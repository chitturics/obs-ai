"""Fine-Grained RBAC — per-tool, per-collection, per-resource access control.

Extends the existing coarse role hierarchy (VIEWER < USER < ANALYST < ADMIN)
with granular permissions that can be:
- Assigned per role (role → permission set)
- Overridden per user (user → additional grants/denials)
- Scoped to specific resources (tool:splunk_search:execute, collection:spl_docs:read)

Permission format: ``{resource_type}:{resource_id}:{action}``

Examples:
    tool:splunk_search:execute
    collection:spl_docs:read
    config:llm:update
    admin:users:manage
    workflow:*:approve
    *:*:read                     (read anything)

Wildcards:
    - ``*`` matches any segment
    - ``tool:*:execute`` = execute any tool
    - ``*:*:*`` = full access (ADMIN default)

Usage:
    from chat_app.rbac import check_permission, require_permission

    # In endpoint
    @router.post("/tools/{tool_name}/execute")
    async def execute_tool(tool_name: str, user=Depends(require_permission("tool", tool_name, "execute"))):
        ...

    # Programmatic check
    allowed = check_permission(user, "collection", "spl_docs", "delete")
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set

from fastapi import Depends, HTTPException

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role hierarchy — higher roles inherit lower role permissions
# ---------------------------------------------------------------------------

ROLE_HIERARCHY: Dict[str, int] = {
    "VIEWER": 0,
    "USER": 1,
    "ANALYST": 2,
    "ADMIN": 3,
}

# ---------------------------------------------------------------------------
# Default permission sets per role
# ---------------------------------------------------------------------------

# Permissions are strings: "resource_type:resource_id:action"
# Wildcards: * matches any segment

_DEFAULT_ROLE_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    "VIEWER": frozenset({
        # Read-only access
        "*:*:read",
        "tool:base64_encode:execute",
        "tool:base64_decode:execute",
        "tool:url_encode:execute",
        "tool:url_decode:execute",
        "tool:hex_encode:execute",
        "tool:hex_decode:execute",
        "tool:json_prettify:execute",
        "tool:json_minify:execute",
        "tool:timestamp_convert:execute",
        "tool:uuid_generate:execute",
        "tool:regex_test:execute",
        "dashboard:*:view",
        "audit:*:read",
    }),
    "USER": frozenset({
        # Inherits VIEWER + search/execute
        "tool:*:execute",
        "collection:*:search",
        "workflow:*:view",
        "feedback:*:submit",
        "chat:*:use",
    }),
    "ANALYST": frozenset({
        # Inherits USER + advanced analysis
        "collection:*:create",
        "collection:*:reindex",
        "tool:*:configure",
        "workflow:*:create",
        "workflow:*:execute",
        "report:*:create",
        "report:*:export",
        "config:*:read",
        "audit:*:export",
    }),
    "ADMIN": frozenset({
        # Full access
        "*:*:*",
    }),
}


# ---------------------------------------------------------------------------
# Permission matching
# ---------------------------------------------------------------------------

def _permission_matches(granted: str, requested: str) -> bool:
    """Check if a granted permission matches a requested permission.

    Supports wildcards: ``*`` matches any single segment.
    ``*:*:*`` matches everything.
    """
    granted_parts = granted.split(":")
    requested_parts = requested.split(":")

    # Pad to 3 parts
    while len(granted_parts) < 3:
        granted_parts.append("*")
    while len(requested_parts) < 3:
        requested_parts.append("*")

    for grant_seg, req_seg in zip(granted_parts[:3], requested_parts[:3]):
        if grant_seg == "*" or req_seg == "*":
            continue
        if grant_seg != req_seg:
            return False
    return True


def _get_effective_permissions(role: str) -> Set[str]:
    """Get all permissions for a role, including inherited from lower roles."""
    role_level = ROLE_HIERARCHY.get(role, 0)
    permissions: Set[str] = set()

    for r, level in ROLE_HIERARCHY.items():
        if level <= role_level:
            permissions.update(_DEFAULT_ROLE_PERMISSIONS.get(r, set()))

    return permissions


# ---------------------------------------------------------------------------
# Per-user overrides (persisted to JSON)
# ---------------------------------------------------------------------------

_USER_OVERRIDES_PATH = Path(os.getenv("RBAC_OVERRIDES_PATH", "/app/data/rbac_overrides.json"))
_user_overrides: Dict[str, Dict[str, List[str]]] = {}  # username -> {"grants": [...], "denials": [...]}
_overrides_lock = threading.Lock()
_overrides_loaded = False


def _load_overrides() -> None:
    """Load per-user permission overrides from JSON file."""
    global _user_overrides, _overrides_loaded
    if _overrides_loaded:
        return
    _overrides_loaded = True

    if _USER_OVERRIDES_PATH.exists():
        try:
            with open(_USER_OVERRIDES_PATH, "r") as fh:
                _user_overrides = json.load(fh)
            logger.info("[RBAC] Loaded %d user permission overrides", len(_user_overrides))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("[RBAC] Failed to load overrides: %s", exc)


def _save_overrides() -> None:
    """Persist per-user permission overrides to JSON file."""
    try:
        _USER_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_USER_OVERRIDES_PATH, "w") as fh:
            json.dump(_user_overrides, fh, indent=2)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.error("[RBAC] Failed to save overrides: %s", exc)


def set_user_overrides(
    username: str,
    grants: Optional[List[str]] = None,
    denials: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Set permission overrides for a specific user.

    Args:
        username: The user identifier.
        grants: Additional permissions to grant (beyond role defaults).
        denials: Permissions to explicitly deny (override role defaults).

    Returns:
        The updated override entry.
    """
    with _overrides_lock:
        _load_overrides()
        entry = _user_overrides.get(username, {"grants": [], "denials": []})
        if grants is not None:
            entry["grants"] = grants
        if denials is not None:
            entry["denials"] = denials
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        _user_overrides[username] = entry
        _save_overrides()
    return entry


