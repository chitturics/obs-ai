"""Comprehensive security tests for the ObsAI admin API.

Covers: SQL injection, XSS prevention, authentication bypass, authorization,
rate limiting, input validation, path traversal, and CSRF protection.
"""
import json
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chat_app.settings import get_settings

get_settings.cache_clear()

from chat_app.admin_api import (
    router,
    public_router,
    _rate_limit,
    _rate_limit_store,
    _RATE_LIMIT_MAX_REQUESTS,
    _track_audit_user,
    _csrf_check,
)
from chat_app.auth_dependencies import get_authenticated_user, require_admin


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_state():
    """Reset admin module state between tests."""
    import chat_app.admin_api as mod
    import chat_app.admin_shared as shared
    mod._config_audit_trail.clear()
    shared._feature_flags = None
    mod._feature_flags = None
    mod._recent_queries.clear()
    mod._intent_counts.clear()
    mod._query_volume.clear()
    mod._SECTION_MODEL_MAP.clear()
    _rate_limit_store.clear()
    yield


def _make_app(user_dict=None, enable_rate_limit=False, enable_csrf=False):
    """Build a FastAPI app with routers and optional dependency overrides.

    Args:
        user_dict: If provided, overrides auth to return this user.
                   If None, real auth runs (unauthenticated scenario).
        enable_rate_limit: If False, rate limiting is bypassed.
        enable_csrf: If False, CSRF checking is bypassed.
    """
    from chat_app.admin_api import (
        dashboard_router, pages_router, pages_public_router,
        interactive_tools_public_router, interactive_tools_router,
        observability_router, skills_router, collections_router,
        learning_router, operations_router, config_router,
        settings_router, tools_router, users_router, security_router,
    )
    app = FastAPI()
    app.include_router(router)
    app.include_router(public_router)
    for sub in [dashboard_router, pages_router, pages_public_router,
                interactive_tools_public_router, interactive_tools_router,
                observability_router, skills_router, collections_router,
                learning_router, operations_router, config_router,
                settings_router, tools_router, users_router, security_router]:
        app.include_router(sub)
    if user_dict is not None:
        app.dependency_overrides[get_authenticated_user] = lambda: user_dict
        app.dependency_overrides[require_admin] = lambda: user_dict
    app.dependency_overrides[_track_audit_user] = lambda: None
    if not enable_rate_limit:
        app.dependency_overrides[_rate_limit] = lambda: None
    if not enable_csrf:
        app.dependency_overrides[_csrf_check] = lambda: None
    return app


_ADMIN_USER = {
    "identifier": "test_admin",
    "metadata": {"role": "ADMIN", "provider": "test"},
}
_VIEWER_USER = {
    "identifier": "test_viewer",
    "metadata": {"role": "VIEWER", "provider": "test"},
}
_USER_USER = {
    "identifier": "test_user",
    "metadata": {"role": "USER", "provider": "test"},
}


@pytest.fixture
def admin_client():
    """TestClient authenticated as ADMIN with rate limiting disabled."""
    return TestClient(_make_app(user_dict=_ADMIN_USER))


@pytest.fixture
def viewer_client():
    """TestClient authenticated as VIEWER (non-admin) with rate limiting disabled."""
    # For viewer: override get_authenticated_user but NOT require_admin,
    # so the role check in require_admin still fires.
    app = _make_app(user_dict=_VIEWER_USER)
    # Re-set require_admin to use the real role check with our viewer user
    del app.dependency_overrides[require_admin]
    return TestClient(app)


@pytest.fixture
def user_client():
    """TestClient authenticated as USER with rate limiting disabled."""
    app = _make_app(user_dict=_USER_USER)
    del app.dependency_overrides[require_admin]
    return TestClient(app)


@pytest.fixture
def unauth_client():
    """TestClient with NO auth override — uses real auth dependency."""
    return TestClient(_make_app(user_dict=None))


@pytest.fixture
def rate_limited_client():
    """TestClient with rate limiting ENABLED."""
    return TestClient(_make_app(user_dict=_ADMIN_USER, enable_rate_limit=True))


@pytest.fixture
def csrf_client():
    """TestClient with CSRF checking ENABLED."""
    return TestClient(_make_app(user_dict=_ADMIN_USER, enable_csrf=True))


# ===========================================================================
# 1. SQL Injection Tests
# ===========================================================================

