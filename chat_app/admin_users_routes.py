"""Admin sub-router: User management, roles, tokens, and auth provider endpoints.

Handles these endpoint groups:
- GET  /api/admin/roles                     — List all roles
- POST /api/admin/roles                     — Create custom role
- DELETE /api/admin/roles/{role_name}       — Delete custom role
- GET  /api/admin/users                     — List all users
- POST /api/admin/users                     — Create a user
- PUT  /api/admin/users/{username}          — Update a user
- DELETE /api/admin/users/{username}        — Delete a user
- GET  /api/admin/users/{username}/activity — User activity
- POST /api/admin/tokens                    — Create API token
- GET  /api/admin/tokens                    — List API tokens
- DELETE /api/admin/tokens/{token_id}       — Revoke API token
- GET  /api/admin/auth/providers            — List auth providers
- GET  /api/admin/auth/oidc/login-url       — OIDC login URL

Mount with:
    from chat_app.admin_users_routes import users_router
    router.include_router(users_router)
"""

import json as _json
import logging
import uuid

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import (
    create_api_token,
    get_authenticated_user,
    list_api_tokens,
    require_admin,
    revoke_api_token,
)
from chat_app.settings import get_settings
from chat_app.admin_shared import (
    _append_audit,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _safe_error,
    _track_audit_user,
    _validate_password_complexity,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

users_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-users"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_engine():
    """Attempt to retrieve the database engine from the app_api module."""
    try:
        from chat_app import app_api
        return getattr(app_api, "engine", None)
    except Exception as _exc:  # broad catch — resilience against all failures
        return None


_DEFAULT_ROLES = ["ADMIN", "USER", "ANALYST", "VIEWER"]
_CUSTOM_ROLES_FILE = Path("/app/data/custom_roles.json")


def _load_custom_roles() -> list:
    """Load custom roles from persistent JSON file."""
    try:
        if _CUSTOM_ROLES_FILE.is_file():
            data = _json.loads(_CUSTOM_ROLES_FILE.read_text())
            return data if isinstance(data, list) else []
    except (OSError, ValueError, KeyError, TypeError, _json.JSONDecodeError) as exc:
        logger.warning("[ADMIN] Failed to load custom roles: %s", exc)
    try:
        fallback = _PROJECT_ROOT / "data" / "custom_roles.json"
        if fallback.is_file():
            data = _json.loads(fallback.read_text())
            return data if isinstance(data, list) else []
    except (OSError, ValueError, KeyError, TypeError, _json.JSONDecodeError) as exc:
        logger.debug("[ADMIN] Failed to load custom roles from fallback path: %s", exc)
    return []


def _save_custom_roles(roles: list):
    """Persist custom roles to JSON file."""
    for p in [_CUSTOM_ROLES_FILE, _PROJECT_ROOT / "data" / "custom_roles.json"]:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_json.dumps(roles, indent=2))
            return
        except (OSError, ValueError, KeyError, TypeError, _json.JSONDecodeError) as exc:
            logger.warning("[ADMIN] Failed to save custom roles: %s", exc)
            continue


def _get_available_roles() -> list:
    """Return all roles: built-in + custom."""
    custom = _load_custom_roles()
    custom_names = [r["name"] for r in custom if isinstance(r, dict) and "name" in r]
    return _DEFAULT_ROLES + [n for n in custom_names if n not in _DEFAULT_ROLES]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateRoleRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=30)
    description: str = Field(default="", max_length=200)
    permissions: list = Field(default_factory=list)


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "USER"


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    password: Optional[str] = None


class _TokenCreateRequest(BaseModel):
    """Request body for creating an API token."""
    label: str = Field(default="", description="Human-readable label for this token")
    role: str = Field(default="ADMIN", description="Role assigned to this token")


# ---------------------------------------------------------------------------
# Role Management
# ---------------------------------------------------------------------------

