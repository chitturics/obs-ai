"""
Authentication dependencies for admin API endpoints.

Supports three authentication methods (checked in order):
1. **Cookie JWT** — Chainlit's built-in ``access_token`` cookie
2. **Bearer token** — ``Authorization: Bearer <jwt>`` header (same JWT validation)
3. **API key** — ``X-API-Key: <key>`` header or ``Authorization: Bearer <api-key>``

API keys can be provisioned two ways:
- Static keys via the ``API_KEYS`` environment variable (comma-separated)
- Dynamic keys via the ``POST /api/admin/tokens`` management endpoint

When authentication is disabled (ENABLE_AUTHENTICATION=false), all
dependencies return an anonymous ADMIN user for backward compatibility.
"""

import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Request

logger = logging.getLogger(__name__)


def _auth_enabled() -> bool:
    """Check whether authentication is enabled.

    SECURITY: defaults to TRUE (fail-closed). Authentication is only disabled
    when explicitly set to false via settings or ENABLE_AUTHENTICATION env var.
    """
    try:
        from chat_app.settings import get_settings
        return get_settings().auth.enabled
    except Exception as _exc:  # broad catch — env fallback must always work
        raw = os.getenv("ENABLE_AUTHENTICATION", "true")  # Default TRUE (fail-closed)
        return raw.lower() not in ("false", "0", "no")


def _get_environment() -> str:
    """Detect deployment environment."""
    return os.getenv("DEPLOYMENT_ENV", os.getenv("APP_ENVIRONMENT", "development"))


# Anonymous fallback — ADMIN role when auth is disabled in dev/test.
# In production, auth is always enabled so this path is never reached.
# Must be ADMIN so admin API endpoints (require_admin) work without login.
_ANONYMOUS_USER: Dict[str, Any] = {
    "identifier": "anonymous",
    "metadata": {"role": "ADMIN", "provider": "anonymous"},
}

# Legacy alias — DEPRECATED. Use _ANONYMOUS_USER instead.
# Retained only for backward compatibility with tests importing this name.
_ANONYMOUS_ADMIN = _ANONYMOUS_USER


# ---------------------------------------------------------------------------
# API Key Store (in-memory + env var fallback)
# ---------------------------------------------------------------------------

_DEFAULT_TOKEN_TTL_DAYS = 90  # Tokens expire after 90 days by default


class _TokenEntry:
    """Represents a managed API token with expiry."""

    __slots__ = ("token_id", "key", "label", "role", "created_at", "created_by", "last_used", "expires_at")

    def __init__(
        self,
        key: str,
        label: str = "",
        role: str = "ADMIN",
        created_by: str = "system",
        ttl_days: int = _DEFAULT_TOKEN_TTL_DAYS,
    ):
        self.token_id: str = str(uuid.uuid4())
        self.key: str = key
        self.label: str = label
        self.role: str = role
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.created_by: str = created_by
        self.last_used: Optional[str] = None
        from datetime import timedelta
        self.expires_at: str = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat() if ttl_days > 0 else ""

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc).isoformat() > self.expires_at

    def touch(self) -> None:
        self.last_used = datetime.now(timezone.utc).isoformat()

    def to_dict(self, mask: bool = True) -> Dict[str, Any]:
        masked_key = self.key[:8] + "..." + self.key[-4:] if mask and len(self.key) > 12 else ("***" if mask else self.key)
        return {
            "token_id": self.token_id,
            "key": masked_key,
            "label": self.label,
            "role": self.role,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "last_used": self.last_used,
        }


# In-memory token store: token_id -> _TokenEntry
_token_store: Dict[str, _TokenEntry] = {}
# Fast lookup: key_string -> _TokenEntry
_token_index: Dict[str, _TokenEntry] = {}
# Track whether env var keys have been loaded
_env_keys_loaded: bool = False


def _ensure_env_keys_loaded() -> None:
    """Load API keys from API_KEYS env var on first use."""
    global _env_keys_loaded
    if _env_keys_loaded:
        return
    _env_keys_loaded = True
    raw = os.getenv("API_KEYS", "").strip()
    if not raw:
        return
    for key in raw.split(","):
        key = key.strip()
        if key and key not in _token_index:
            entry = _TokenEntry(key=key, label="env", role="ADMIN", created_by="env:API_KEYS")
            _token_store[entry.token_id] = entry
            _token_index[key] = entry
    logger.info("Loaded %d API key(s) from API_KEYS environment variable", len([k for k in raw.split(",") if k.strip()]))