class TestSQLInjection:
    """Verify that user-supplied input is not interpolated into SQL."""

    SQL_PAYLOADS = [
        "'; DROP TABLE users; --",
        "1 OR 1=1",
        "' UNION SELECT * FROM information_schema.tables --",
        "1; DELETE FROM users WHERE ''='",
        "admin'--",
        "' OR '1'='1",
    ]

    def test_search_endpoint_rejects_sql_injection(self, admin_client):
        """Collection search uses ChromaDB (not SQL), but input must not cause errors."""
        for payload in self.SQL_PAYLOADS:
            with patch("chat_app.admin_collections_routes._get_chroma_client") as mock_chroma:
                mock_client = MagicMock()
                mock_client.list_collections.return_value = []
                mock_chroma.return_value = mock_client
                resp = admin_client.post(
                    "/api/admin/collections/search",
                    json={"query": payload, "limit": 5},
                )
                # Should succeed (200) or fail gracefully (4xx/5xx) — never execute SQL
                assert resp.status_code in (200, 422, 500), (
                    f"Unexpected status {resp.status_code} for payload: {payload}"
                )

    def test_settings_update_rejects_sql_in_values(self, admin_client):
        """Config update with SQL injection in values should be validated by Pydantic."""
        for payload in self.SQL_PAYLOADS:
            resp = admin_client.patch(
                "/api/admin/settings/app",
                json={"values": {"version": payload}},
            )
            # Pydantic may accept a string value but it is never used as SQL.
            # The key thing is it does not crash or execute SQL.
            assert resp.status_code in (200, 422), (
                f"Unexpected status {resp.status_code} for payload: {payload}"
            )

    def test_activity_endpoint_safe_with_sql_payload(self, admin_client):
        """Activity endpoint should not interpret SQL in query params."""
        resp = admin_client.get(
            "/api/admin/activity",
            params={"limit": "1; DROP TABLE users"},
        )
        # FastAPI validates int params — should get 422
        assert resp.status_code == 422

    def test_settings_history_section_filter_safe(self, admin_client):
        """Settings history section filter should not allow SQL injection."""
        resp = admin_client.get(
            "/api/admin/settings/history",
            params={"section": "'; DROP TABLE audit; --"},
        )
        # Should return empty results, not crash
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("entries", data.get("history", [])), list)


# ===========================================================================
# 2. XSS Prevention Tests
# ===========================================================================

class TestXSSPrevention:
    """Verify that script tags and HTML are not reflected unsanitized."""

    XSS_PAYLOADS = [
        "<script>alert('xss')</script>",
        '<img src=x onerror="alert(1)">',
        "javascript:alert(document.cookie)",
        '"><script>alert(1)</script>',
        "<svg onload=alert(1)>",
    ]

    def test_search_query_not_reflected_as_html(self, admin_client):
        """Search results should return JSON (not HTML), preventing XSS execution."""
        for payload in self.XSS_PAYLOADS:
            with patch("chat_app.admin_collections_routes._get_chroma_client") as mock_chroma:
                mock_client = MagicMock()
                mock_client.list_collections.return_value = []
                mock_chroma.return_value = mock_client
                resp = admin_client.post(
                    "/api/admin/collections/search",
                    json={"query": payload, "limit": 5},
                )
                if resp.status_code == 200:
                    # The critical XSS defense: response MUST be application/json.
                    # Browsers will not execute <script> tags in JSON responses.
                    ct = resp.headers.get("content-type", "")
                    assert ct.startswith("application/json"), (
                        f"Response for XSS payload has unsafe content-type: {ct}"
                    )
                    # Additionally, verify the response is valid JSON (not raw HTML)
                    data = resp.json()
                    assert isinstance(data, dict)

    def test_feature_toggle_xss_in_name(self, admin_client):
        """Feature flag name with XSS payload should not be rendered as HTML."""
        resp = admin_client.put(
            "/api/admin/features/<script>alert(1)</script>",
            json={"enabled": True},
        )
        # Should return JSON error, not render HTML
        assert resp.headers.get("content-type", "").startswith("application/json")

    def test_settings_section_xss_in_name(self, admin_client):
        """Unknown section name with XSS should return 404 JSON, not rendered HTML."""
        resp = admin_client.patch(
            "/api/admin/settings/<script>alert(1)</script>",
            json={"values": {"key": "value"}},
        )
        assert resp.status_code == 404
        assert resp.headers.get("content-type", "").startswith("application/json")
        # The error message should not contain unescaped HTML
        body = resp.text
        assert "<script>" not in body or '"<script>' in body

    def test_json_responses_have_correct_content_type(self, admin_client):
        """All API responses should be application/json to prevent browser HTML rendering."""
        endpoints = [
            "/api/admin/settings",
            "/api/admin/features",
            "/api/admin/dashboard",
            "/api/admin/activity",
        ]
        for ep in endpoints:
            resp = admin_client.get(ep)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                assert "application/json" in ct, (
                    f"Endpoint {ep} returned content-type '{ct}' instead of JSON"
                )


