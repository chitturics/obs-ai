"""SCIM 2.0 User Provisioning — automated user lifecycle management.

Implements SCIM (System for Cross-domain Identity Management) endpoints
for automated user provisioning from identity providers like Okta, Azure AD, etc.

Endpoints:
- GET    /scim/v2/Users          — List/filter users
- GET    /scim/v2/Users/{id}     — Get user by ID
- POST   /scim/v2/Users          — Create user
- PUT    /scim/v2/Users/{id}     — Replace user
- PATCH  /scim/v2/Users/{id}     — Update user (partial)
- DELETE /scim/v2/Users/{id}     — Deactivate user

SCIM schema: urn:ietf:params:scim:schemas:core:2.0:User

Usage:
    from chat_app.scim import scim_router
    # Mount in FastAPI app
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SCIM schema constants
# ---------------------------------------------------------------------------

SCIM_SCHEMA_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_SCHEMA_LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_SCHEMA_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"

_SCIM_USERS_FILE = Path(os.getenv("SCIM_USERS_FILE", "/app/data/scim_users.json"))


# ---------------------------------------------------------------------------
# SCIM User model
# ---------------------------------------------------------------------------

class SCIMUser:
    """Internal representation of a SCIM-provisioned user."""

    def __init__(self, data: Dict[str, Any]):
        self.id = data.get("id", str(uuid.uuid4()))
        self.external_id = data.get("externalId", "")
        self.user_name = data.get("userName", "")
        self.display_name = data.get("displayName", "")
        self.active = data.get("active", True)
        self.emails = data.get("emails", [])
        self.groups = data.get("groups", [])
        self.roles = data.get("roles", ["USER"])
        self.meta = data.get("meta", {
            "resourceType": "User",
            "created": datetime.now(timezone.utc).isoformat(),
            "lastModified": datetime.now(timezone.utc).isoformat(),
        })

    @property
    def primary_email(self) -> str:
        for email in self.emails:
            if isinstance(email, dict) and email.get("primary"):
                return email.get("value", "")
        if self.emails and isinstance(self.emails[0], dict):
            return self.emails[0].get("value", "")
        if self.emails and isinstance(self.emails[0], str):
            return self.emails[0]
        return ""

    def to_scim(self) -> Dict[str, Any]:
        """Serialize to SCIM 2.0 JSON."""
        return {
            "schemas": [SCIM_SCHEMA_USER],
            "id": self.id,
            "externalId": self.external_id,
            "userName": self.user_name,
            "displayName": self.display_name,
            "active": self.active,
            "emails": self.emails,
            "groups": self.groups,
            "roles": [{"value": r} for r in self.roles],
            "meta": self.meta,
        }

    def to_storage(self) -> Dict[str, Any]:
        """Serialize for persistence."""
        return {
            "id": self.id,
            "externalId": self.external_id,
            "userName": self.user_name,
            "displayName": self.display_name,
            "active": self.active,
            "emails": self.emails,
            "groups": self.groups,
            "roles": self.roles,
            "meta": self.meta,
        }


# ---------------------------------------------------------------------------
# SCIM User Store
# ---------------------------------------------------------------------------

class SCIMUserStore:
    """Persistent store for SCIM-provisioned users."""

    def __init__(self):
        self._users: Dict[str, SCIMUser] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not _SCIM_USERS_FILE.exists():
            return
        try:
            with open(_SCIM_USERS_FILE) as fh:
                data = json.load(fh)
            for uid, udata in data.items():
                self._users[uid] = SCIMUser(udata)
            logger.info("[SCIM] Loaded %d users", len(self._users))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("[SCIM] Failed to load users: %s", exc)

    def _save(self) -> None:
        try:
            _SCIM_USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_SCIM_USERS_FILE, "w") as fh:
                json.dump({uid: u.to_storage() for uid, u in self._users.items()}, fh, indent=2)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("[SCIM] Failed to save users: %s", exc)

    def create(self, data: Dict[str, Any]) -> SCIMUser:
        user = SCIMUser(data)
        # Check for duplicate userName
        for existing in self._users.values():
            if existing.user_name == user.user_name:
                raise ValueError(f"User already exists: {user.user_name}")
        with self._lock:
            self._users[user.id] = user
            self._save()
        return user

    def get(self, user_id: str) -> Optional[SCIMUser]:
        return self._users.get(user_id)

    def get_by_username(self, username: str) -> Optional[SCIMUser]:
        for user in self._users.values():
            if user.user_name == username:
                return user
        return None

    def update(self, user_id: str, data: Dict[str, Any]) -> Optional[SCIMUser]:
        user = self._users.get(user_id)
        if not user:
            return None
        # Update fields
        if "userName" in data:
            user.user_name = data["userName"]
        if "displayName" in data:
            user.display_name = data["displayName"]
        if "active" in data:
            user.active = data["active"]
        if "emails" in data:
            user.emails = data["emails"]
        if "groups" in data:
            user.groups = data["groups"]
        if "roles" in data:
            user.roles = data["roles"]
        if "externalId" in data:
            user.external_id = data["externalId"]
        user.meta["lastModified"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._save()
        return user

    def delete(self, user_id: str) -> bool:
        """Soft-delete: set active=False."""
        user = self._users.get(user_id)
        if not user:
            return False
        user.active = False
        user.meta["lastModified"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._save()
        return True

    def list_users(
        self,
        start_index: int = 1,
        count: int = 100,
        filter_str: Optional[str] = None,
    ) -> tuple:
        """List users with optional SCIM filter. Returns (users, total_count)."""
        users = list(self._users.values())

        # Basic SCIM filter support (userName eq "value")
        if filter_str:
            filter_str = filter_str.strip()
            if 'userName eq' in filter_str:
                value = filter_str.split('"')[1] if '"' in filter_str else ""
                users = [u for u in users if u.user_name == value]
            elif 'active eq' in filter_str:
                is_active = 'true' in filter_str.lower()
                users = [u for u in users if u.active == is_active]

        total = len(users)
        # Pagination (SCIM uses 1-based indexing)
        start = max(0, start_index - 1)
        page = users[start:start + count]
        return page, total

    def get_stats(self) -> Dict[str, Any]:
        active = sum(1 for u in self._users.values() if u.active)
        return {
            "total_users": len(self._users),
            "active_users": active,
            "inactive_users": len(self._users) - active,
        }


# ---------------------------------------------------------------------------
# SCIM Router
# ---------------------------------------------------------------------------

_store: Optional[SCIMUserStore] = None


def _get_store() -> SCIMUserStore:
    global _store
    if _store is None:
        _store = SCIMUserStore()
    return _store


# Bearer token auth for SCIM endpoints
async def _scim_auth(request: Request) -> None:
    """Validate SCIM bearer token with timing-safe comparison.

    SECURITY: Rejects ALL requests if SCIM_BEARER_TOKEN is not configured.
    No dev-mode bypass — SCIM provisioning requires explicit token setup.
    """
    import secrets as _secrets

    expected = os.getenv("SCIM_BEARER_TOKEN", "").strip()
    if not expected:
        logger.warning("[SCIM] Request rejected — SCIM_BEARER_TOKEN not configured")
        raise HTTPException(status_code=503, detail={"schemas": [SCIM_SCHEMA_ERROR],
                            "detail": "SCIM provisioning not configured", "status": "503"})

    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"schemas": [SCIM_SCHEMA_ERROR],
                            "detail": "Bearer token required", "status": "401"})

    token = auth_header[7:].strip()
    # Timing-safe comparison to prevent side-channel attacks
    if not _secrets.compare_digest(token.encode(), expected.encode()):
        logger.warning("[SCIM] Invalid bearer token from %s", request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail={"schemas": [SCIM_SCHEMA_ERROR],
                            "detail": "Invalid SCIM token", "status": "401"})


scim_router = APIRouter(
    prefix="/scim/v2",
    tags=["scim"],
    dependencies=[Depends(_scim_auth)],
)


@scim_router.get("/Users")
async def list_scim_users(
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=1, le=1000),
    filter: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """SCIM 2.0 List Users."""
    store = _get_store()
    users, total = store.list_users(start_index=startIndex, count=count, filter_str=filter)
    return {
        "schemas": [SCIM_SCHEMA_LIST],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(users),
        "Resources": [u.to_scim() for u in users],
    }


@scim_router.get("/Users/{user_id}")
async def get_scim_user(user_id: str) -> Dict[str, Any]:
    """SCIM 2.0 Get User."""
    user = _get_store().get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"schemas": [SCIM_SCHEMA_ERROR],
                            "detail": "User not found", "status": "404"})
    return user.to_scim()


@scim_router.post("/Users", status_code=201)
async def create_scim_user(request: Request) -> Dict[str, Any]:
    """SCIM 2.0 Create User."""
    body = await request.json()
    try:
        user = _get_store().create(body)
        logger.info("[SCIM] User created: %s (%s)", user.user_name, user.id)
        return user.to_scim()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"schemas": [SCIM_SCHEMA_ERROR],
                            "detail": str(exc), "status": "409"})


@scim_router.put("/Users/{user_id}")
async def replace_scim_user(user_id: str, request: Request) -> Dict[str, Any]:
    """SCIM 2.0 Replace User."""
    body = await request.json()
    user = _get_store().update(user_id, body)
    if not user:
        raise HTTPException(status_code=404, detail={"schemas": [SCIM_SCHEMA_ERROR],
                            "detail": "User not found", "status": "404"})
    return user.to_scim()


@scim_router.patch("/Users/{user_id}")
async def patch_scim_user(user_id: str, request: Request) -> Dict[str, Any]:
    """SCIM 2.0 Patch User (partial update)."""
    body = await request.json()
    # SCIM PATCH uses Operations format, simplify to direct field updates
    operations = body.get("Operations", [])
    updates = {}
    for op in operations:
        path = op.get("path", "")
        value = op.get("value")
        if path == "active":
            updates["active"] = value
        elif path == "displayName":
            updates["displayName"] = value
        elif path == "userName":
            updates["userName"] = value
    if not updates and body.get("active") is not None:
        updates["active"] = body["active"]

    user = _get_store().update(user_id, updates)
    if not user:
        raise HTTPException(status_code=404, detail={"schemas": [SCIM_SCHEMA_ERROR],
                            "detail": "User not found", "status": "404"})
    return user.to_scim()


@scim_router.delete("/Users/{user_id}", status_code=204)
async def delete_scim_user(user_id: str):
    """SCIM 2.0 Delete User (soft-delete: sets active=False)."""
    if not _get_store().delete(user_id):
        raise HTTPException(status_code=404, detail={"schemas": [SCIM_SCHEMA_ERROR],
                            "detail": "User not found", "status": "404"})
    return None