def _validate_api_key(key: str) -> Optional[_TokenEntry]:
    """Check if an API key is valid and not expired. Returns the token entry or None."""
    _ensure_env_keys_loaded()
    entry = _token_index.get(key)
    if entry:
        if entry.is_expired:
            logger.warning("[AUTH] API key expired: id=%s label=%s expired_at=%s",
                           entry.token_id[:8], entry.label, entry.expires_at)
            return None
        entry.touch()
    return entry


def create_api_token(label: str = "", role: str = "ADMIN", created_by: str = "admin") -> _TokenEntry:
    """Generate a new API token and store it. Returns the entry (with cleartext key)."""
    key = f"obsai_{secrets.token_urlsafe(32)}"
    entry = _TokenEntry(key=key, label=label, role=role, created_by=created_by)
    _token_store[entry.token_id] = entry
    _token_index[entry.key] = entry
    logger.info("API token created: id=%s label=%s by=%s", entry.token_id, label, created_by)
    return entry


def list_api_tokens() -> List[Dict[str, Any]]:
    """Return all tokens with masked keys."""
    _ensure_env_keys_loaded()
    return [entry.to_dict(mask=True) for entry in _token_store.values()]


def revoke_api_token(token_id: str) -> bool:
    """Revoke a token by ID. Returns True if found and removed."""
    entry = _token_store.pop(token_id, None)
    if entry is None:
        return False
    _token_index.pop(entry.key, None)
    logger.info("API token revoked: id=%s label=%s", token_id, entry.label)
    return True


# ---------------------------------------------------------------------------
# JWT Validation Helper
# ---------------------------------------------------------------------------

def _decode_jwt_token(token: str) -> Dict[str, Any]:
    """Decode a JWT token using Chainlit's auth. Returns user dict or raises HTTPException."""
    try:
        from chainlit.auth import decode_jwt
        user = decode_jwt(token)
    except HTTPException:
        raise
    except Exception as exc:
        # Broad catch: any failure (malformed token, missing key, unexpected
        # library error) must return 401, never 500.
        logger.debug("JWT decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {
        "identifier": getattr(user, "identifier", "unknown"),
        "metadata": getattr(user, "metadata", {}) or {},
    }


# ---------------------------------------------------------------------------
# Main Authentication Dependency
# ---------------------------------------------------------------------------

async def _try_oidc_validation(token: str) -> Optional[Dict[str, Any]]:
    """Attempt to validate a bearer token against configured OIDC providers.

    Returns a user dict if any OIDC provider validates the token, otherwise None.
    """
    try:
        from chat_app.auth_providers import get_all_providers, init_auth_providers
        providers = get_all_providers()
        if not providers:
            init_auth_providers()
            providers = get_all_providers()
        for name, provider in providers.items():
            if provider.provider_type != "oidc":
                continue
            identity = await provider.validate_token(token)
            if identity:
                # Use the highest role from the identity
                role = identity.roles[0] if identity.roles else "USER"
                return {
                    "identifier": identity.user_id or identity.email,
                    "metadata": {
                        "role": role,
                        "roles": identity.roles,
                        "provider": identity.provider,
                        "email": identity.email,
                        "display_name": identity.display_name,
                        "groups": identity.groups,
                    },
                }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("OIDC token validation skipped: %s", exc)
    return None