@users_router.get("/roles", summary="List all roles")
async def list_roles(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all available roles with descriptions and permissions."""
    built_in = {
        "ADMIN": {"description": "Full access to all settings, user management, and system configuration.", "permissions": ["All admin API endpoints", "User CRUD", "Config changes", "Container management", "Backup/restore", "Ingestion"], "builtin": True},
        "USER": {"description": "Standard chat access with personal settings.", "permissions": ["Chat assistant", "Personal settings", "File uploads", "Slash commands"], "builtin": True},
        "ANALYST": {"description": "Can view dashboards, run queries, and access read-only analytics.", "permissions": ["Dashboard access", "Collections browsing", "SPL command reference", "Knowledge graph queries", "Read-only settings"], "builtin": True},
        "VIEWER": {"description": "Read-only access. Can view but not modify anything.", "permissions": ["Chat (read-only)", "View dashboard", "View documentation"], "builtin": True},
    }
    custom = _load_custom_roles()
    roles = []
    for name, info in built_in.items():
        roles.append({"name": name, **info})
    for r in custom:
        if isinstance(r, dict) and r.get("name") not in built_in:
            roles.append({**r, "builtin": False})
    total = len(roles)
    page = roles[offset:offset + limit]
    return {"roles": page, "total": total}


@users_router.post("/roles", summary="Create a custom role")
async def create_role(req: CreateRoleRequest):
    """Create a new custom role."""
    role_name = req.name.upper().replace(" ", "_")
    all_roles = _get_available_roles()
    if role_name in all_roles:
        raise HTTPException(status_code=409, detail=f"Role '{role_name}' already exists")
    custom = _load_custom_roles()
    custom.append({"name": role_name, "description": req.description, "permissions": req.permissions})
    _save_custom_roles(custom)
    _append_audit("roles", "create", {"role": role_name}, {})
    return {"status": "created", "role": role_name}


@users_router.delete("/roles/{role_name}", summary="Delete a custom role")
async def delete_role(role_name: str):
    """Delete a custom role (built-in roles cannot be deleted)."""
    if role_name.upper() in _DEFAULT_ROLES:
        raise HTTPException(status_code=403, detail=f"Cannot delete built-in role '{role_name}'")
    custom = _load_custom_roles()
    new_custom = [r for r in custom if not (isinstance(r, dict) and r.get("name") == role_name.upper())]
    if len(new_custom) == len(custom):
        raise HTTPException(status_code=404, detail=f"Custom role '{role_name}' not found")
    _save_custom_roles(new_custom)
    _append_audit("roles", "delete", {"role": role_name}, {})
    return {"status": "deleted", "role": role_name}


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@users_router.get("/users")
async def list_users(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all users with their roles and activity stats."""
    engine = _get_engine()
    if not engine:
        settings = get_settings()
        fallback = [{
            "username": settings.auth.admin_user or "admin",
            "role": "ADMIN",
            "provider": "env",
            "created_at": None,
            "query_count": 0,
            "thread_count": 0,
            "last_active": None,
        }]
        return {"users": fallback, "total": 1, "roles": _get_available_roles()}

    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            result = await conn.execute(text(
                'SELECT u."id", u."identifier", u."metadata", u."createdAt",'
                '  COALESCE(i.query_count, 0) AS query_count,'
                '  COALESCE(t.thread_count, 0) AS thread_count,'
                '  i.last_active'
                ' FROM users u'
                ' LEFT JOIN ('
                '   SELECT username, COUNT(*) AS query_count,'
                '     MAX(created_at) AS last_active'
                '   FROM assistant_interactions GROUP BY username'
                ' ) i ON u."identifier" = i.username'
                ' LEFT JOIN ('
                '   SELECT "userIdentifier", COUNT(*) AS thread_count'
                '   FROM threads GROUP BY "userIdentifier"'
                ' ) t ON u."identifier" = t."userIdentifier"'
                ' ORDER BY u."identifier"'
            ))
            rows = result.fetchall()

            users = []
            for row in rows:
                meta = row[2] if isinstance(row[2], dict) else {}
                last_active = row[6]
                users.append({
                    "id": str(row[0]),
                    "username": row[1],
                    "role": meta.get("role", "USER"),
                    "provider": meta.get("provider", "unknown"),
                    "created_at": row[3],
                    "query_count": row[4],
                    "thread_count": row[5],
                    "last_active": str(last_active) if last_active else None,
                    "metadata": {k: v for k, v in meta.items()
                                 if k not in ("password_hash", "salt")},
                })

        total = len(users)
        page = users[offset:offset + limit]
        return {"users": page, "total": total, "roles": _get_available_roles()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@users_router.post("/users")
async def create_user(req: CreateUserRequest):
    """Create a new user."""
    engine = _get_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Database not available")

    if req.role not in _get_available_roles():
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {_get_available_roles()}")

    _validate_password_complexity(req.password)

    import bcrypt

    password_hash = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()

    try:
        from sqlalchemy import text

        user_id = str(uuid.uuid4())
        metadata = {
            "role": req.role,
            "provider": "credentials",
            "password_hash": password_hash,
        }

        async with engine.begin() as conn:
            existing = await conn.execute(text(
                'SELECT "id" FROM users WHERE "identifier" = :u'
            ), {"u": req.username})
            if existing.fetchone():
                raise HTTPException(status_code=409, detail=f"User '{req.username}' already exists")

            await conn.execute(text(
                'INSERT INTO users ("id", "identifier", "metadata", "createdAt") '
                "VALUES (:id, :ident, :meta, :ts)"
            ), {
                "id": user_id,
                "ident": req.username,
                "meta": _json.dumps(metadata),
                "ts": _now_iso(),
            })

        _append_audit("users", "create", {"username": req.username, "role": req.role}, {})
        return {"status": "created", "username": req.username, "role": req.role, "id": user_id}
    except HTTPException:
        raise
    except (OSError, ValueError, KeyError, TypeError, _json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@users_router.put("/users/{username}")
async def update_user(username: str, req: UpdateUserRequest):
    """Update a user's role or password."""
    engine = _get_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Database not available")

    if req.role and req.role not in _get_available_roles():
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {_get_available_roles()}")

    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            result = await conn.execute(text(
                'SELECT "id", "metadata" FROM users WHERE "identifier" = :u'
            ), {"u": username})
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"User '{username}' not found")

            meta = row[1] if isinstance(row[1], dict) else _json.loads(row[1]) if row[1] else {}
            previous = {"role": meta.get("role")}

            if req.role:
                meta["role"] = req.role
            if req.password:
                _validate_password_complexity(req.password)
                import bcrypt
                meta["password_hash"] = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
                meta.pop("salt", None)

            await conn.execute(text(
                'UPDATE users SET "metadata" = :meta WHERE "identifier" = :u'
            ), {"meta": _json.dumps(meta), "u": username})

        changes = {}
        if req.role:
            changes["role"] = req.role
        if req.password:
            changes["password"] = "***changed***"
        _append_audit("users", "update", changes, previous)
        return {"status": "updated", "username": username, "changes": changes}
    except HTTPException:
        raise
    except (OSError, ValueError, KeyError, TypeError, _json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@users_router.delete("/users/{username}")
async def delete_user(username: str):
    """Delete a user and all their data."""
    engine = _get_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Database not available")

    _s = get_settings()
    if username == _s.auth.admin_user:
        raise HTTPException(status_code=403, detail="Cannot delete the admin user")

    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            result = await conn.execute(text(
                'SELECT "id" FROM users WHERE "identifier" = :u'
            ), {"u": username})
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"User '{username}' not found")

            await conn.execute(text(
                'DELETE FROM users WHERE "identifier" = :u'
            ), {"u": username})

            for table in ["assistant_interactions", "assistant_feedback",
                          "assistant_liked_queries", "assistant_disliked_queries",
                          "assistant_notes", "assistant_episodes"]:
                await conn.execute(text(
                    f'DELETE FROM {table} WHERE "username" = :u'
                ), {"u": username})

        _append_audit("users", "delete", {"username": username}, {})
        return {"status": "deleted", "username": username}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@users_router.get("/users/{username}/activity")
async def user_activity(
    username: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Get a user's recent activity."""
    engine = _get_engine()
    if not engine:
        return {"activity": [], "total": 0}

    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            count_result = await conn.execute(text(
                "SELECT COUNT(*) FROM assistant_interactions WHERE username = :u"
            ), {"u": username})
            total = count_result.scalar() or 0

            result = await conn.execute(text(
                "SELECT question, answer, created_at FROM assistant_interactions "
                "WHERE username = :u ORDER BY created_at DESC LIMIT :lim OFFSET :off"
            ), {"u": username, "lim": limit, "off": offset})
            rows = result.fetchall()

        return {
            "username": username,
            "activity": [
                {"question": r[0][:200] if r[0] else "", "answer_length": len(r[1] or ""),
                 "timestamp": str(r[2])} for r in rows
            ],
            "total": total,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[ADMIN] user activity failed: %s", exc)
        return {"activity": [], "total": 0}


# ---------------------------------------------------------------------------
# API Token Management
# ---------------------------------------------------------------------------

@users_router.post("/tokens", summary="Create a new API token")
async def create_token(
    body: _TokenCreateRequest,
    user: dict = Depends(get_authenticated_user),
):
    """Generate a new API token for programmatic access."""
    valid_roles = {"ADMIN", "USER", "ANALYST", "VIEWER"}
    if body.role.upper() not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Must be one of: {', '.join(sorted(valid_roles))}",
        )
    entry = create_api_token(
        label=body.label,
        role=body.role.upper(),
        created_by=user.get("identifier", "unknown"),
    )
    return {
        "token_id": entry.token_id,
        "key": entry.key,
        "label": entry.label,
        "role": entry.role,
        "created_at": entry.created_at,
        "created_by": entry.created_by,
        "message": "Store this key securely. It will not be shown again.",
    }


@users_router.get("/tokens", summary="List active API tokens")
async def list_tokens(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return all active API tokens with masked keys."""
    all_tokens = list_api_tokens()
    total = len(all_tokens)
    page = all_tokens[offset:offset + limit]
    return {
        "tokens": page,
        "total": total,
        "timestamp": _now_iso(),
    }


@users_router.delete("/tokens/{token_id}", summary="Revoke an API token")
async def delete_token(token_id: str):
    """Revoke an API token by its ID."""
    if not revoke_api_token(token_id):
        raise HTTPException(status_code=404, detail=f"Token '{token_id}' not found")
    return {
        "message": f"Token '{token_id}' has been revoked",
        "token_id": token_id,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Auth Provider Endpoints
# ---------------------------------------------------------------------------

@users_router.get("/auth/providers", summary="List configured auth providers")
async def list_auth_providers():
    """Return all configured authentication providers and their status."""
    try:
        from chat_app.auth_providers import get_all_providers, init_auth_providers
        if not get_all_providers():
            init_auth_providers()
        providers = get_all_providers()
        result = []
        for name, provider in providers.items():
            result.append({
                "name": name,
                "type": provider.provider_type,
                "supports_login_url": bool(provider.get_login_url("")),
            })
        return {
            "providers": result,
            "total": len(result),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[ADMIN] auth providers list failed: %s", exc)
        return {
            "providers": [],
            "total": 0,
            "timestamp": _now_iso(),
        }


@users_router.get("/auth/oidc/login-url", summary="Get OIDC login URL")
async def get_oidc_login_url(
    provider_name: str = Query("oidc", description="Name of the OIDC provider"),
    redirect_uri: str = Query("", description="Redirect URI after authentication"),
    request: Request = None,
):
    """Generate the OIDC authorization URL for browser redirect."""
    from chat_app.auth_providers import get_provider, init_auth_providers, get_all_providers
    if not get_all_providers():
        init_auth_providers()
    provider = get_provider(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")

    if not redirect_uri and request:
        host = request.headers.get("host", "localhost:8000")
        scheme = request.headers.get("x-forwarded-proto", "http")
        redirect_uri = f"{scheme}://{host}/api/admin/auth/oidc/callback"

    login_url = provider.get_login_url(redirect_uri)
    if not login_url:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_name}' does not support login URL generation")
    return {"login_url": login_url, "provider": provider_name, "redirect_uri": redirect_uri}


# ---------------------------------------------------------------------------
# GET /api/admin/users/roles — compact roles list for frontend dropdowns
# ---------------------------------------------------------------------------

@users_router.get("/users/roles", summary="List available user roles")
async def list_user_roles():
    """Return all available user roles as a lightweight list for dropdown menus.

    This endpoint is an alias for /roles that follows the /users/* path
    convention.  It returns only names and descriptions — no pagination — for
    use in user-create and user-edit forms.
    """
    all_role_names = _get_available_roles()
    built_in_meta = {
        "ADMIN":   {"description": "Full admin access to all settings and user management.", "level": 4},
        "ANALYST": {"description": "Read-only analytics, dashboards, and collection browsing.", "level": 3},
        "USER":    {"description": "Standard chat access with personal settings.", "level": 2},
        "VIEWER":  {"description": "Read-only access. View but cannot modify.", "level": 1},
    }
    roles = []
    for name in all_role_names:
        meta = built_in_meta.get(name, {"description": "Custom role.", "level": 0})
        roles.append({
            "name": name,
            "description": meta["description"],
            "level": meta["level"],
            "builtin": name in built_in_meta,
        })
    # Sort by descending privilege level so the most privileged role appears first.
    roles.sort(key=lambda r: r["level"], reverse=True)
    return {
        "roles": roles,
        "total": len(roles),
        "timestamp": _now_iso(),
    }
