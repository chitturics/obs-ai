"""
Tests for API token/bearer authentication and token management endpoints.

Covers:
- API key validation from API_KEYS env var
- Bearer token auth (JWT fallback and API key)
- X-API-Key header auth
- Token management CRUD endpoints (POST/GET/DELETE /api/admin/tokens)
- Authentication priority: cookie > bearer > api-key
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_token_store():
    """Reset the in-memory token store between tests."""
    from chat_app import auth_dependencies as ad
    ad._token_store.clear()
    ad._token_index.clear()
    ad._env_keys_loaded = False
    yield
    ad._token_store.clear()
    ad._token_index.clear()
    ad._env_keys_loaded = False


@pytest.fixture
def admin_app():
    """Create a FastAPI app with admin routes and auth overridden to ADMIN."""
    from chat_app.admin_api import router as admin_router, public_router as admin_public_router
    from chat_app.admin_api import users_router
    from chat_app.auth_dependencies import get_authenticated_user, require_admin
    from chat_app.admin_shared import _rate_limit, _csrf_check, _track_audit_user

    async def _fake_user():
        return {
            "identifier": "test_admin",
            "metadata": {"role": "ADMIN", "provider": "test"},
        }

    app = FastAPI(title="Auth Test")
    app.include_router(admin_router)
    app.include_router(admin_public_router)
    app.include_router(users_router)
    app.dependency_overrides[get_authenticated_user] = _fake_user
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[_rate_limit] = lambda: None
    app.dependency_overrides[_csrf_check] = lambda: None
    app.dependency_overrides[_track_audit_user] = lambda: None
    return TestClient(app)


@pytest.fixture
def auth_app():
    """Create a FastAPI app with REAL auth enabled (no overrides) for testing auth flows."""
    from chat_app.admin_api import router as admin_router, public_router as admin_public_router
    from chat_app.admin_api import users_router, pages_public_router
    from chat_app.admin_api import _rate_limit, _csrf_check, _track_audit_user
    from chat_app.auth_dependencies import require_admin

    app = FastAPI(title="Auth Flow Test")
    app.include_router(admin_router)
    app.include_router(admin_public_router)
    app.include_router(users_router)
    app.include_router(pages_public_router)
    # Disable rate limit & CSRF for testing, but keep real auth
    app.dependency_overrides[_rate_limit] = lambda: None
    app.dependency_overrides[_csrf_check] = lambda: None
    app.dependency_overrides[_track_audit_user] = lambda: None
    return TestClient(app)


# ---------------------------------------------------------------------------
# Unit Tests: Token Store Functions
# ---------------------------------------------------------------------------

class TestTokenStore:
    """Test the in-memory token store functions."""

    def test_create_api_token(self):
        from chat_app.auth_dependencies import create_api_token
        entry = create_api_token(label="test-key", role="ADMIN", created_by="unit_test")
        assert entry.key.startswith("obsai_")
        assert entry.label == "test-key"
        assert entry.role == "ADMIN"
        assert entry.created_by == "unit_test"
        assert entry.token_id

    def test_create_and_list_tokens(self):
        from chat_app.auth_dependencies import create_api_token, list_api_tokens
        create_api_token(label="key1")
        create_api_token(label="key2")
        tokens = list_api_tokens()
        assert len(tokens) == 2
        labels = {t["label"] for t in tokens}
        assert labels == {"key1", "key2"}

    def test_listed_tokens_are_masked(self):
        from chat_app.auth_dependencies import create_api_token, list_api_tokens
        entry = create_api_token(label="masked-test")
        tokens = list_api_tokens()
        assert len(tokens) == 1
        # The key should be masked — not equal to the real key
        assert tokens[0]["key"] != entry.key
        assert "..." in tokens[0]["key"]

    def test_revoke_token(self):
        from chat_app.auth_dependencies import create_api_token, revoke_api_token, list_api_tokens
        entry = create_api_token(label="revokable")
        assert len(list_api_tokens()) == 1
        result = revoke_api_token(entry.token_id)
        assert result is True
        assert len(list_api_tokens()) == 0

    def test_revoke_nonexistent_token(self):
        from chat_app.auth_dependencies import revoke_api_token
        result = revoke_api_token("does-not-exist")
        assert result is False

    def test_validate_api_key(self):
        from chat_app.auth_dependencies import create_api_token, _validate_api_key
        entry = create_api_token(label="validate-test")
        result = _validate_api_key(entry.key)
        assert result is not None
        assert result.token_id == entry.token_id

    def test_validate_invalid_key(self):
        from chat_app.auth_dependencies import _validate_api_key
        result = _validate_api_key("not_a_real_key")
        assert result is None

    def test_validate_updates_last_used(self):
        from chat_app.auth_dependencies import create_api_token, _validate_api_key
        entry = create_api_token(label="touch-test")
        assert entry.last_used is None
        _validate_api_key(entry.key)
        assert entry.last_used is not None

    def test_env_keys_loaded(self):
        """Keys from API_KEYS env var should be loadable."""
        from chat_app.auth_dependencies import _validate_api_key, _ensure_env_keys_loaded
        import chat_app.auth_dependencies as ad
        ad._env_keys_loaded = False
        with patch.dict(os.environ, {"API_KEYS": "env_key_alpha,env_key_beta"}):
            _ensure_env_keys_loaded()
        result = _validate_api_key("env_key_alpha")
        assert result is not None
        assert result.created_by == "env:API_KEYS"

    def test_env_keys_empty(self):
        """Empty API_KEYS env var should not crash."""
        from chat_app.auth_dependencies import _ensure_env_keys_loaded, list_api_tokens
        import chat_app.auth_dependencies as ad
        ad._env_keys_loaded = False
        with patch.dict(os.environ, {"API_KEYS": ""}):
            _ensure_env_keys_loaded()
        assert len(list_api_tokens()) == 0

    def test_env_keys_loaded_only_once(self):
        """Env keys should only be loaded once even if called multiple times."""
        from chat_app.auth_dependencies import _ensure_env_keys_loaded, list_api_tokens
        import chat_app.auth_dependencies as ad
        ad._env_keys_loaded = False
        with patch.dict(os.environ, {"API_KEYS": "onekey"}):
            _ensure_env_keys_loaded()
            _ensure_env_keys_loaded()  # second call should be a no-op
        assert len(list_api_tokens()) == 1

    def test_token_to_dict_unmasked(self):
        from chat_app.auth_dependencies import create_api_token
        entry = create_api_token(label="dict-test")
        d = entry.to_dict(mask=False)
        assert d["key"] == entry.key
        assert d["label"] == "dict-test"


# ---------------------------------------------------------------------------
# Unit Tests: get_authenticated_user with various auth methods
# ---------------------------------------------------------------------------

class TestAuthMethods:
    """Test the get_authenticated_user dependency with different auth methods."""

    def test_auth_disabled_returns_anonymous(self):
        """When auth is disabled, should return anonymous admin."""
        from chat_app.auth_dependencies import get_authenticated_user
        import asyncio

        mock_request = MagicMock()
        with patch("chat_app.auth_dependencies._auth_enabled", return_value=False):
            result = asyncio.get_event_loop().run_until_complete(
                get_authenticated_user(mock_request)
            )
        assert result["identifier"] == "anonymous"
        assert result["metadata"]["role"] == "VIEWER"

    def test_api_key_via_x_api_key_header(self):
        """X-API-Key header should authenticate with a valid key."""
        from chat_app.auth_dependencies import get_authenticated_user, create_api_token
        import asyncio

        entry = create_api_token(label="header-test", role="ANALYST")
        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None
        mock_request.headers.get = lambda h, default="": {
            "authorization": "",
            "x-api-key": entry.key,
        }.get(h.lower(), default)

        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
            result = asyncio.get_event_loop().run_until_complete(
                get_authenticated_user(mock_request)
            )
        assert "api-key:" in result["identifier"]
        assert result["metadata"]["role"] == "ANALYST"
        assert result["metadata"]["provider"] == "api_key"

    def test_api_key_via_bearer_header(self):
        """Bearer header with an API key should authenticate."""
        from chat_app.auth_dependencies import get_authenticated_user, create_api_token
        import asyncio

        entry = create_api_token(label="bearer-api-test", role="ADMIN")
        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None
        mock_request.headers.get = lambda h, default="": {
            "authorization": f"Bearer {entry.key}",
            "x-api-key": "",
        }.get(h.lower(), default)

        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
            result = asyncio.get_event_loop().run_until_complete(
                get_authenticated_user(mock_request)
            )
        assert "api-key:" in result["identifier"]
        assert result["metadata"]["role"] == "ADMIN"

    def test_invalid_api_key_via_x_api_key_raises_401(self):
        """Invalid X-API-Key should raise 401."""
        from chat_app.auth_dependencies import get_authenticated_user
        from fastapi import HTTPException
        import asyncio

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None
        mock_request.headers.get = lambda h, default="": {
            "authorization": "",
            "x-api-key": "invalid_key_value",
        }.get(h.lower(), default)

        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    get_authenticated_user(mock_request)
                )
            assert exc_info.value.status_code == 401
            assert "Invalid API key" in str(exc_info.value.detail)

    def test_no_credentials_raises_401(self):
        """No cookie, no bearer, no api-key should raise 401."""
        from chat_app.auth_dependencies import get_authenticated_user
        from fastapi import HTTPException
        import asyncio

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None
        mock_request.headers.get = lambda h, default="": default

        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    get_authenticated_user(mock_request)
                )
            assert exc_info.value.status_code == 401

    def test_cookie_takes_priority_over_api_key(self):
        """Cookie auth should be checked before API key."""
        from chat_app.auth_dependencies import get_authenticated_user, create_api_token
        import asyncio

        entry = create_api_token(label="priority-test")
        mock_user = MagicMock()
        mock_user.identifier = "cookie_user"
        mock_user.metadata = {"role": "USER", "provider": "cookie"}

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = "valid_jwt_token"
        mock_request.headers.get = lambda h, default="": {
            "authorization": "",
            "x-api-key": entry.key,
        }.get(h.lower(), default)

        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True), \
             patch("chat_app.auth_dependencies._decode_jwt_token", return_value={
                 "identifier": "cookie_user",
                 "metadata": {"role": "USER", "provider": "cookie"},
             }) as mock_decode:
            result = asyncio.get_event_loop().run_until_complete(
                get_authenticated_user(mock_request)
            )
        # Cookie path was used
        assert result["identifier"] == "cookie_user"
        mock_decode.assert_called_once_with("valid_jwt_token")

    def test_env_api_key_authenticates(self):
        """API key from API_KEYS env var should work for auth."""
        from chat_app.auth_dependencies import get_authenticated_user
        import chat_app.auth_dependencies as ad
        import asyncio

        ad._env_keys_loaded = False
        with patch.dict(os.environ, {"API_KEYS": "my_env_secret_key"}):
            mock_request = MagicMock()
            mock_request.cookies.get.return_value = None
            mock_request.headers.get = lambda h, default="": {
                "authorization": "",
                "x-api-key": "my_env_secret_key",
            }.get(h.lower(), default)

            with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
                result = asyncio.get_event_loop().run_until_complete(
                    get_authenticated_user(mock_request)
                )
            assert result["metadata"]["provider"] == "api_key"
            assert result["metadata"]["role"] == "ADMIN"


# ---------------------------------------------------------------------------
# Integration Tests: Token Management Endpoints
# ---------------------------------------------------------------------------

class TestTokenEndpoints:
    """Test the /api/admin/tokens CRUD endpoints."""

    def test_create_token(self, admin_app):
        resp = admin_app.post("/api/admin/tokens", json={"label": "my-ci-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"].startswith("obsai_")
        assert data["label"] == "my-ci-key"
        assert data["role"] == "ADMIN"
        assert data["token_id"]
        assert "Store this key securely" in data["message"]

    def test_create_token_with_role(self, admin_app):
        resp = admin_app.post("/api/admin/tokens", json={"label": "viewer-key", "role": "VIEWER"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "VIEWER"

    def test_create_token_invalid_role(self, admin_app):
        resp = admin_app.post("/api/admin/tokens", json={"label": "bad", "role": "SUPERUSER"})
        assert resp.status_code == 400
        assert "Invalid role" in resp.json()["detail"]

    def test_create_token_default_label(self, admin_app):
        resp = admin_app.post("/api/admin/tokens", json={})
        assert resp.status_code == 200
        assert resp.json()["label"] == ""
        assert resp.json()["role"] == "ADMIN"

    def test_list_tokens_empty(self, admin_app):
        resp = admin_app.get("/api/admin/tokens")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tokens"] == []
        assert data["total"] == 0

    def test_list_tokens_after_create(self, admin_app):
        admin_app.post("/api/admin/tokens", json={"label": "first"})
        admin_app.post("/api/admin/tokens", json={"label": "second"})
        resp = admin_app.get("/api/admin/tokens")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        labels = {t["label"] for t in data["tokens"]}
        assert labels == {"first", "second"}

    def test_list_tokens_keys_are_masked(self, admin_app):
        admin_app.post("/api/admin/tokens", json={"label": "masked"})
        resp = admin_app.get("/api/admin/tokens")
        for token in resp.json()["tokens"]:
            assert "..." in token["key"]

    def test_delete_token(self, admin_app):
        create_resp = admin_app.post("/api/admin/tokens", json={"label": "delete-me"})
        token_id = create_resp.json()["token_id"]

        del_resp = admin_app.delete(f"/api/admin/tokens/{token_id}")
        assert del_resp.status_code == 200
        assert "revoked" in del_resp.json()["message"]

        # Verify it's gone
        list_resp = admin_app.get("/api/admin/tokens")
        assert list_resp.json()["total"] == 0

    def test_delete_nonexistent_token(self, admin_app):
        resp = admin_app.delete("/api/admin/tokens/nonexistent-id")
        assert resp.status_code == 404

    def test_create_then_delete_then_list(self, admin_app):
        """Full lifecycle: create two tokens, delete one, verify one remains."""
        r1 = admin_app.post("/api/admin/tokens", json={"label": "keep"})
        r2 = admin_app.post("/api/admin/tokens", json={"label": "remove"})
        admin_app.delete(f"/api/admin/tokens/{r2.json()['token_id']}")

        tokens = admin_app.get("/api/admin/tokens").json()["tokens"]
        assert len(tokens) == 1
        assert tokens[0]["label"] == "keep"


# ---------------------------------------------------------------------------
# Integration Tests: Auth Flow with Real Endpoints
# ---------------------------------------------------------------------------

class TestAuthFlowIntegration:
    """Test real auth flow with API keys against live endpoints."""

    def test_api_key_grants_access_to_protected_endpoint(self, auth_app):
        """A valid API key in X-API-Key header should grant access."""
        from chat_app.auth_dependencies import create_api_token

        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
            entry = create_api_token(label="integration-test", role="ADMIN")
            resp = auth_app.get(
                "/api/admin/tokens",
                headers={"X-API-Key": entry.key},
            )
        assert resp.status_code == 200

    def test_api_key_bearer_grants_access(self, auth_app):
        """A valid API key in Authorization: Bearer header should grant access."""
        from chat_app.auth_dependencies import create_api_token

        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
            entry = create_api_token(label="bearer-int-test", role="ADMIN")
            resp = auth_app.get(
                "/api/admin/tokens",
                headers={"Authorization": f"Bearer {entry.key}"},
            )
        assert resp.status_code == 200

    def test_invalid_key_rejected(self, auth_app):
        """Invalid API key should be rejected with 401."""
        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
            resp = auth_app.get(
                "/api/admin/tokens",
                headers={"X-API-Key": "invalid_garbage_key"},
            )
        assert resp.status_code == 401

    def test_no_auth_rejected(self, auth_app):
        """No auth at all should be rejected when auth is enabled."""
        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
            resp = auth_app.get("/api/admin/tokens")
        assert resp.status_code == 401

    def test_env_key_grants_access(self, auth_app):
        """API key from API_KEYS env var should grant access."""
        import chat_app.auth_dependencies as ad
        ad._env_keys_loaded = False
        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True), \
             patch.dict(os.environ, {"API_KEYS": "env_test_key_12345"}):
            resp = auth_app.get(
                "/api/admin/tokens",
                headers={"X-API-Key": "env_test_key_12345"},
            )
        assert resp.status_code == 200

    def test_whoami_with_api_key(self, auth_app):
        """The /whoami endpoint should reflect API key identity."""
        from chat_app.auth_dependencies import create_api_token

        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
            entry = create_api_token(label="whoami-test", role="ANALYST")
            resp = auth_app.get(
                "/api/admin/whoami",
                headers={"X-API-Key": entry.key},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "ANALYST"
        assert data["authenticated"] is True
        assert "api-key:" in data["username"]

    def test_role_enforcement_with_api_key(self, auth_app):
        """API key with VIEWER role should be denied access to ADMIN-only endpoints."""
        from chat_app.auth_dependencies import create_api_token

        with patch("chat_app.auth_dependencies._auth_enabled", return_value=True):
            entry = create_api_token(label="viewer-key", role="VIEWER")
            resp = auth_app.get(
                "/api/admin/tokens",
                headers={"X-API-Key": entry.key},
            )
        assert resp.status_code == 403
        assert "Access denied" in resp.json()["detail"]