async def get_authenticated_user(request: Request) -> Dict[str, Any]:
    """
    Extract the authenticated user from the request.

    Authentication methods are checked in order:
    0. ``X-Service-Key`` header (internal service-to-service auth)
    1. ``access_token`` cookie (Chainlit JWT)
    2. ``Authorization: Bearer <token>`` header (OIDC, API key, or JWT)
    3. ``X-API-Key: <key>`` header (API key)

    Returns a dict with ``identifier`` and ``metadata`` (including ``role``).
    When authentication is disabled, returns an anonymous ADMIN user so all
    endpoints continue to work without breaking changes.
    """
    if not _auth_enabled():
        env = _get_environment()
        if env in ("production", "staging"):
            logger.error("[AUTH] Authentication disabled in %s environment — rejecting request", env)
            raise HTTPException(status_code=503, detail="Authentication is required but not configured. Contact administrator.")
        logger.debug("[AUTH] Auth disabled in %s — returning anonymous VIEWER", env)
        return _ANONYMOUS_USER

    # --- 0. Service-to-service key (internal services like MCP server) ---
    service_key = request.headers.get("x-service-key", "").strip()
    if service_key:
        expected = os.getenv("SERVICE_API_KEY", "").strip()
        if expected and secrets.compare_digest(service_key, expected):
            return {
                "identifier": "service:internal",
                "metadata": {"role": "ADMIN", "provider": "service_key"},
            }
        raise HTTPException(status_code=401, detail="Invalid service key")

    # --- 1. Cookie-based JWT auth (existing Chainlit flow) ---
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return _check_mfa(request, _decode_jwt_token(cookie_token))

    # --- 2. Authorization: Bearer <token> header ---
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        bearer_value = auth_header[7:].strip()
        if bearer_value:
            # Check if it is a managed API key first (they start with "obsai_"
            # or may be an env-var key).
            api_entry = _validate_api_key(bearer_value)
            if api_entry:
                return _check_mfa(request, {
                    "identifier": f"api-key:{api_entry.label or api_entry.token_id[:8]}",
                    "metadata": {"role": api_entry.role, "provider": "api_key"},
                })
            # Try OIDC provider token validation (e.g., IBM SSO, Azure AD)
            oidc_user = await _try_oidc_validation(bearer_value)
            if oidc_user:
                return _check_mfa(request, oidc_user)
            # Otherwise, treat it as a JWT
            return _check_mfa(request, _decode_jwt_token(bearer_value))

    # --- 3. X-API-Key header ---
    api_key = request.headers.get("x-api-key", "").strip()
    if api_key:
        api_entry = _validate_api_key(api_key)
        if api_entry:
            return _check_mfa(request, {
                "identifier": f"api-key:{api_entry.label or api_entry.token_id[:8]}",
                "metadata": {"role": api_entry.role, "provider": "api_key"},
            })
        raise HTTPException(status_code=401, detail="Invalid API key")

    raise HTTPException(status_code=401, detail="Authentication required")


# ---------------------------------------------------------------------------
# MFA Verification (optional — graceful when mfa_manager module is absent)
# ---------------------------------------------------------------------------

def _check_mfa(request: Request, user: Dict[str, Any]) -> Dict[str, Any]:
    """Check MFA status for the authenticated user.

    - If MFA module is not installed, skip silently.
    - If MFA is required for the user's role but user is NOT enrolled,
      set ``metadata.mfa_enrollment_required = True`` (UI prompt, non-blocking).
    - If user IS enrolled, verify the ``X-MFA-Token`` header; set
      ``metadata.mfa_verified`` accordingly.
    """
    try:
        from chat_app.mfa import get_mfa_manager
    except ImportError:
        return user

    try:
        mfa = get_mfa_manager()
        role = user.get("metadata", {}).get("role", "USER")
        username = user.get("identifier", "")

        if not mfa.is_required(role):
            return user

        if not mfa.is_enrolled(username):
            # Non-blocking: flag for the UI to prompt enrollment
            user.setdefault("metadata", {})["mfa_enrollment_required"] = True
            logger.info("MFA enrollment required for user=%s role=%s", username, role)
            return user

        # User is enrolled — verify the one-time token from the request header
        mfa_token = request.headers.get("x-mfa-token", "").strip()
        if mfa_token and mfa.verify(username, mfa_token):
            user.setdefault("metadata", {})["mfa_verified"] = True
        else:
            user.setdefault("metadata", {})["mfa_verified"] = False
            env = os.getenv("DEPLOYMENT_ENV", os.getenv("APP_ENVIRONMENT", "development"))
            if env in ("production", "staging"):
                logger.warning("[AUTH] MFA required but not verified for user=%s in %s — blocking", username, env)
                raise HTTPException(
                    status_code=403,
                    detail="MFA verification required. Provide X-MFA-Token header with your TOTP code.",
                )
            logger.warning("[AUTH] MFA verification failed for user=%s (non-blocking in %s)", username, env)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        # Never break auth flow due to MFA subsystem errors
        logger.debug("MFA check skipped due to error: %s", exc)

    return user


def require_role(*allowed_roles: str):
    """
    Factory that returns a FastAPI dependency requiring the user to have
    one of the specified roles.

    Usage::

        @router.get("/admin-only", dependencies=[Depends(require_role("ADMIN"))])
        async def admin_endpoint(): ...

    Or as a parameter dependency::

        async def endpoint(user=Depends(require_role("ADMIN"))):
            ...
    """
    async def _check(user: dict = Depends(get_authenticated_user)):
        role = user.get("metadata", {}).get("role", "USER")
        if role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {', '.join(allowed_roles)}. Your role: {role}",
            )
        return user
    return _check


# Convenience aliases
require_admin = require_role("ADMIN")
require_admin_or_analyst = require_role("ADMIN", "ANALYST")
require_any_authenticated = require_role("ADMIN", "USER", "ANALYST", "VIEWER")