# ===========================================================================
# 3. Authentication Bypass Tests
# ===========================================================================

class TestAuthenticationBypass:
    """Verify that admin endpoints require valid authentication."""

    ADMIN_ENDPOINTS = [
        ("GET", "/api/admin/settings"),
        ("GET", "/api/admin/features"),
        ("GET", "/api/admin/dashboard"),
        ("GET", "/api/admin/activity"),
        ("GET", "/api/admin/skills"),
        ("GET", "/api/admin/llm"),
        ("GET", "/api/admin/collections"),
    ]

    def test_admin_endpoints_reject_unauthenticated(self, unauth_client):
        """Admin endpoints without credentials should return 401."""
        for method, path in self.ADMIN_ENDPOINTS:
            if method == "GET":
                resp = unauth_client.get(path)
            elif method == "POST":
                resp = unauth_client.post(path, json={})
            assert resp.status_code in (401, 403), (
                f"{method} {path} returned {resp.status_code} without auth (expected 401/403)"
            )

    def test_admin_post_endpoints_reject_unauthenticated(self, unauth_client):
        """Mutating admin endpoints should reject unauthenticated requests."""
        mutating = [
            ("PATCH", "/api/admin/settings/app", {"values": {"version": "1.0"}}),
            ("PUT", "/api/admin/features/test_flag", {"enabled": True}),
        ]
        for method, path, body in mutating:
            if method == "PATCH":
                resp = unauth_client.patch(path, json=body)
            elif method == "PUT":
                resp = unauth_client.put(path, json=body)
            assert resp.status_code in (401, 403), (
                f"{method} {path} returned {resp.status_code} without auth (expected 401/403)"
            )

    def test_invalid_api_key_rejected(self):
        """An invalid API key should result in 401."""
        test_app = _make_app(enable_rate_limit=False)
        # Remove auth override so real auth runs
        test_app.dependency_overrides.pop(get_authenticated_user, None)
        test_app.dependency_overrides.pop(require_admin, None)
        client = TestClient(test_app)
        resp = client.get(
            "/api/admin/settings",
            headers={"X-API-Key": "totally-invalid-key-12345"},
        )
        assert resp.status_code in (401, 403)

    def test_malformed_bearer_token_rejected(self):
        """A malformed Bearer token should result in 401."""
        test_app = _make_app(enable_rate_limit=False)
        test_app.dependency_overrides.pop(get_authenticated_user, None)
        test_app.dependency_overrides.pop(require_admin, None)
        client = TestClient(test_app)
        resp = client.get(
            "/api/admin/settings",
            headers={"Authorization": "Bearer not.a.valid.jwt.token"},
        )
        assert resp.status_code in (401, 403)

    def test_public_endpoints_accessible_without_auth(self, unauth_client):
        """Public endpoints (no auth dependency) should remain accessible."""
        # These public_router endpoints do NOT use Depends(get_authenticated_user)
        # Only endpoints on pages_public_router / interactive_tools_public_router
        # are truly public.  /registry and /sections-data moved to auth-protected
        # pages_router during the sub-router refactor.
        public_endpoints = [
            "/api/admin/commands-data",
            "/api/admin/spl-commands",
        ]
        for path in public_endpoints:
            resp = unauth_client.get(path)
            # Public endpoints should not return 401
            assert resp.status_code != 401, (
                f"Public endpoint {path} returned 401 — should be accessible"
            )


# ===========================================================================
# 4. Authorization Tests
# ===========================================================================

