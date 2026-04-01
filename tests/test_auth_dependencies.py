"""Comprehensive unit tests for chat_app.auth_dependencies."""
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from chat_app.settings import get_settings

get_settings.cache_clear()

from chat_app.auth_dependencies import (
    _ANONYMOUS_ADMIN,
    _TokenEntry,
    _auth_enabled,
    _decode_jwt_token,
    _token_index,
    _token_store,
    _validate_api_key,
    create_api_token,
    get_authenticated_user,
    list_api_tokens,
    require_admin,
    require_admin_or_analyst,
    require_any_authenticated,
    require_role,
    revoke_api_token,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_token_state():
    """Reset the in-memory token store between tests."""
    import chat_app.auth_dependencies as mod
    mod._token_store.clear()
    mod._token_index.clear()
    mod._env_keys_loaded = False
    yield
    mod._token_store.clear()
    mod._token_index.clear()
    mod._env_keys_loaded = False


def _make_user(role: str = "ADMIN", identifier: str = "test_user") -> dict:
    return {"identifier": identifier, "metadata": {"role": role, "provider": "test"}}


def _make_app_with_dependency(dep):
    """Create a FastAPI app with a single endpoint protected by *dep*."""
    app = FastAPI()

    @app.get("/test")
    async def _endpoint(user=dep):
        return {"user": user}

    return app


# ---------------------------------------------------------------------------
# _TokenEntry
# ---------------------------------------------------------------------------

class TestTokenEntry:
    def test_creation(self):
        entry = _TokenEntry(key="abc123", label="test", role="ADMIN", created_by="tester")
        assert entry.key == "abc123"
        assert entry.label == "test"
        assert entry.role == "ADMIN"
        assert entry.created_by == "tester"
        assert entry.last_used is None
        assert entry.token_id  # UUID assigned

    def test_touch_updates_last_used(self):
        entry = _TokenEntry(key="k", label="l")
        assert entry.last_used is None
        entry.touch()
        assert entry.last_used is not None

    def test_to_dict_masks_key(self):
        entry = _TokenEntry(key="obsai_a_very_long_secret_key_1234", label="masked")
        d = entry.to_dict(mask=True)
        assert "..." in d["key"]
        assert d["label"] == "masked"

    def test_to_dict_no_mask(self):
        entry = _TokenEntry(key="obsai_cleartext_key_here_1234567", label="clear")
        d = entry.to_dict(mask=False)
        assert d["key"] == "obsai_cleartext_key_here_1234567"

    def test_to_dict_short_key_masks_fully(self):
        entry = _TokenEntry(key="short")
        d = entry.to_dict(mask=True)
        assert d["key"] == "***"


# ---------------------------------------------------------------------------
# Token management functions
# ---------------------------------------------------------------------------

class TestTokenManagement:
    def test_create_api_token(self):
        entry = create_api_token(label="ci", role="ANALYST", created_by="admin")
        assert entry.key.startswith("obsai_")
        assert entry.role == "ANALYST"
        assert entry.token_id in _token_store

    def test_validate_api_key_valid(self):
        entry = create_api_token(label="valid")
        result = _validate_api_key(entry.key)
        assert result is not None
        assert result.last_used is not None

    def test_validate_api_key_invalid(self):
        result = _validate_api_key("nonexistent_key")
        assert result is None

    def test_list_api_tokens(self):
        create_api_token(label="one")
        create_api_token(label="two")
        tokens = list_api_tokens()
        assert len(tokens) == 2
        labels = {t["label"] for t in tokens}
        assert labels == {"one", "two"}

    def test_revoke_api_token_success(self):
        entry = create_api_token(label="revoke_me")
        assert revoke_api_token(entry.token_id) is True
        assert entry.token_id not in _token_store
        assert entry.key not in _token_index

    def test_revoke_api_token_not_found(self):
        assert revoke_api_token("nonexistent-id") is False

    @patch.dict(os.environ, {"API_KEYS": "key_one,key_two"})
    def test_env_keys_loaded(self):
        import chat_app.auth_dependencies as mod
        mod._env_keys_loaded = False
        mod._ensure_env_keys_loaded()
        assert _validate_api_key("key_one") is not None
        assert _validate_api_key("key_two") is not None

    @patch.dict(os.environ, {"API_KEYS": ""})
    def test_env_keys_empty(self):
        import chat_app.auth_dependencies as mod
        mod._env_keys_loaded = False
        mod._ensure_env_keys_loaded()
        # No crash, no keys added
        assert len(mod._token_store) == 0


# ---------------------------------------------------------------------------
# _auth_enabled
# ---------------------------------------------------------------------------

class TestAuthEnabled:
    def test_auth_enabled_from_settings(self):
        with patch("chat_app.settings.get_settings") as mock_gs:
            mock_gs.return_value.auth.enabled = True
            assert _auth_enabled() is True

    def test_auth_disabled_from_settings(self):
        with patch("chat_app.settings.get_settings") as mock_gs:
            mock_gs.return_value.auth.enabled = False
            assert _auth_enabled() is False

    @patch.dict(os.environ, {"ENABLE_AUTHENTICATION": "true"})
    def test_auth_enabled_env_fallback(self):
        with patch("chat_app.settings.get_settings", side_effect=RuntimeError("no settings")):
            assert _auth_enabled() is True

    @patch.dict(os.environ, {"ENABLE_AUTHENTICATION": "false"})
    def test_auth_disabled_env_fallback(self):
        with patch("chat_app.settings.get_settings", side_effect=RuntimeError("no settings")):
            assert _auth_enabled() is False


# ---------------------------------------------------------------------------
# get_authenticated_user
# ---------------------------------------------------------------------------

class TestGetAuthenticatedUser:
    @pytest.mark.asyncio
    @patch("chat_app.auth_dependencies._auth_enabled", return_value=False)
    @patch("chat_app.auth_dependencies._get_environment", return_value="development")
    async def test_auth_disabled_returns_anonymous_viewer(self, _, __):
        """When auth disabled in dev, anonymous user gets VIEWER role (not ADMIN)."""
        request = MagicMock()
        user = await get_authenticated_user(request)
        assert user["identifier"] == "anonymous"
        assert user["metadata"]["role"] == "VIEWER"

    @pytest.mark.asyncio
    @patch("chat_app.auth_dependencies._decode_jwt_token")
    @patch("chat_app.auth_dependencies._auth_enabled", return_value=True)
    async def test_cookie_jwt_auth(self, _, mock_decode):
        mock_decode.return_value = _make_user("ADMIN", "cookie_user")
        request = MagicMock()
        request.headers.get = lambda h, d="": ""  # No service key or other headers
        request.cookies.get.return_value = "valid_jwt_token"
        user = await get_authenticated_user(request)
        assert user["identifier"] == "cookie_user"
        mock_decode.assert_called_once_with("valid_jwt_token")

    @pytest.mark.asyncio
    @patch("chat_app.auth_dependencies._auth_enabled", return_value=True)
    async def test_bearer_api_key_auth(self, _):
        entry = create_api_token(label="bearer_test", role="ANALYST")
        request = MagicMock()
        request.cookies.get.return_value = None
        request.headers.get = lambda h, d="": f"Bearer {entry.key}" if h == "authorization" else ""
        user = await get_authenticated_user(request)
        assert user["metadata"]["role"] == "ANALYST"
        assert user["metadata"]["provider"] == "api_key"

    @pytest.mark.asyncio
    @patch("chat_app.auth_dependencies._auth_enabled", return_value=True)
    async def test_x_api_key_header_auth(self, _):
        entry = create_api_token(label="xapi", role="USER")
        request = MagicMock()
        request.cookies.get.return_value = None
        request.headers.get = lambda h, d="": entry.key if h == "x-api-key" else ""
        user = await get_authenticated_user(request)
        assert user["metadata"]["role"] == "USER"

    @pytest.mark.asyncio
    @patch("chat_app.auth_dependencies._auth_enabled", return_value=True)
    async def test_invalid_x_api_key_raises_401(self, _):
        request = MagicMock()
        request.cookies.get.return_value = None
        request.headers.get = lambda h, d="": "bad_key" if h == "x-api-key" else ""
        with pytest.raises(HTTPException) as exc_info:
            await get_authenticated_user(request)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    @patch("chat_app.auth_dependencies._auth_enabled", return_value=True)
    async def test_no_credentials_raises_401(self, _):
        request = MagicMock()
        request.cookies.get.return_value = None
        request.headers.get.return_value = ""
        with pytest.raises(HTTPException) as exc_info:
            await get_authenticated_user(request)
        assert exc_info.value.status_code == 401
        assert "Authentication required" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("chat_app.auth_dependencies._auth_enabled", return_value=True)
    @patch("chat_app.auth_dependencies._decode_jwt_token", side_effect=HTTPException(status_code=401, detail="expired"))
    async def test_expired_jwt_raises_401(self, mock_decode, _):
        request = MagicMock()
        request.cookies.get.return_value = "expired_token"
        with pytest.raises(HTTPException) as exc_info:
            await get_authenticated_user(request)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    @patch("chat_app.auth_dependencies._auth_enabled", return_value=True)
    @patch("chat_app.auth_dependencies._decode_jwt_token")
    async def test_bearer_jwt_fallback_after_api_key_miss(self, mock_decode, _):
        """If bearer value is not an API key, it falls back to JWT decode."""
        mock_decode.return_value = _make_user("USER", "jwt_bearer_user")
        request = MagicMock()
        request.cookies.get.return_value = None
        request.headers.get = lambda h, d="": "Bearer some_jwt_token" if h == "authorization" else ""
        user = await get_authenticated_user(request)
        assert user["identifier"] == "jwt_bearer_user"
        mock_decode.assert_called_once_with("some_jwt_token")


# ---------------------------------------------------------------------------
# _decode_jwt_token
# ---------------------------------------------------------------------------

class TestDecodeJwtToken:
    @pytest.fixture(autouse=True)
    def _setup_chainlit_auth_mock(self):
        """Ensure chainlit.auth is a proper mock submodule."""
        import sys
        auth_mock = MagicMock()
        sys.modules["chainlit.auth"] = auth_mock
        yield auth_mock
        # Restore
        sys.modules["chainlit.auth"] = MagicMock()

    def test_valid_token(self, _setup_chainlit_auth_mock):
        mock_user = MagicMock()
        mock_user.identifier = "jwt_user"
        mock_user.metadata = {"role": "ADMIN"}
        _setup_chainlit_auth_mock.decode_jwt = MagicMock(return_value=mock_user)
        result = _decode_jwt_token("valid_token")
        assert result["identifier"] == "jwt_user"
        assert result["metadata"]["role"] == "ADMIN"

    def test_invalid_token_raises_401(self, _setup_chainlit_auth_mock):
        _setup_chainlit_auth_mock.decode_jwt = MagicMock(side_effect=ValueError("bad token"))
        with pytest.raises(HTTPException) as exc_info:
            _decode_jwt_token("bad_token")
        assert exc_info.value.status_code == 401

    def test_http_exception_passed_through(self, _setup_chainlit_auth_mock):
        _setup_chainlit_auth_mock.decode_jwt = MagicMock(
            side_effect=HTTPException(status_code=401, detail="expired")
        )
        with pytest.raises(HTTPException) as exc_info:
            _decode_jwt_token("expired_token")
        assert exc_info.value.status_code == 401

    def test_user_with_no_metadata(self, _setup_chainlit_auth_mock):
        mock_user = MagicMock()
        mock_user.identifier = "bare_user"
        mock_user.metadata = None
        _setup_chainlit_auth_mock.decode_jwt = MagicMock(return_value=mock_user)
        result = _decode_jwt_token("token")
        assert result["metadata"] == {}


# ---------------------------------------------------------------------------
# require_role
# ---------------------------------------------------------------------------

class TestRequireRole:
    @pytest.mark.asyncio
    async def test_admin_role_with_admin_user(self):
        dep = require_role("ADMIN")
        user = _make_user("ADMIN")
        result = await dep(user=user)
        assert result["metadata"]["role"] == "ADMIN"

    @pytest.mark.asyncio
    async def test_admin_role_with_analyst_user_raises_403(self):
        dep = require_role("ADMIN")
        user = _make_user("ANALYST")
        with pytest.raises(HTTPException) as exc_info:
            await dep(user=user)
        assert exc_info.value.status_code == 403
        assert "ANALYST" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_analyst_role_with_analyst_user(self):
        dep = require_role("ANALYST")
        user = _make_user("ANALYST")
        result = await dep(user=user)
        assert result["metadata"]["role"] == "ANALYST"

    @pytest.mark.asyncio
    async def test_viewer_role_with_viewer_user(self):
        dep = require_role("VIEWER")
        user = _make_user("VIEWER")
        result = await dep(user=user)
        assert result["metadata"]["role"] == "VIEWER"

    @pytest.mark.asyncio
    async def test_multiple_roles_or_logic(self):
        dep = require_role("ADMIN", "ANALYST")
        # ANALYST should pass
        user = _make_user("ANALYST")
        result = await dep(user=user)
        assert result["metadata"]["role"] == "ANALYST"
        # ADMIN should also pass
        user = _make_user("ADMIN")
        result = await dep(user=user)
        assert result["metadata"]["role"] == "ADMIN"

    @pytest.mark.asyncio
    async def test_multiple_roles_user_not_in_list(self):
        dep = require_role("ADMIN", "ANALYST")
        user = _make_user("VIEWER")
        with pytest.raises(HTTPException) as exc_info:
            await dep(user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_metadata(self):
        dep = require_role("ADMIN")
        user = {"identifier": "no_meta", "metadata": {}}
        # Default role is "USER" when missing, so ADMIN check fails
        with pytest.raises(HTTPException) as exc_info:
            await dep(user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_none_role_field(self):
        dep = require_role("ADMIN")
        user = {"identifier": "empty_role", "metadata": {"role": None}}
        with pytest.raises(HTTPException):
            await dep(user=user)

    @pytest.mark.asyncio
    async def test_user_role_default_when_no_role_key(self):
        """When metadata has no 'role' key, default is 'USER'."""
        dep = require_role("USER")
        user = {"identifier": "default", "metadata": {"provider": "test"}}
        result = await dep(user=user)
        assert result["identifier"] == "default"


# ---------------------------------------------------------------------------
# Convenience aliases
# ---------------------------------------------------------------------------

class TestConvenienceAliases:
    @pytest.mark.asyncio
    async def test_require_admin_passes_for_admin(self):
        result = await require_admin(user=_make_user("ADMIN"))
        assert result["metadata"]["role"] == "ADMIN"

    @pytest.mark.asyncio
    async def test_require_admin_fails_for_user(self):
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(user=_make_user("USER"))
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_admin_or_analyst_passes_analyst(self):
        result = await require_admin_or_analyst(user=_make_user("ANALYST"))
        assert result["metadata"]["role"] == "ANALYST"

    @pytest.mark.asyncio
    async def test_require_admin_or_analyst_fails_viewer(self):
        with pytest.raises(HTTPException):
            await require_admin_or_analyst(user=_make_user("VIEWER"))

    @pytest.mark.asyncio
    async def test_require_any_authenticated_passes_viewer(self):
        result = await require_any_authenticated(user=_make_user("VIEWER"))
        assert result["metadata"]["role"] == "VIEWER"

    @pytest.mark.asyncio
    async def test_require_any_authenticated_passes_admin(self):
        result = await require_any_authenticated(user=_make_user("ADMIN"))
        assert result["metadata"]["role"] == "ADMIN"


# ---------------------------------------------------------------------------
# Anonymous admin (auth disabled)
# ---------------------------------------------------------------------------

class TestAnonymousUser:
    """Anonymous users now get VIEWER role (security hardening: fail-closed)."""

    def test_anonymous_user_constant(self):
        from chat_app.auth_dependencies import _ANONYMOUS_USER
        assert _ANONYMOUS_USER["identifier"] == "anonymous"
        assert _ANONYMOUS_USER["metadata"]["role"] == "VIEWER"
        assert _ANONYMOUS_USER["metadata"]["provider"] == "anonymous"

    @pytest.mark.asyncio
    @patch("chat_app.auth_dependencies._auth_enabled", return_value=False)
    @patch("chat_app.auth_dependencies._get_environment", return_value="development")
    async def test_anonymous_gets_viewer_role(self, _, __):
        request = MagicMock()
        user = await get_authenticated_user(request)
        assert user["metadata"]["role"] == "VIEWER"


# ---------------------------------------------------------------------------
# Role hierarchy integration
# ---------------------------------------------------------------------------

class TestRoleHierarchy:
    """Validate that the role checks work for ADMIN > ANALYST > USER > VIEWER."""

    ROLES_ORDERED = ["ADMIN", "ANALYST", "USER", "VIEWER"]

    @pytest.mark.asyncio
    async def test_admin_passes_admin_only(self):
        dep = require_role("ADMIN")
        await dep(user=_make_user("ADMIN"))
        for role in ("ANALYST", "USER", "VIEWER"):
            with pytest.raises(HTTPException):
                await dep(user=_make_user(role))

    @pytest.mark.asyncio
    async def test_each_role_passes_own_check(self):
        for role in self.ROLES_ORDERED:
            dep = require_role(role)
            result = await dep(user=_make_user(role))
            assert result["metadata"]["role"] == role