def get_user_overrides(username: str) -> Dict[str, Any]:
    """Get permission overrides for a specific user."""
    with _overrides_lock:
        _load_overrides()
        return _user_overrides.get(username, {"grants": [], "denials": []})


def list_all_overrides() -> Dict[str, Dict[str, Any]]:
    """List all user permission overrides."""
    with _overrides_lock:
        _load_overrides()
        return dict(_user_overrides)


def delete_user_overrides(username: str) -> bool:
    """Remove all permission overrides for a user."""
    with _overrides_lock:
        _load_overrides()
        if username in _user_overrides:
            del _user_overrides[username]
            _save_overrides()
            return True
    return False


# ---------------------------------------------------------------------------
# Permission checking
# ---------------------------------------------------------------------------

def check_permission(
    user: Dict[str, Any],
    resource_type: str,
    resource_id: str = "*",
    action: str = "read",
) -> bool:
    """Check whether a user has a specific permission.

    Args:
        user: User dict with ``identifier`` and ``metadata.role``.
        resource_type: The resource category (tool, collection, config, admin, etc.)
        resource_id: The specific resource (tool name, collection name, etc.)
        action: The action (read, execute, create, update, delete, manage, etc.)

    Returns:
        True if the user has the permission, False otherwise.
    """
    role = user.get("metadata", {}).get("role", "USER")
    username = user.get("identifier", "unknown")
    requested = f"{resource_type}:{resource_id}:{action}"

    # Get role permissions (with inheritance)
    permissions = _get_effective_permissions(role)

    # Apply per-user overrides
    with _overrides_lock:
        _load_overrides()
        overrides = _user_overrides.get(username, {})

    # Explicit denials take precedence
    for denial in overrides.get("denials", []):
        if _permission_matches(denial, requested):
            logger.debug("[RBAC] DENIED %s for %s (explicit denial: %s)", requested, username, denial)
            return False

    # Check role permissions
    for perm in permissions:
        if _permission_matches(perm, requested):
            return True

    # Check per-user grants
    for grant in overrides.get("grants", []):
        if _permission_matches(grant, requested):
            return True

    logger.debug("[RBAC] DENIED %s for %s (role=%s, no matching permission)", requested, username, role)
    return False


def get_user_permissions(user: Dict[str, Any]) -> Dict[str, Any]:
    """Get the full permission set for a user (role + overrides).

    Returns a summary useful for UI display and debugging.
    """
    role = user.get("metadata", {}).get("role", "USER")
    username = user.get("identifier", "unknown")
    role_perms = _get_effective_permissions(role)

    with _overrides_lock:
        _load_overrides()
        overrides = _user_overrides.get(username, {"grants": [], "denials": []})

    return {
        "username": username,
        "role": role,
        "role_level": ROLE_HIERARCHY.get(role, 0),
        "role_permissions": sorted(role_perms),
        "grants": overrides.get("grants", []),
        "denials": overrides.get("denials", []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def require_permission(
    resource_type: str,
    resource_id: str = "*",
    action: str = "read",
):
    """FastAPI dependency factory that checks fine-grained permissions.

    Usage:
        @router.get("/collections/{name}")
        async def get_collection(name: str, user=Depends(require_permission("collection", name, "read"))):
            ...

    For dynamic resource_id (from path params), use a wrapper:
        async def endpoint(name: str, user=Depends(get_authenticated_user)):
            if not check_permission(user, "collection", name, "read"):
                raise HTTPException(403, "Access denied")
    """
    from chat_app.auth_dependencies import get_authenticated_user

    async def _check(user: dict = Depends(get_authenticated_user)) -> dict:
        if not check_permission(user, resource_type, resource_id, action):
            role = user.get("metadata", {}).get("role", "USER")
            raise HTTPException(
                status_code=403,
                detail={
                    "error": {
                        "code": "PERMISSION_DENIED",
                        "message": f"Permission denied: {resource_type}:{resource_id}:{action}",
                        "details": {
                            "required_permission": f"{resource_type}:{resource_id}:{action}",
                            "your_role": role,
                        },
                    }
                },
            )
        return user

    return _check


# ---------------------------------------------------------------------------
# Utility: list all default permissions
# ---------------------------------------------------------------------------

def get_default_permissions() -> Dict[str, List[str]]:
    """Return the default permission sets for all roles."""
    return {role: sorted(perms) for role, perms in _DEFAULT_ROLE_PERMISSIONS.items()}