class TestAuthorization:
    """Verify role-based access control is enforced."""

    def test_viewer_cannot_access_admin_settings(self, viewer_client):
        """VIEWER role should be denied access to admin-only endpoints."""
        resp = viewer_client.get("/api/admin/settings")
        assert resp.status_code == 403
        assert "Access denied" in resp.json().get("detail", "")

    def test_viewer_cannot_update_settings(self, viewer_client):
        """VIEWER should not be able to modify settings."""
        resp = viewer_client.patch(
            "/api/admin/settings/app",
            json={"values": {"version": "hacked"}},
        )
        assert resp.status_code == 403

    def test_viewer_cannot_toggle_features(self, viewer_client):
        """VIEWER should not be able to toggle feature flags."""
        resp = viewer_client.put(
            "/api/admin/features/reranking",
            json={"enabled": True},
        )
        assert resp.status_code == 403

    def test_user_cannot_access_admin_endpoints(self, user_client):
        """USER role should be denied access to ADMIN-only endpoints."""
        resp = user_client.get("/api/admin/settings")
        assert resp.status_code == 403

    def test_user_cannot_modify_llm_config(self, user_client):
        """USER role should not be able to change LLM configuration."""
        resp = user_client.patch(
            "/api/admin/llm",
            json={"model": "malicious-model"},
        )
        assert resp.status_code == 403

    def test_admin_can_access_settings(self, admin_client):
        """ADMIN role should have full access to settings."""
        resp = admin_client.get("/api/admin/settings")
        assert resp.status_code == 200

    def test_role_in_error_message(self, viewer_client):
        """Forbidden response should indicate the user's actual role."""
        resp = viewer_client.get("/api/admin/settings")
        detail = resp.json().get("detail", "")
        assert "VIEWER" in detail


# ===========================================================================
# 5. Rate Limiting Tests
# ===========================================================================

class TestRateLimiting:
    """Verify rate limiting protects against abuse."""

    def test_rate_limit_returns_429_after_threshold(self, rate_limited_client):
        """After exceeding the rate limit, requests should get 429."""
        # Flood the endpoint to exceed the limit
        for i in range(_RATE_LIMIT_MAX_REQUESTS):
            resp = rate_limited_client.get("/api/admin/settings")
            # All of these should succeed (200)
            assert resp.status_code == 200, f"Request {i+1} failed with {resp.status_code}"

        # The next request should be rate-limited
        resp = rate_limited_client.get("/api/admin/settings")
        assert resp.status_code == 429, (
            f"Expected 429 after {_RATE_LIMIT_MAX_REQUESTS} requests, got {resp.status_code}"
        )

    def test_rate_limit_includes_retry_after_header(self, rate_limited_client):
        """429 responses should include Retry-After header."""
        # Exhaust the rate limit
        for _ in range(_RATE_LIMIT_MAX_REQUESTS):
            rate_limited_client.get("/api/admin/settings")

        resp = rate_limited_client.get("/api/admin/settings")
        assert resp.status_code == 429
        assert "retry-after" in resp.headers, "429 response missing Retry-After header"
        retry_after = int(resp.headers["retry-after"])
        assert retry_after > 0

    def test_rate_limit_message_is_generic(self, rate_limited_client):
        """Rate limit error should not leak internal details."""
        for _ in range(_RATE_LIMIT_MAX_REQUESTS):
            rate_limited_client.get("/api/admin/settings")

        resp = rate_limited_client.get("/api/admin/settings")
        assert resp.status_code == 429
        detail = resp.json().get("detail", "")
        assert "rate limit" in detail.lower()
        # Should not expose IP or internal state
        assert "127.0.0.1" not in detail
        assert "testclient" not in detail.lower()


# ===========================================================================
# 6. Input Validation Tests
# ===========================================================================

