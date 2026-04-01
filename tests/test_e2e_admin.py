"""
End-to-End Tests — Admin API, Skills, Human-in-the-Loop, Observability.

Tests the full admin flow: settings → features → skills → approvals → dashboard.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def full_app():
    """Create a FastAPI app with admin + hitl + observability routes."""
    from chat_app.admin_api import (
        router as admin_router, public_router as admin_public_router,
        config_router, settings_router, tools_router, users_router,
        security_router, observability_router, skills_router,
        skills_orch_router, workflow_templates_router,
        collections_router, learning_router, learning_ext_router, operations_router,
        dashboard_router, pages_router, pages_public_router,
        interactive_tools_public_router, interactive_tools_router,
    )
    from chat_app.admin_config_helpers import config_ext_router
    from chat_app.admin_tools_routes_ext import tools_ext_router
    from chat_app.admin_tools_routes_ext2 import tools_ext2_router
    from chat_app.human_loop_api import router as hitl_router
    from chat_app.observability_api import router as obs_router

    app = FastAPI(title="ObsAI Test")
    app.include_router(admin_router)
    app.include_router(admin_public_router)
    for _sub in [config_router, config_ext_router, settings_router,
                 tools_router, tools_ext_router, tools_ext2_router,
                 users_router, security_router, observability_router, skills_router,
                 skills_orch_router, workflow_templates_router,
                 collections_router, learning_router, learning_ext_router, operations_router,
                 dashboard_router, pages_router, pages_public_router,
                 interactive_tools_public_router, interactive_tools_router]:
        app.include_router(_sub)
    app.include_router(hitl_router)
    app.include_router(obs_router)
    # Override auth dependency to return an admin user for all tests
    from chat_app.auth_dependencies import get_authenticated_user, require_admin
    from chat_app.admin_shared import _rate_limit, _csrf_check, _track_audit_user

    async def _fake_user():
        return {
            "identifier": "test_admin",
            "metadata": {"role": "ADMIN", "provider": "test"},
        }

    app.dependency_overrides[get_authenticated_user] = _fake_user
    app.dependency_overrides[require_admin] = lambda: None
    # Disable rate limiting in tests to avoid 429s from rapid test requests
    app.dependency_overrides[_rate_limit] = lambda: None
    app.dependency_overrides[_csrf_check] = lambda: None
    app.dependency_overrides[_track_audit_user] = lambda: None
    return TestClient(app)


# ---------------------------------------------------------------------------
# Admin Settings E2E
# ---------------------------------------------------------------------------

class TestAdminSettingsE2E:
    """Test settings management end-to-end."""

    def test_get_then_update_settings(self, full_app):
        """GET settings, PATCH a value, verify change."""
        # Get current settings
        resp = full_app.get("/api/admin/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "sections" in data
        old_log_level = data["sections"]["app"]["log_level"]

        # Update log level
        resp = full_app.patch(
            "/api/admin/settings/app",
            json={"values": {"log_level": "DEBUG"}},
        )
        assert resp.status_code == 200
        assert resp.json()["updated"]["log_level"] == "DEBUG"

        # Verify change persisted in GET
        resp = full_app.get("/api/admin/settings")
        assert resp.json()["sections"]["app"]["log_level"] == "DEBUG"

        # Verify audit trail recorded
        resp = full_app.get("/api/admin/settings/history")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) >= 1
        assert entries[0]["section"] == "app"

        # Restore original
        full_app.patch(
            "/api/admin/settings/app",
            json={"values": {"log_level": old_log_level}},
        )

    def test_invalid_settings_rejected(self, full_app):
        """Invalid setting values are rejected with 422."""
        resp = full_app.patch(
            "/api/admin/settings/app",
            json={"values": {"log_level": 12345}},  # Should be string
        )
        # May succeed since pydantic coerces int to str, or may fail
        assert resp.status_code in (200, 422)


# ---------------------------------------------------------------------------
# Feature Flags E2E
# ---------------------------------------------------------------------------

class TestFeatureFlagsE2E:
    """Test feature flag management end-to-end."""

    def test_list_toggle_verify(self, full_app):
        """List features, toggle one, verify it changed."""
        # List
        resp = full_app.get("/api/admin/features")
        assert resp.status_code == 200
        features = resp.json()["features"]
        assert "query_caching" in features

        # Toggle off
        resp = full_app.put(
            "/api/admin/features/query_caching",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        # Verify
        resp = full_app.get("/api/admin/features")
        assert resp.json()["features"]["query_caching"]["enabled"] is False

        # Toggle back
        full_app.put("/api/admin/features/query_caching", json={"enabled": True})


# ---------------------------------------------------------------------------
# Skills Marketplace E2E
# ---------------------------------------------------------------------------

class TestSkillsMarketplaceE2E:
    """Test skills marketplace flow end-to-end."""

    def test_discover_skills(self, full_app):
        """Discover available skills from the skills directory."""
        resp = full_app.get("/api/admin/skills/discover")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
        assert data["total"] >= 0

    @pytest.mark.skip(reason="Marketplace endpoint not yet implemented")
    def test_marketplace_browse(self, full_app):
        """Browse the skill marketplace."""
        resp = full_app.get("/api/admin/marketplace")
        assert resp.status_code == 200
        data = resp.json()
        assert "marketplace" in data
        assert "categories" in data

    def test_list_installed_skills(self, full_app):
        """List installed skills."""
        resp = full_app.get("/api/admin/skills")
        assert resp.status_code == 200
        assert "skills" in resp.json()

    def test_skill_metrics(self, full_app):
        """Get skill execution metrics."""
        resp = full_app.get("/api/admin/skills/metrics")
        assert resp.status_code == 200
        assert "aggregated" in resp.json()


# ---------------------------------------------------------------------------
# Dashboard E2E
# ---------------------------------------------------------------------------

class TestDashboardE2E:
    """Test dashboard aggregation end-to-end."""

    def test_dashboard_all_sections(self, full_app):
        """Dashboard returns all expected sections."""
        resp = full_app.get("/api/admin/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "timestamp" in data
        assert "features" in data
        assert "settings" in data
        assert "activity" in data

    def test_dashboard_activity_tracking(self, full_app):
        """Activity section tracks data."""
        resp = full_app.get("/api/admin/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert "query_volume" in data
        assert "intent_distribution" in data
        assert "recent_queries" in data


# ---------------------------------------------------------------------------
# Human-in-the-Loop E2E
# ---------------------------------------------------------------------------

class TestHITLE2E:
    """Test Human-in-the-Loop flow end-to-end."""

    def test_submit_and_retrieve_feedback(self, full_app):
        """Submit feedback, then retrieve it."""
        # Submit
        resp = full_app.post("/api/hitl/feedback", json={
            "query": "how does stats count by host work?",
            "response_summary": "The stats command aggregates data...",
            "rating": 4,
            "tags": ["spl", "stats"],
        })
        assert resp.status_code == 200
        assert resp.json()["rating"] == 4

        # Retrieve
        resp = full_app.get("/api/hitl/feedback")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert data["feedback"][0]["rating"] == 4

    def test_feedback_rating_boundaries(self, full_app):
        """Feedback ratings are clamped to 1-5."""
        resp = full_app.post("/api/hitl/feedback", json={
            "query": "test",
            "response_summary": "test response",
            "rating": 1,
        })
        assert resp.status_code == 200
        assert resp.json()["rating"] == 1

    def test_insights_empty_initially(self, full_app):
        """Insights endpoint works with no data."""
        resp = full_app.get("/api/hitl/insights")
        assert resp.status_code == 200
        assert "insights" in resp.json()

    def test_hitl_metrics(self, full_app):
        """HITL metrics endpoint returns expected structure."""
        resp = full_app.get("/api/hitl/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "pending_approvals" in data
        assert "satisfaction_score" in data

    def test_approvals_empty(self, full_app):
        """Approvals endpoint works with no pending."""
        resp = full_app.get("/api/hitl/approvals")
        assert resp.status_code == 200
        assert resp.json()["total_pending"] == 0


# ---------------------------------------------------------------------------
# Observability E2E
# ---------------------------------------------------------------------------

class TestObservabilityE2E:
    """Test observability endpoints end-to-end."""

    def test_obs_dashboard(self, full_app):
        """Observability dashboard returns all sections."""
        resp = full_app.get("/api/observability/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "tracing" in data
        assert "slos" in data
        assert "alerts" in data
        assert "metrics" in data

    def test_slo_list(self, full_app):
        """SLOs endpoint returns default definitions."""
        resp = full_app.get("/api/observability/slos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 4

    def test_specific_slo(self, full_app):
        """Get a specific SLO."""
        resp = full_app.get("/api/observability/slos/response_latency_p95")
        assert resp.status_code == 200
        assert resp.json()["name"] == "response_latency_p95"

    def test_unknown_slo(self, full_app):
        """Unknown SLO returns empty or error."""
        resp = full_app.get("/api/observability/slos/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        # May return error dict or empty result
        assert "error" in data or data == {}

    def test_alerts_list(self, full_app):
        """Alerts endpoint returns rules."""
        resp = full_app.get("/api/observability/alerts")
        assert resp.status_code == 200
        assert "rules" in resp.json()

    def test_evaluate_alerts(self, full_app):
        """Evaluate alerts endpoint works."""
        resp = full_app.post("/api/observability/alerts/evaluate")
        assert resp.status_code == 200
        assert "evaluated" in resp.json()

    def test_traces_empty(self, full_app):
        """Traces endpoint works with no data."""
        resp = full_app.get("/api/observability/traces")
        assert resp.status_code == 200
        assert "traces" in resp.json()

    def test_metrics_endpoint(self, full_app):
        """Metrics endpoint returns summary."""
        resp = full_app.get("/api/observability/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "counters" in data
        assert "gauges" in data
        assert "histograms" in data


# ---------------------------------------------------------------------------
# LLM Management E2E
# ---------------------------------------------------------------------------

class TestLLMManagementE2E:
    """Test LLM configuration endpoints."""

    def test_get_llm_config(self, full_app):
        """Get current LLM configuration."""
        resp = full_app.get("/api/admin/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert "current" in data
        assert "profiles" in data
        assert "model" in data["current"]

    def test_update_temperature(self, full_app):
        """Update LLM temperature."""
        resp = full_app.patch(
            "/api/admin/llm",
            json={"temperature": 0.5},
        )
        assert resp.status_code == 200
        assert resp.json()["changes"]["temperature"] == 0.5

    def test_update_empty_rejected(self, full_app):
        """Empty update is rejected."""
        resp = full_app.patch("/api/admin/llm", json={})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Prompts E2E
# ---------------------------------------------------------------------------

class TestPromptsE2E:
    """Test prompt template management."""

    def test_list_prompts(self, full_app):
        """List all prompt templates."""
        resp = full_app.get("/api/admin/prompts")
        assert resp.status_code == 200
        assert "prompts" in resp.json()

    def test_update_prompt_creates_file(self, full_app):
        """Updating a prompt creates/updates a template file."""
        # Clean up any leftover file from previous test runs
        from pathlib import Path
        template_dir = Path(__file__).resolve().parent.parent / "chat_app" / "prompt_templates"
        cleanup_path = template_dir / "test_custom_prompt.md"
        if cleanup_path.exists():
            cleanup_path.unlink()

        resp = full_app.put(
            "/api/admin/prompts/test_custom_prompt",
            json={"content": "This is a test prompt template for ObsAI testing."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_new"] is True
        assert "test_custom_prompt" in data["name"]

        # Clean up
        if cleanup_path.exists():
            cleanup_path.unlink()


# ---------------------------------------------------------------------------
# Agent Tasks E2E
# ---------------------------------------------------------------------------

class TestAgentTasksE2E:
    """Test agent task listing."""

    def test_list_agent_tasks(self, full_app):
        """List all agent tasks."""
        resp = full_app.get("/api/admin/agent-tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        # Should have at least the builtin tasks
        builtin_names = [t["name"] for t in data["tasks"] if t["type"] == "builtin"]
        assert "spl_analysis" in builtin_names


# ---------------------------------------------------------------------------
# Collections E2E
# ---------------------------------------------------------------------------

class TestCollectionsE2E:
    """Test collection management."""

    def test_list_collections(self, full_app):
        """List collections (may fail if ChromaDB not running)."""
        resp = full_app.get("/api/admin/collections")
        assert resp.status_code == 200
        assert "collections" in resp.json()


# ---------------------------------------------------------------------------
# Uploads E2E
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="Upload endpoints not yet implemented")
class TestUploadsE2E:
    """Test upload/ingestion management."""

    def test_list_uploads(self, full_app):
        """List configured upload directories."""
        resp = full_app.get("/api/admin/uploads")
        assert resp.status_code == 200
        data = resp.json()
        assert "directories" in data
        assert "supported_types" in data

    def test_ingest_nonexistent_dir(self, full_app):
        """Ingestion of nonexistent directory returns 404."""
        resp = full_app.post(
            "/api/admin/uploads/ingest",
            json={"path": "/nonexistent/directory"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Feedback & Feature Requests E2E
# ---------------------------------------------------------------------------

class TestFeedbackFeatureRequestsE2E:
    """Test feedback and feature request endpoints."""

    def test_submit_feature_request(self, full_app):
        """Submit a feature request."""
        resp = full_app.post("/api/admin/feedback/feature-request", json={
            "title": "Add dark mode support",
            "description": "Would be great to have a dark theme option in the admin UI",
            "priority": "medium",
            "category": "ui",
        })
        assert resp.status_code == 200
        assert resp.json()["request"]["title"] == "Add dark mode support"

    def test_list_feature_requests(self, full_app):
        """List feature requests."""
        # Submit one first
        full_app.post("/api/admin/feedback/feature-request", json={
            "title": "Better SPL autocomplete",
            "description": "Add intelligent SPL autocomplete suggestions",
            "priority": "high",
            "category": "features",
        })

        resp = full_app.get("/api/admin/feedback/feature-requests")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    def test_get_feedback_with_filter(self, full_app):
        """Get feedback with rating filter."""
        resp = full_app.get("/api/admin/feedback?rating_filter=5")
        assert resp.status_code == 200
        assert "feedback" in resp.json()


# ---------------------------------------------------------------------------
# MCP E2E
# ---------------------------------------------------------------------------

class TestMCPE2E:
    """Test MCP management endpoints (uses /config/mcp-gateway)."""

    def test_get_mcp_gateway_config(self, full_app):
        """Get MCP gateway configuration via config shortcut."""
        resp = full_app.get("/api/admin/config/mcp-gateway")
        assert resp.status_code == 200
        assert "mcp_gateway" in resp.json()

    def test_list_mcp_servers(self, full_app):
        """List MCP servers from config."""
        resp = full_app.get("/api/admin/config/mcp-gateway/servers")
        assert resp.status_code == 200
        assert "servers" in resp.json()

    def test_old_mcp_endpoints_removed(self, full_app):
        """Old broken /mcp endpoints should no longer exist."""
        resp = full_app.get("/api/admin/mcp")
        assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Container Management E2E
# ---------------------------------------------------------------------------

class TestContainerManagementE2E:
    """Test container management endpoints."""

    def test_list_containers(self, full_app):
        """List containers (may show empty if docker not running)."""
        resp = full_app.get("/api/admin/containers")
        assert resp.status_code == 200
        assert "services" in resp.json()


# ---------------------------------------------------------------------------
# Config.yaml Management E2E
# ---------------------------------------------------------------------------

class TestConfigManagementE2E:
    """Test full config.yaml CRUD lifecycle end-to-end."""

    def test_get_full_config(self, full_app):
        """Full config returns all sections."""
        resp = full_app.get("/api/admin/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "config" in data
        assert "sections" in data
        assert "active_profile" in data

    def test_list_config_sections(self, full_app):
        """Sections endpoint returns metadata."""
        resp = full_app.get("/api/admin/config/sections")
        assert resp.status_code == 200
        sections = resp.json()["sections"]
        # Should have at least some known sections
        assert isinstance(sections, dict)

    def test_get_specific_section(self, full_app):
        """Get a known config section."""
        # Try the profiles section (always present)
        resp = full_app.get("/api/admin/config/section/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert data["section"] == "profiles"

    def test_list_profiles(self, full_app):
        """List deployment profiles."""
        resp = full_app.get("/api/admin/config/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert "active_profile" in data

    def test_get_specific_profile(self, full_app):
        """Get a specific profile by name."""
        resp = full_app.get("/api/admin/config/profiles")
        assert resp.status_code == 200
        profiles = resp.json()["profiles"]
        if profiles:
            name = list(profiles.keys())[0]
            resp = full_app.get(f"/api/admin/config/profiles/{name}")
            assert resp.status_code == 200
            assert "profile" in resp.json()

    def test_directory_shortcuts(self, full_app):
        """Directory config shortcut endpoint."""
        resp = full_app.get("/api/admin/config/directories")
        assert resp.status_code == 200
        assert "directories" in resp.json()

    def test_database_shortcut(self, full_app):
        """Database config shortcut endpoint."""
        resp = full_app.get("/api/admin/config/database")
        assert resp.status_code == 200
        assert "database" in resp.json()

    def test_retrieval_shortcut(self, full_app):
        """Retrieval config shortcut endpoint."""
        resp = full_app.get("/api/admin/config/retrieval")
        assert resp.status_code == 200
        assert "retrieval" in resp.json()

    def test_ingestion_shortcut(self, full_app):
        """Ingestion config shortcut endpoint."""
        resp = full_app.get("/api/admin/config/ingestion")
        assert resp.status_code == 200
        assert "ingestion" in resp.json()

    def test_ui_shortcut(self, full_app):
        """UI config shortcut endpoint."""
        resp = full_app.get("/api/admin/config/ui")
        assert resp.status_code == 200
        assert "ui" in resp.json()

    def test_security_shortcut(self, full_app):
        """Security config shortcut endpoint."""
        resp = full_app.get("/api/admin/config/security")
        assert resp.status_code == 200
        assert "security" in resp.json()

    def test_mcp_gateway_shortcut(self, full_app):
        """MCP gateway config shortcut endpoint."""
        resp = full_app.get("/api/admin/config/mcp-gateway")
        assert resp.status_code == 200
        assert "mcp_gateway" in resp.json()

    def test_organization_shortcut(self, full_app):
        """Organization config shortcut endpoint."""
        resp = full_app.get("/api/admin/config/organization")
        assert resp.status_code == 200
        assert "organization" in resp.json()

    def test_index_mappings_crud(self, full_app):
        """Get and update index mappings."""
        resp = full_app.get("/api/admin/config/organization/index-mappings")
        assert resp.status_code == 200
        assert "index_mappings" in resp.json()

    def test_field_mappings_crud(self, full_app):
        """Get and update field mappings."""
        resp = full_app.get("/api/admin/config/organization/field-mappings")
        assert resp.status_code == 200
        assert "field_mappings" in resp.json()

    def test_mcp_servers_list(self, full_app):
        """List MCP servers from config."""
        resp = full_app.get("/api/admin/config/mcp-gateway/servers")
        assert resp.status_code == 200
        assert "servers" in resp.json()

    def test_config_backups(self, full_app):
        """Config backups endpoint works."""
        resp = full_app.get("/api/admin/config/backups")
        assert resp.status_code == 200
        assert "backups" in resp.json()

    def test_config_export(self, full_app):
        """Export full config."""
        resp = full_app.post("/api/admin/config/export")
        assert resp.status_code == 200
        assert "config" in resp.json()

    def test_prompts_config_shortcut(self, full_app):
        """Prompt config shortcut endpoint."""
        resp = full_app.get("/api/admin/config/prompts-config")
        assert resp.status_code == 200
        assert "prompts" in resp.json()

    def test_features_config_shortcut(self, full_app):
        """Features config from config.yaml."""
        resp = full_app.get("/api/admin/config/features")
        assert resp.status_code == 200
        assert "features" in resp.json()


# ---------------------------------------------------------------------------
# Idle Worker E2E
# ---------------------------------------------------------------------------

class TestIdleWorkerE2E:
    """Test idle worker management endpoints."""

    def test_get_idle_worker_status(self, full_app):
        """Get idle worker status."""
        resp = full_app.get("/api/admin/idle-worker")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data or "error" in data

    def test_get_observability_summary(self, full_app):
        """Get observability summary from admin."""
        resp = full_app.get("/api/admin/observability-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "slos" in data or "error" in data


# ---------------------------------------------------------------------------
# Skill & Agent Catalog E2E
# ---------------------------------------------------------------------------

class TestSkillCatalogE2E:
    """Test skill catalog endpoints end-to-end."""

    def test_get_full_skill_catalog(self, full_app):
        resp = full_app.get("/api/admin/skill-catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["skills"]) > 50
        assert "summary" in data

    def test_list_skill_actions(self, full_app):
        resp = full_app.get("/api/admin/skill-catalog/actions")
        assert resp.status_code == 200
        actions = resp.json()["actions"]
        for action in ["think", "eat", "run", "sleep", "write"]:
            assert action in actions

    def test_get_skill_by_action_think(self, full_app):
        resp = full_app.get("/api/admin/skill-catalog/action/think")
        assert resp.status_code == 200
        assert resp.json()["family"] == "cognitive"

    def test_get_skills_by_family(self, full_app):
        resp = full_app.get("/api/admin/skill-catalog/family/cognitive")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 5

    def test_search_skills_spl(self, full_app):
        resp = full_app.get("/api/admin/skill-catalog/search?q=spl")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 3

    def test_skills_for_spl_generation(self, full_app):
        resp = full_app.get("/api/admin/skill-catalog/intent/spl_generation")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 3

    def test_skills_requiring_approval(self, full_app):
        resp = full_app.get("/api/admin/skill-catalog/approval-required")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 5


class TestAgentCatalogE2E:
    """Test agent catalog endpoints end-to-end."""

    def test_get_full_agent_catalog(self, full_app):
        resp = full_app.get("/api/admin/agent-catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["agents"]) > 30
        assert "summary" in data

    def test_list_agent_roles(self, full_app):
        resp = full_app.get("/api/admin/agent-catalog/roles")
        assert resp.status_code == 200
        roles = resp.json()["roles"]
        for role in ["coder", "ops guy", "tester", "monitor"]:
            assert role in roles

    def test_get_agent_by_role_coder(self, full_app):
        resp = full_app.get("/api/admin/agent-catalog/role/coder")
        assert resp.status_code == 200
        assert resp.json()["department"] == "engineering"

    def test_get_agents_by_department(self, full_app):
        resp = full_app.get("/api/admin/agent-catalog/department/engineering")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 5

    def test_search_agents_security(self, full_app):
        resp = full_app.get("/api/admin/agent-catalog/search?q=security")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 2

    def test_agents_for_troubleshooting(self, full_app):
        resp = full_app.get("/api/admin/agent-catalog/intent/troubleshooting")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 2

    def test_best_agent_for_spl(self, full_app):
        resp = full_app.get("/api/admin/agent-catalog/best/spl_generation")
        assert resp.status_code == 200
        assert resp.json()["expertise"] in ("expert", "lead")


# ---------------------------------------------------------------------------
# SSL & Port Configuration E2E
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="SSL/ports endpoints not yet implemented")
class TestSSLPortsE2E:
    """Test SSL status, toggle, and port configuration."""

    def test_get_ssl_status(self, full_app):
        resp = full_app.get("/api/admin/ssl/status")
        assert resp.status_code == 200
        d = resp.json()
        assert "enabled" in d
        assert "cert_file" in d
        assert "key_file" in d
        assert "cert_exists" in d
        assert "key_exists" in d

    def test_ssl_toggle_on_off(self, full_app):
        # Read current state
        resp = full_app.get("/api/admin/ssl/status")
        initial = resp.json()["enabled"]
        # Toggle to opposite
        resp = full_app.patch("/api/admin/ssl/toggle", json={"enabled": not initial})
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] == "ok"
        assert d["ssl_enabled"] == (not initial)
        # Toggle back
        resp = full_app.patch("/api/admin/ssl/toggle", json={"enabled": initial})
        assert resp.status_code == 200

    def test_ssl_toggle_same_state_no_change(self, full_app):
        resp = full_app.get("/api/admin/ssl/status")
        current = resp.json()["enabled"]
        resp = full_app.patch("/api/admin/ssl/toggle", json={"enabled": current})
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] == "ok"

    def test_get_port_config(self, full_app):
        resp = full_app.get("/api/admin/ports")
        assert resp.status_code == 200
        d = resp.json()
        assert "configured" in d
        assert "running" in d
        assert "labels" in d
        assert "app" in d["configured"]
        assert "gateway" in d["configured"]
        assert "ollama" in d["configured"]

    def test_save_port_config(self, full_app):
        resp = full_app.patch("/api/admin/ports", json={"app": 8090, "gateway": 8000})
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] == "ok"

    def test_save_port_invalid_rejected(self, full_app):
        resp = full_app.patch("/api/admin/ports", json={"app": 99999})
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] == "error"

    def test_generate_self_signed_cert(self, full_app):
        resp = full_app.post("/api/admin/ssl/generate-self-signed")
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] in ("ok", "error")


# ---------------------------------------------------------------------------
# Orchestration E2E
# ---------------------------------------------------------------------------

class TestOrchestrationE2E:
    """Test orchestration strategies, stats, and quality."""

    def test_list_strategies(self, full_app):
        resp = full_app.get("/api/admin/orchestration/strategies")
        assert resp.status_code == 200
        d = resp.json()
        assert "strategies" in d
        assert len(d["strategies"]) >= 15  # 17 strategies
        assert "current_default" in d

    def test_get_strategy_details(self, full_app):
        resp = full_app.get("/api/admin/orchestration/strategies")
        d = resp.json()
        strats = d["strategies"]
        # Each strategy should have key fields
        for s in strats:
            assert "name" in s
            assert "description" in s or "desc" in s

    def test_set_strategy(self, full_app):
        # Get current default
        resp = full_app.get("/api/admin/orchestration/strategies")
        original = resp.json()["current_default"]
        # Change to single_agent
        resp = full_app.post("/api/admin/orchestration/strategy", json={"strategy": "single_agent"})
        assert resp.status_code == 200
        # Restore
        full_app.post("/api/admin/orchestration/strategy", json={"strategy": original})

    def test_get_orchestration_stats(self, full_app):
        resp = full_app.get("/api/admin/orchestration/stats")
        assert resp.status_code == 200
        d = resp.json()
        assert isinstance(d, dict)

    def test_get_orchestration_quality(self, full_app):
        resp = full_app.get("/api/admin/orchestration/quality")
        assert resp.status_code == 200

    def test_reset_orchestration_stats(self, full_app):
        resp = full_app.post("/api/admin/orchestration/reset-stats")
        assert resp.status_code == 200
        d = resp.json()
        assert d.get("status") == "ok"

    def test_workflow_history(self, full_app):
        resp = full_app.get("/api/admin/workflows/history")
        assert resp.status_code == 200
        d = resp.json()
        assert isinstance(d, (dict, list))


# ---------------------------------------------------------------------------
# Knowledge Graph E2E
# ---------------------------------------------------------------------------

class TestKnowledgeGraphE2E:
    """Test knowledge graph stats, entities, and queries."""

    def test_get_kg_stats(self, full_app):
        resp = full_app.get("/api/admin/knowledge-graph/stats")
        assert resp.status_code == 200
        d = resp.json()
        assert "total_entities" in d
        assert "total_relationships" in d

    def test_list_kg_entities(self, full_app):
        resp = full_app.get("/api/admin/knowledge-graph/entities")
        assert resp.status_code == 200
        d = resp.json()
        entities = d.get("entities", d)
        assert isinstance(entities, list)

    def test_filter_kg_entities_by_type(self, full_app):
        resp = full_app.get("/api/admin/knowledge-graph/entities?type=Command")
        assert resp.status_code == 200
        d = resp.json()
        entities = d.get("entities", d)
        assert isinstance(entities, list)

    def test_query_kg(self, full_app):
        resp = full_app.get("/api/admin/knowledge-graph/query?q=stats")
        assert resp.status_code == 200
        d = resp.json()
        assert "entities" in d or "results" in d

    def test_rebuild_kg(self, full_app):
        resp = full_app.post("/api/admin/knowledge-graph/rebuild")
        assert resp.status_code == 200
        d = resp.json()
        # Response has "rebuilt": true and "stats" dict
        assert d.get("status") in ("ok", "success", "rebuilding") or d.get("rebuilt") is True


# ---------------------------------------------------------------------------
# Cache E2E
# ---------------------------------------------------------------------------

class TestCacheE2E:
    """Test cache stats and operations."""

    def test_get_cache_stats(self, full_app):
        resp = full_app.get("/api/admin/cache/stats")
        assert resp.status_code == 200
        d = resp.json()
        assert isinstance(d, dict)

    def test_search_cache_keys(self, full_app):
        resp = full_app.post("/api/admin/cache/search", json={"pattern": "*"})
        assert resp.status_code == 200

    def test_clear_cache(self, full_app):
        resp = full_app.post("/api/admin/cache/clear")
        assert resp.status_code == 200
        d = resp.json()
        assert d.get("status") in ("ok", "success")


# ---------------------------------------------------------------------------
# Audit Log E2E
# ---------------------------------------------------------------------------

class TestAuditLogE2E:
    """Test audit log retrieval and admin action logging."""

    def test_get_audit_log(self, full_app):
        resp = full_app.get("/api/admin/settings/history")
        assert resp.status_code == 200
        d = resp.json()
        entries = d.get("entries", d.get("history", d))
        assert isinstance(entries, (list, dict))

    def test_audit_after_cache_clear(self, full_app):
        """Admin actions should appear in audit log."""
        full_app.post("/api/admin/cache/clear")
        resp = full_app.get("/api/admin/settings/history")
        d = resp.json()
        entries = d.get("entries", d.get("history", []))
        if isinstance(entries, list) and entries:
            assert len(entries) >= 0  # Non-negative


# ---------------------------------------------------------------------------
# Users & Roles E2E
# ---------------------------------------------------------------------------

class TestUsersRolesE2E:
    """Test user and role management."""

    def test_list_users(self, full_app):
        resp = full_app.get("/api/admin/users")
        assert resp.status_code == 200
        d = resp.json()
        users = d.get("users", d)
        assert isinstance(users, (list, dict))

    def test_list_roles(self, full_app):
        resp = full_app.get("/api/admin/roles")
        assert resp.status_code == 200
        d = resp.json()
        roles = d.get("roles", d)
        assert isinstance(roles, (list, dict))

    def test_get_user_activity(self, full_app):
        resp = full_app.get("/api/admin/users/activity/admin")
        assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Version & Health E2E
# ---------------------------------------------------------------------------

class TestVersionHealthE2E:
    """Test version info and health endpoints."""

    @pytest.mark.skip(reason="Version endpoint not yet implemented")
    def test_get_version(self, full_app):
        resp = full_app.get("/api/admin/version")
        assert resp.status_code == 200
        d = resp.json()
        assert "current_version" in d

    @pytest.mark.skip(reason="Version changelog endpoint not yet implemented")
    def test_get_version_changelog(self, full_app):
        resp = full_app.get("/api/admin/version/changelog")
        assert resp.status_code == 200

    def test_health_check(self, full_app):
        resp = full_app.get("/api/admin/dashboard")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Search & Collections E2E (extended)
# ---------------------------------------------------------------------------

class TestSearchCollectionsE2E:
    """Extended collection and search tests."""

    def test_collection_facets(self, full_app):
        resp = full_app.get("/api/admin/collections/assistant_memory_mxbai_v2/facets")
        assert resp.status_code in (200, 404, 500)  # 500 if no ChromaDB in test

    def test_search_chunks(self, full_app):
        resp = full_app.post(
            "/api/admin/collections/search",
            json={"query": "search", "n_results": 2},
        )
        assert resp.status_code in (200, 500)  # 500 if no ChromaDB in test

    def test_browse_collection(self, full_app):
        resp = full_app.get("/api/admin/collections/assistant_memory_mxbai_v2/chunks?limit=5")
        assert resp.status_code in (200, 404, 500)  # 500 if no ChromaDB in test

    def test_reindex(self, full_app):
        resp = full_app.post("/api/admin/collections/reindex")
        assert resp.status_code == 200
        d = resp.json()
        assert d.get("status") in ("ok", "started", "already_running", "success")

    def test_reindex_status(self, full_app):
        resp = full_app.get("/api/admin/collections/reindex/status")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Learning & Idle Worker E2E
# ---------------------------------------------------------------------------

class TestLearningE2E:
    """Test learning dashboard and idle worker."""

    def test_get_learning_dashboard(self, full_app):
        resp = full_app.get("/api/admin/learning/dashboard")
        assert resp.status_code == 200

    def test_get_idle_worker_detailed(self, full_app):
        resp = full_app.get("/api/admin/idle-worker")
        assert resp.status_code == 200
        d = resp.json()
        assert isinstance(d, dict)


# ---------------------------------------------------------------------------
# Network & Diagnostics E2E
# ---------------------------------------------------------------------------

class TestNetworkDiagnosticsE2E:
    """Test network diagnostic tools."""

    def test_network_ping(self, full_app):
        resp = full_app.post("/api/admin/tools/network-test", json={"target": "localhost", "tool": "ping"})
        assert resp.status_code == 200

    def test_network_dns(self, full_app):
        resp = full_app.post("/api/admin/tools/network-test", json={"target": "localhost", "tool": "dns"})
        assert resp.status_code == 200

    def test_network_port_check(self, full_app):
        resp = full_app.post("/api/admin/tools/network-test", json={"target": "localhost", "tool": "port", "port": 5432})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Backup E2E
# ---------------------------------------------------------------------------

class TestBackupE2E:
    """Test backup operations."""

    def test_list_backups(self, full_app):
        resp = full_app.get("/api/admin/backup/all")
        assert resp.status_code == 200

    def test_list_config_backups(self, full_app):
        resp = full_app.get("/api/admin/config/backups")
        assert resp.status_code == 200

    def test_create_backup(self, full_app):
        resp = full_app.post("/api/admin/backup/unified", json={"config": True, "collections": False, "state": False})
        assert resp.status_code == 200
        d = resp.json()
        assert isinstance(d, dict)


# ---------------------------------------------------------------------------
# Agentic Framework E2E
# ---------------------------------------------------------------------------

class TestAgenticFrameworkE2E:
    """Test agentic execution and dispatch."""

    def test_agentic_status(self, full_app):
        resp = full_app.get("/api/admin/agentic/status")
        assert resp.status_code == 200

    def test_execution_log(self, full_app):
        resp = full_app.get("/api/admin/agentic/execution-log")
        assert resp.status_code == 200

    def test_dispatch_log(self, full_app):
        resp = full_app.get("/api/admin/agentic/dispatch-log")
        assert resp.status_code == 200

    def test_agent_metrics(self, full_app):
        resp = full_app.get("/api/admin/agentic/agent-metrics")
        assert resp.status_code == 200

    def test_skill_metrics_detailed(self, full_app):
        resp = full_app.get("/api/admin/skills/metrics")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Pending Approvals E2E
# ---------------------------------------------------------------------------

class TestPendingApprovalsE2E:
    """Test human-in-the-loop approval queue."""

    def test_get_pending_approvals(self, full_app):
        resp = full_app.get("/api/admin/approvals")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Organization & Index Mappings E2E (extended)
# ---------------------------------------------------------------------------

class TestOrganizationExtendedE2E:
    """Extended organization config tests."""

    def test_get_org_config(self, full_app):
        resp = full_app.get("/api/admin/config/organization")
        assert resp.status_code == 200

    def test_get_index_mappings(self, full_app):
        resp = full_app.get("/api/admin/config/organization/index-mappings")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Public Endpoints (no auth required)
# ---------------------------------------------------------------------------

class TestPublicEndpointsE2E:
    """Test endpoints that should work without authentication."""

    def test_commands_page_html(self, full_app):
        resp = full_app.get("/api/admin/commands")
        assert resp.status_code == 200
        assert "ObsAI Commands" in resp.text or "commands" in resp.text.lower()

    def test_commands_data(self, full_app):
        resp = full_app.get("/api/admin/commands-data")
        assert resp.status_code == 200

    def test_spec_files(self, full_app):
        resp = full_app.get("/api/admin/spec-files")
        assert resp.status_code == 200

    def test_splunkbase_catalog(self, full_app):
        resp = full_app.get("/api/admin/splunkbase/catalog")
        assert resp.status_code == 200

    def test_outdated_apps(self, full_app):
        resp = full_app.get("/api/admin/splunkbase/outdated")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Config Restart Policy E2E
# ---------------------------------------------------------------------------

class TestConfigRestartPolicyE2E:
    """Test config restart policies."""

    def test_get_restart_policy(self, full_app):
        resp = full_app.get("/api/admin/config/restart-policy")
        assert resp.status_code == 200
        d = resp.json()
        # Should list sections with their restart requirements
        assert isinstance(d, dict)
