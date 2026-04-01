"""
Tests for admin observability, collection explorer, learning dashboard,
commands page, and bug fix endpoints.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    from chat_app.admin_api import router, public_router
    from chat_app.admin_api import (
        dashboard_router, pages_router, pages_public_router,
        interactive_tools_public_router, interactive_tools_router,
        observability_router, skills_router, collections_router,
        learning_router, operations_router, config_router,
        settings_router, tools_router, users_router, security_router,
    )
    from chat_app.admin_config_helpers import config_ext_router
    from chat_app.auth_dependencies import get_authenticated_user

    app = FastAPI()
    app.include_router(router)
    app.include_router(public_router)
    for sub in [dashboard_router, pages_router, pages_public_router,
                interactive_tools_public_router, interactive_tools_router,
                observability_router, skills_router, collections_router,
                learning_router, operations_router, config_router,
                config_ext_router, settings_router, tools_router,
                users_router, security_router]:
        app.include_router(sub)
    from chat_app.auth_dependencies import require_admin
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
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Collection Search
# ---------------------------------------------------------------------------

class TestCollectionSearch:
    def test_search_endpoint_exists(self, client):
        resp = client.post(
            "/api/admin/collections/search",
            json={"query": "stats", "limit": 5},
        )
        # May fail with 500 if ChromaDB not available, but should not 404
        assert resp.status_code in (200, 500)

    def test_search_requires_query(self, client):
        resp = client.post(
            "/api/admin/collections/search",
            json={"query": "", "limit": 5},
        )
        assert resp.status_code == 422  # validation error


class TestCollectionBrowse:
    def test_browse_endpoint_exists(self, client):
        resp = client.get("/api/admin/collections/test_collection/chunks?limit=5")
        # 500 expected if ChromaDB not available
        assert resp.status_code in (200, 500)


class TestCollectionDelete:
    def test_delete_endpoint_exists(self, client):
        resp = client.request(
            "DELETE",
            "/api/admin/collections/chunks",
            json={"collection_name": "test", "chunk_ids": ["id1"]},
        )
        assert resp.status_code in (200, 500)

    def test_delete_requires_ids(self, client):
        resp = client.request(
            "DELETE",
            "/api/admin/collections/chunks",
            json={"collection_name": "test", "chunk_ids": []},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

class TestObservability:
    def test_observability_returns_json(self, client):
        resp = client.get("/api/admin/observability")
        assert resp.status_code == 200
        data = resp.json()
        assert "search_performance" in data
        assert "collection_usage" in data
        assert "recent_searches" in data
        assert "intent_distribution" in data

    def test_observability_search_performance_fields(self, client):
        resp = client.get("/api/admin/observability")
        sp = resp.json()["search_performance"]
        assert "total_queries" in sp
        assert "avg_latency_ms" in sp
        assert "avg_confidence" in sp


# ---------------------------------------------------------------------------
# Learning Dashboard
# ---------------------------------------------------------------------------

class TestLearningDashboard:
    def test_learning_dashboard_returns_json(self, client):
        resp = client.get("/api/admin/learning/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "job_schedule" in data
        assert "learning_history" in data
        assert "learning_trend" in data

    def test_learning_dashboard_has_jobs(self, client):
        resp = client.get("/api/admin/learning/dashboard")
        jobs = resp.json()["job_schedule"]
        assert len(jobs) == 5
        names = {j["name"] for j in jobs}
        assert "auto_heal" in names
        assert "hourly_learn" in names
        assert "monthly_audit" in names


# ---------------------------------------------------------------------------
# Backup Create
# ---------------------------------------------------------------------------

class TestBackupCreate:
    def test_backup_endpoint_exists(self, client):
        resp = client.post("/api/admin/config/backup")
        # May return ok or error depending on whether config file exists
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "error")


# ---------------------------------------------------------------------------
# Containers (Bug Fix)
# ---------------------------------------------------------------------------

class TestContainersFallback:
    def test_containers_returns_services(self, client):
        resp = client.get("/api/admin/containers")
        assert resp.status_code == 200
        data = resp.json()
        assert "services" in data
        # Should always return at least the known services fallback
        assert len(data["services"]) >= 1


# ---------------------------------------------------------------------------
# Commands Page (Public)
# ---------------------------------------------------------------------------

class TestCommandsPage:
    def test_commands_page_returns_html(self, client):
        resp = client.get("/api/admin/commands")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_commands_page_no_auth_required(self, app):
        clean_app = FastAPI()
        from chat_app.admin_api import public_router, pages_public_router
        clean_app.include_router(public_router)
        clean_app.include_router(pages_public_router)
        clean_client = TestClient(clean_app)
        resp = clean_client.get("/api/admin/commands")
        assert resp.status_code == 200

    def test_commands_data_returns_json(self, client):
        resp = client.get("/api/admin/commands-data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["commands"]) >= 15

    def test_commands_data_no_auth_required(self, app):
        clean_app = FastAPI()
        from chat_app.admin_api import public_router, pages_public_router
        clean_app.include_router(public_router)
        clean_app.include_router(pages_public_router)
        clean_client = TestClient(clean_app)
        resp = clean_client.get("/api/admin/commands-data")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Enriched record_query
# ---------------------------------------------------------------------------

class TestEnrichedRecordQuery:
    def test_record_query_with_new_fields(self):
        from chat_app.admin_api import record_query, _recent_queries, _collection_hit_counts
        initial_count = len(_recent_queries)
        record_query(
            query="test observability query",
            intent="spl_generation",
            collections_searched=["col_a", "col_b"],
            chunks_found=5,
            confidence=0.85,
            duration_ms=150,
            profile="LLM_PRO",
        )
        assert len(_recent_queries) > initial_count
        last = _recent_queries[-1]
        assert last["collections_searched"] == ["col_a", "col_b"]
        assert last["chunks_found"] == 5
        assert last["confidence"] == 0.85
        assert last["duration_ms"] == 150
        assert last["profile"] == "LLM_PRO"
        assert _collection_hit_counts.get("col_a", 0) >= 1
        assert _collection_hit_counts.get("col_b", 0) >= 1