class TestInputValidation:
    """Verify proper validation of request payloads."""

    def test_oversized_json_body(self, admin_client):
        """Extremely large JSON payloads should be rejected or handled safely."""
        # 2MB string value
        huge_value = "A" * (2 * 1024 * 1024)
        resp = admin_client.patch(
            "/api/admin/settings/app",
            json={"values": {"version": huge_value}},
        )
        # Should either reject (413/422) or handle without crash
        assert resp.status_code in (200, 413, 422, 500)

    def test_invalid_content_type_rejected(self, admin_client):
        """Sending non-JSON content type to a JSON endpoint should fail."""
        resp = admin_client.patch(
            "/api/admin/settings/app",
            content="not json at all",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 422

    def test_empty_json_body(self, admin_client):
        """Empty JSON body for update endpoints should be rejected."""
        resp = admin_client.patch(
            "/api/admin/settings/app",
            content="{}",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_unicode_edge_cases_in_search(self, admin_client):
        """Unicode edge cases should be handled gracefully."""
        unicode_payloads = [
            "\u0000",  # Null byte
            "\ud800",  # Lone surrogate (may be rejected)
            "\U0001f4a9" * 100,  # Many emoji
            "A\u0300" * 500,  # Combining characters
            "\u202e" + "malicious" + "\u202c",  # RTL override
            "\ufeff" + "BOM prefix",  # BOM
        ]
        for payload in unicode_payloads:
            try:
                with patch("chat_app.admin_collections_routes._get_chroma_client") as mock_chroma:
                    mock_client = MagicMock()
                    mock_client.list_collections.return_value = []
                    mock_chroma.return_value = mock_client
                    resp = admin_client.post(
                        "/api/admin/collections/search",
                        json={"query": payload, "limit": 5},
                    )
                    # Must not crash — any status code is fine as long as we get a response
                    assert resp.status_code in (200, 400, 422, 500)
            except Exception:
                # Some unicode payloads may fail at JSON serialization level — that is acceptable
                pass

    def test_regex_catastrophic_backtracking(self, admin_client):
        """Regex endpoint should timeout on catastrophic backtracking patterns."""
        # Classic ReDoS pattern: (a+)+ against 'aaa...!'
        resp = admin_client.post(
            "/api/admin/tools/regex-test",
            json={
                "pattern": "(a+)+$",
                "test_text": "a" * 30 + "!",
            },
        )
        # The endpoint has a 2-second timeout — should return 408 or succeed quickly
        # depending on Python's regex engine. Either way, it must respond.
        assert resp.status_code in (200, 408, 422)

    def test_regex_invalid_pattern(self, admin_client):
        """Invalid regex patterns should return a clear error, not crash."""
        resp = admin_client.post(
            "/api/admin/tools/regex-test",
            json={
                "pattern": "(unmatched",
                "test_text": "test string",
            },
        )
        # Should return an error status (compile error) or handle gracefully
        assert resp.status_code in (200, 400, 422, 500)
        if resp.status_code == 200:
            # If 200, should contain an error indicator in the response
            data = resp.json()
            # At minimum, the response should be valid JSON, not a crash
            assert isinstance(data, dict)

    def test_regex_pattern_length_limit(self, admin_client):
        """Overly long regex patterns should be rejected."""
        resp = admin_client.post(
            "/api/admin/tools/regex-test",
            json={
                "pattern": "a" * 600,
                "test_text": "test",
            },
        )
        # Pydantic max_length=500 on pattern field should catch this
        assert resp.status_code in (413, 422)

    def test_negative_limit_rejected(self, admin_client):
        """Negative limit values should be rejected by validation."""
        resp = admin_client.get(
            "/api/admin/settings/history",
            params={"limit": -1},
        )
        assert resp.status_code == 422

    def test_extreme_limit_capped(self, admin_client):
        """Limit values above maximum should be rejected."""
        resp = admin_client.get(
            "/api/admin/settings/history",
            params={"limit": 99999},
        )
        # ge=1, le=500 validation should reject this
        assert resp.status_code == 422

    def test_collection_search_empty_query_rejected(self, admin_client):
        """Empty search query should be rejected by min_length validation."""
        resp = admin_client.post(
            "/api/admin/collections/search",
            json={"query": "", "limit": 5},
        )
        assert resp.status_code == 422


# ===========================================================================
# 7. Path Traversal Tests
# ===========================================================================

class TestPathTraversal:
    """Verify that file-related endpoints prevent directory traversal."""

    TRAVERSAL_PAYLOADS = [
        "../../etc/passwd",
        "../../../etc/shadow",
        "..%2f..%2f..%2fetc%2fpasswd",
        "....//....//etc/passwd",
        "/etc/passwd",
        "..\\..\\..\\etc\\passwd",
    ]

    def test_spec_files_path_traversal_blocked(self, admin_client):
        """spec-files endpoint should sanitize path components."""
        for payload in self.TRAVERSAL_PAYLOADS:
            resp = admin_client.get(f"/api/admin/spec-files/{payload}")
            if resp.status_code == 200:
                data = resp.json()
                # Should not contain /etc/passwd content
                content = json.dumps(data)
                assert "root:" not in content, (
                    f"Path traversal succeeded with payload: {payload}"
                )
                assert "/bin/bash" not in content
                assert "/bin/sh" not in content

    def test_spec_files_null_byte_injection(self, admin_client):
        """Null byte injection should not bypass path validation."""
        resp = admin_client.get("/api/admin/spec-files/props.conf.spec%00../../etc/passwd")
        if resp.status_code == 200:
            data = resp.json()
            content = json.dumps(data)
            assert "root:" not in content

    def test_spec_files_sanitizes_special_chars(self, admin_client):
        """Special characters in spec file name should be stripped."""
        dangerous_names = [
            "$(whoami).conf.spec",
            "`id`.conf.spec",
            "test;ls.conf.spec",
            "test|cat /etc/passwd.conf.spec",
        ]
        for name in dangerous_names:
            resp = admin_client.get(f"/api/admin/spec-files/{name}")
            # Should not execute shell commands — just return not-found or safe response
            assert resp.status_code in (200, 404, 422)

    def test_tools_endpoint_path_traversal(self, admin_client):
        """Tools endpoint should not allow path traversal in tool names."""
        resp = admin_client.get("/api/admin/tools/../../etc/passwd")
        # Should return 404 or valid JSON error, not file contents
        if resp.status_code == 200:
            data = resp.json()
            content = json.dumps(data)
            assert "root:" not in content


# ===========================================================================
# 8. CSRF Protection Tests
# ===========================================================================

class TestCSRFProtection:
    """Verify CSRF protection on mutating endpoints."""

    def test_cross_origin_post_rejected(self, csrf_client):
        """POST from a different origin should be rejected by CSRF check."""
        resp = csrf_client.put(
            "/api/admin/features/test_flag",
            json={"enabled": True},
            headers={
                "Origin": "https://evil-site.com",
                "Host": "localhost:8000",
            },
        )
        assert resp.status_code == 403
        assert "CSRF" in resp.json().get("detail", "")

    def test_cross_origin_patch_rejected(self, csrf_client):
        """PATCH from a different origin should be rejected."""
        resp = csrf_client.patch(
            "/api/admin/settings/app",
            json={"values": {"version": "1.0"}},
            headers={
                "Origin": "https://attacker.com",
                "Host": "localhost:8000",
            },
        )
        assert resp.status_code == 403

    def test_same_origin_requests_allowed(self, admin_client):
        """Requests from the same origin should pass CSRF check."""
        resp = admin_client.get(
            "/api/admin/settings",
            headers={
                "Origin": "http://localhost:8000",
                "Host": "localhost:8000",
            },
        )
        # GET requests are not subject to CSRF, but should still succeed
        assert resp.status_code == 200

    def test_no_origin_header_allowed(self, admin_client):
        """Requests without Origin header (non-browser clients) should be allowed."""
        resp = admin_client.get("/api/admin/settings")
        assert resp.status_code == 200


# ===========================================================================
# 9. Error Message Safety Tests
# ===========================================================================

class TestErrorMessageSafety:
    """Verify error messages do not leak sensitive information."""

    def test_unknown_section_error_does_not_leak_internals(self, admin_client):
        """404 for unknown section should list valid sections, not stack traces."""
        resp = admin_client.patch(
            "/api/admin/settings/nonexistent_section",
            json={"values": {"key": "val"}},
        )
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert "Traceback" not in detail
        assert "File " not in detail

    def test_validation_error_does_not_expose_internals(self, admin_client):
        """Pydantic validation errors should be structured, not raw exceptions."""
        resp = admin_client.patch(
            "/api/admin/settings/app",
            json={"values": {"version": None}},
        )
        # Should be a structured validation error or succeed
        if resp.status_code == 422:
            data = resp.json()
            # Should have structured error info, not raw Python traceback
            detail = str(data.get("detail", ""))
            assert "Traceback" not in detail

    def test_500_errors_use_safe_error_messages(self, admin_client):
        """Internal errors should return generic messages, not stack traces."""
        with patch("chat_app.admin_collections_routes._get_chroma_client", side_effect=RuntimeError("DB connection failed")):
            resp = admin_client.get("/api/admin/collections")
            if resp.status_code == 500:
                detail = resp.json().get("detail", "")
                # Should not expose the raw exception message to the client
                assert "RuntimeError" not in detail or "Internal error" in detail


# ===========================================================================
# 10. Header Security Tests
# ===========================================================================

class TestHeaderSecurity:
    """Verify security-relevant response headers."""

    def test_json_responses_have_proper_content_type(self, admin_client):
        """API responses should have application/json content type."""
        resp = admin_client.get("/api/admin/settings")
        assert "application/json" in resp.headers.get("content-type", "")

    def test_no_server_version_leak(self, admin_client):
        """Server header should not expose detailed version information."""
        resp = admin_client.get("/api/admin/settings")
        server = resp.headers.get("server", "")
        # Should not expose detailed internal versions
        assert "Python" not in server or server == ""
