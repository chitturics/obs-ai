"""Tests for security startup checks."""

import pytest


class TestSecurityStartupChecks:

    def test_development_passes_with_defaults(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_ENV", "development")
        monkeypatch.setenv("ENABLE_AUTHENTICATION", "false")
        from chat_app.security_startup import run_security_checks
        result = run_security_checks()
        assert result["passed"] is True  # No blockers in dev
        assert result["environment"] == "development"

    def test_production_blocks_no_auth(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_ENV", "production")
        monkeypatch.setenv("ENABLE_AUTHENTICATION", "false")
        monkeypatch.delenv("CHAINLIT_AUTH_SECRET", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        from chat_app.security_startup import run_security_checks
        result = run_security_checks()
        assert result["passed"] is False
        assert any("disabled in production" in b for b in result["blockers"])

    def test_production_blocks_default_db_password(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_ENV", "production")
        monkeypatch.setenv("ENABLE_AUTHENTICATION", "true")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://chainlit:chainlit@db:5432/chainlit")
        monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "a" * 32)
        monkeypatch.setenv("JWT_SECRET", "b" * 32)
        from chat_app.security_startup import run_security_checks
        result = run_security_checks()
        assert any("default password" in b for b in result["blockers"])

    def test_production_blocks_short_secret(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_ENV", "production")
        monkeypatch.setenv("ENABLE_AUTHENTICATION", "true")
        monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "short")
        monkeypatch.setenv("JWT_SECRET", "also_short")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:secure_pw_123@db:5432/db")
        from chat_app.security_startup import run_security_checks
        result = run_security_checks()
        assert any("too short" in b for b in result["blockers"])

    def test_production_passes_with_proper_config(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_ENV", "production")
        monkeypatch.setenv("ENABLE_AUTHENTICATION", "true")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:secure_pw_123@db:5432/db")
        monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "a" * 32)
        monkeypatch.setenv("JWT_SECRET", "b" * 32)
        monkeypatch.setenv("ADMIN_PASSWORD", "StrongP@ssw0rd123")
        monkeypatch.setenv("SERVICE_API_KEY", "svc_key_123")
        monkeypatch.setenv("REDIS_PASSWORD", "redis_secure_pw")
        monkeypatch.setenv("GF_SECURITY_ADMIN_PASSWORD", "grafana_secure_pw")
        from chat_app.security_startup import run_security_checks
        result = run_security_checks()
        assert result["passed"] is True
        assert len(result["blockers"]) == 0


class TestAuthFailClosed:

    def test_auth_defaults_to_enabled(self):
        """_auth_enabled() should default to True (fail-closed)."""
        import os
        old = os.environ.pop("ENABLE_AUTHENTICATION", None)
        try:
            from chat_app.auth_dependencies import _auth_enabled
            # With no env var set, should default to True
            assert _auth_enabled() is True
        finally:
            if old is not None:
                os.environ["ENABLE_AUTHENTICATION"] = old

    def test_anonymous_user_is_viewer_not_admin(self):
        from chat_app.auth_dependencies import _ANONYMOUS_USER
        assert _ANONYMOUS_USER["metadata"]["role"] == "VIEWER"
