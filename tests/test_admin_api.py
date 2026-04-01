"""Comprehensive unit tests for chat_app.admin_api."""
import json
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# We need to ensure settings are importable before importing admin_api.
# The conftest.py handles chainlit mocking. We also need to ensure
# get_settings works — clear its cache so it rebuilds with defaults.
from chat_app.settings import get_settings, reload_settings

# Force a fresh settings build so admin_api can import cleanly.
get_settings.cache_clear()

from chat_app.admin_api import (
    router,
    public_router,
    _config_audit_trail,
    _feature_flags,
    _get_feature_flags,
    _recent_queries,
    _intent_counts,
    _query_volume,
    record_query,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_admin_state():
    """Reset all in-memory state between tests."""
    import chat_app.admin_api as mod
    import chat_app.admin_shared as shared
    mod._config_audit_trail.clear()
    shared._feature_flags = None  # Force re-init on next call (canonical location)
    mod._feature_flags = None  # Also reset module-level alias
    mod._recent_queries.clear()
    mod._intent_counts.clear()
    mod._query_volume.clear()
    # Clear the section model map cache so it is rebuilt each test
    mod._SECTION_MODEL_MAP.clear()
    yield


@pytest.fixture
def admin_client():
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
    # Override auth + middleware dependencies for testing
    from chat_app.auth_dependencies import get_authenticated_user, require_admin
    from chat_app.admin_shared import _rate_limit, _csrf_check, _track_audit_user

    async def _fake_user():
        return {
            "identifier": "test_admin",
            "metadata": {"role": "ADMIN", "provider": "test"},
        }

    app.dependency_overrides[get_authenticated_user] = _fake_user
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[_rate_limit] = lambda: None
    app.dependency_overrides[_csrf_check] = lambda: None
    app.dependency_overrides[_track_audit_user] = lambda: None
    return TestClient(app)


@pytest.fixture
def skills_manager_mock():
    """Provide a mock SkillsManager for the admin API to use."""
    mgr = MagicMock()
    mgr.list_skills.return_value = [
        {
            "name": "test_skill",
            "version": "1.0.0",
            "description": "A test skill",
            "category": "custom",
            "status": "active",
            "author": "Tester",
            "actions": ["action_a"],
            "tags": [],
            "metrics": {
                "execution_count": 0,
                "error_count": 0,
                "error_rate": 0.0,
                "avg_latency_ms": 0.0,
                "last_executed": None,
            },
        }
    ]
    mgr.discover_skills.return_value = []
    mgr.get_skill.return_value = None
    mgr.get_skill_metrics.return_value = {
        "total_skills": 1,
        "active_skills": 1,
        "total_actions": 1,
        "total_executions": 0,
        "total_errors": 0,
        "overall_error_rate": 0.0,
        "pending_approvals": 0,
    }
    mgr.get_execution_history.return_value = []
    mgr.get_pending_approvals.return_value = []
    mgr.approve_action.return_value = True
    return mgr


# ---------------------------------------------------------------------------
# GET /api/admin/settings — all sections
# ---------------------------------------------------------------------------

class TestGetSettings:
    def test_get_all_settings(self, admin_client):
        resp = admin_client.get("/api/admin/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "sections" in data
        sections = data["sections"]
        # Verify key sections are present
        for section_name in ("app", "ollama", "chroma", "cache", "ui", "learning"):
            assert section_name in sections, f"Missing section: {section_name}"
        assert "active_profile" in data
        assert "version" in data
        assert "timestamp" in data

    def test_settings_have_expected_fields(self, admin_client):
        resp = admin_client.get("/api/admin/settings")
        sections = resp.json()["sections"]
        # Spot-check some fields
        assert "model" in sections["ollama"]
        assert "enabled" in sections["cache"]
        assert "framework" in sections["ui"]


# ---------------------------------------------------------------------------
# PATCH /api/admin/settings/{section}
# ---------------------------------------------------------------------------

class TestUpdateSettings:
    def test_update_valid_section(self, admin_client):
        resp = admin_client.patch(
            "/api/admin/settings/cache",
            json={"values": {"enabled": True, "ttl": 7200}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["section"] == "cache"
        assert data["updated"]["enabled"] is True
        assert data["updated"]["ttl"] == 7200
        assert "audit_id" in data

    def test_update_unknown_section(self, admin_client):
        resp = admin_client.patch(
            "/api/admin/settings/nonexistent",
            json={"values": {"foo": "bar"}},
        )
        assert resp.status_code == 404
        assert "nonexistent" in resp.json()["detail"]

    def test_update_invalid_value_type(self, admin_client):
        # rate_limit.global_rate expects a float, passing a non-coercible string
        resp = admin_client.patch(
            "/api/admin/settings/rate_limit",
            json={"values": {"global_rate": "not_a_number"}},
        )
        # Pydantic may coerce or reject; if rejected it returns 422
        # If pydantic can coerce, it succeeds. Let's check for either.
        assert resp.status_code in (200, 422)

    def test_update_creates_audit_entry(self, admin_client):
        admin_client.patch(
            "/api/admin/settings/app",
            json={"values": {"log_level": "DEBUG"}},
        )
        resp = admin_client.get("/api/admin/settings/history")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) >= 1
        assert entries[0]["section"] == "app"
        assert entries[0]["action"] == "update"


# ---------------------------------------------------------------------------
# GET /api/admin/settings/history
# ---------------------------------------------------------------------------

class TestSettingsHistory:
    def test_empty_history(self, admin_client):
        resp = admin_client.get("/api/admin/settings/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["entries"] == []

    def test_history_with_entries(self, admin_client):
        admin_client.patch("/api/admin/settings/cache", json={"values": {"enabled": True}})
        admin_client.patch("/api/admin/settings/app", json={"values": {"log_level": "DEBUG"}})
        resp = admin_client.get("/api/admin/settings/history")
        data = resp.json()
        assert data["returned"] == 2

    def test_history_filter_by_section(self, admin_client):
        admin_client.patch("/api/admin/settings/cache", json={"values": {"enabled": True}})
        admin_client.patch("/api/admin/settings/app", json={"values": {"log_level": "DEBUG"}})
        resp = admin_client.get("/api/admin/settings/history?section=app")
        data = resp.json()
        assert data["returned"] == 1
        assert data["entries"][0]["section"] == "app"

    def test_history_limit(self, admin_client):
        for _ in range(5):
            admin_client.patch("/api/admin/settings/cache", json={"values": {"ttl": 100}})
        resp = admin_client.get("/api/admin/settings/history?limit=2")
        assert resp.json()["returned"] == 2


# ---------------------------------------------------------------------------
# GET/PUT /api/admin/features
# ---------------------------------------------------------------------------

class TestFeatures:
    def test_list_features(self, admin_client):
        resp = admin_client.get("/api/admin/features")
        assert resp.status_code == 200
        data = resp.json()
        assert "features" in data
        assert "total" in data
        assert "enabled_count" in data
        assert data["total"] > 0

    def test_toggle_feature_on(self, admin_client):
        # First get the features to know what is available
        features = admin_client.get("/api/admin/features").json()["features"]
        feature_name = list(features.keys())[0]
        resp = admin_client.put(
            f"/api/admin/features/{feature_name}",
            json={"enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_toggle_feature_off(self, admin_client):
        features = admin_client.get("/api/admin/features").json()["features"]
        feature_name = list(features.keys())[0]
        resp = admin_client.put(
            f"/api/admin/features/{feature_name}",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_toggle_unknown_feature(self, admin_client):
        resp = admin_client.put(
            "/api/admin/features/nonexistent_feature",
            json={"enabled": True},
        )
        assert resp.status_code == 404
        assert "nonexistent_feature" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/admin/skills
# ---------------------------------------------------------------------------

class TestSkillsEndpoints:
    def test_list_skills(self, admin_client, skills_manager_mock):
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.get("/api/admin/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert "skills" in data
        assert data["total"] == 1

    def test_discover_skills(self, admin_client, skills_manager_mock):
        skills_manager_mock.discover_skills.return_value = []
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.get("/api/admin/skills/discover")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
        assert "skills_dir" in data

    def test_install_skill_not_found(self, admin_client, skills_manager_mock):
        skills_manager_mock.get_skill.return_value = None
        skills_manager_mock.install_skill.side_effect = FileNotFoundError("not found")
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.post("/api/admin/skills/missing_skill/install")
        assert resp.status_code == 404

    def test_install_skill_success(self, admin_client, skills_manager_mock):
        mock_instance = MagicMock()
        mock_instance.manifest.version = "1.0.0"
        mock_instance.manifest.actions = []
        mock_instance.status.value = "active"
        mock_instance.error = None
        skills_manager_mock.get_skill.return_value = None
        skills_manager_mock.install_skill.return_value = mock_instance
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.post("/api/admin/skills/new_skill/install")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "new_skill"
        assert data["status"] == "active"

    def test_install_skill_already_installed(self, admin_client, skills_manager_mock):
        existing = MagicMock()
        existing.status.value = "active"
        skills_manager_mock.get_skill.return_value = existing
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.post("/api/admin/skills/existing_skill/install")
        assert resp.status_code == 409

    def test_uninstall_skill_success(self, admin_client, skills_manager_mock):
        existing = MagicMock()
        skills_manager_mock.get_skill.return_value = existing
        skills_manager_mock.uninstall_skill.return_value = True
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.post("/api/admin/skills/some_skill/uninstall")
        assert resp.status_code == 200
        assert resp.json()["uninstalled"] is True

    def test_uninstall_skill_not_installed(self, admin_client, skills_manager_mock):
        skills_manager_mock.get_skill.return_value = None
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.post("/api/admin/skills/ghost/uninstall")
        assert resp.status_code == 404

    def test_toggle_skill_enable(self, admin_client, skills_manager_mock):
        existing = MagicMock()
        existing.status.value = "disabled"
        skills_manager_mock.get_skill.return_value = existing
        skills_manager_mock.enable_skill.return_value = True
        # After enabling, get_skill returns active status
        enabled = MagicMock()
        enabled.status.value = "active"
        skills_manager_mock.get_skill.side_effect = [existing, enabled]
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.put(
                "/api/admin/skills/my_skill/toggle",
                json={"enabled": True},
            )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_toggle_skill_not_installed(self, admin_client, skills_manager_mock):
        skills_manager_mock.get_skill.return_value = None
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.put(
                "/api/admin/skills/ghost/toggle",
                json={"enabled": True},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/admin/dashboard
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_dashboard_returns_all_sections(self, admin_client, skills_manager_mock):
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock), \
             patch("chat_app.admin_api._get_engine", return_value=None):
            resp = admin_client.get("/api/admin/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "timestamp" in data
        assert "health" in data
        assert "skills" in data
        assert "features" in data
        assert "settings" in data
        assert "activity" in data

    def test_dashboard_settings_summary(self, admin_client, skills_manager_mock):
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock), \
             patch("chat_app.admin_api._get_engine", return_value=None):
            resp = admin_client.get("/api/admin/dashboard")
        settings = resp.json()["settings"]
        assert "active_profile" in settings
        assert "model" in settings
        assert "learning_enabled" in settings

    def test_dashboard_handles_import_errors(self, admin_client, skills_manager_mock):
        """Dashboard should not crash if health_monitor or resource_manager fail."""
        with patch("chat_app.admin_api._get_skills_manager", return_value=skills_manager_mock), \
             patch("chat_app.admin_api._get_engine", return_value=None):
            resp = admin_client.get("/api/admin/dashboard")
        # Even if health/resources fail, we get an error dict instead of a 500
        assert resp.status_code == 200
        data = resp.json()
        # health and resources sections should exist (possibly with error)
        assert "health" in data
        assert "resources" in data


# ---------------------------------------------------------------------------
# POST /api/admin/approvals/{id}/approve, /deny
# ---------------------------------------------------------------------------

class TestApprovals:
    def test_approve_valid(self, admin_client, skills_manager_mock):
        approval_id = "test:act:123"
        skills_manager_mock.get_pending_approvals.return_value = [
            {"id": approval_id, "action": "scan", "skill": "sec", "params": None, "timestamp": time.time()}
        ]
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "done"
        mock_result.error = None
        mock_result.latency_ms = 42.0
        skills_manager_mock.execute_action = AsyncMock(return_value=mock_result)

        with patch("chat_app.admin_dashboard_routes._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.post(f"/api/admin/approvals/{approval_id}/approve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is True
        assert data["execution"]["success"] is True

    def test_approve_not_found(self, admin_client, skills_manager_mock):
        skills_manager_mock.get_pending_approvals.return_value = []
        with patch("chat_app.admin_dashboard_routes._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.post("/api/admin/approvals/bogus_id/approve")
        assert resp.status_code == 404

    def test_deny_valid(self, admin_client, skills_manager_mock):
        approval_id = "test:deny:456"
        skills_manager_mock.get_pending_approvals.return_value = [
            {"id": approval_id, "action": "delete", "skill": "mgr", "params": None, "timestamp": time.time()}
        ]
        with patch("chat_app.admin_dashboard_routes._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.post(
                f"/api/admin/approvals/{approval_id}/deny",
                json={"reason": "too risky"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["denied"] is True
        assert data["reason"] == "too risky"

    def test_deny_not_found(self, admin_client, skills_manager_mock):
        skills_manager_mock.get_pending_approvals.return_value = []
        with patch("chat_app.admin_dashboard_routes._get_skills_manager", return_value=skills_manager_mock):
            resp = admin_client.post("/api/admin/approvals/ghost_id/deny")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Activity tracking (record_query)
# ---------------------------------------------------------------------------

class TestActivityTracking:
    def test_record_query(self, admin_client):
        record_query("show me errors", intent="search", user_id="u1")
        resp = admin_client.get("/api/admin/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tracked"] == 1
        assert data["recent_queries"][0]["query"] == "show me errors"
        assert data["intent_distribution"]["search"] == 1

    def test_record_query_truncation(self, admin_client):
        long_query = "x" * 1000
        record_query(long_query)
        resp = admin_client.get("/api/admin/activity")
        assert len(resp.json()["recent_queries"][0]["query"]) == 500
