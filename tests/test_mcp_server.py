"""
MCP Admin Server Tests
======================
Tests the MCP server (mcp_server.py) that wraps admin API endpoints
for MCP-compatible clients.

Tests cover:
- Helper functions (_auto_login, _reset_client, _get_client)
- HTTP methods with 401 auto-retry (_api_get, _api_post, _api_patch)
- All MCP tool function existence and callability
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Module import fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mcp_mod():
    """Import mcp_server.py with mocked FastMCP dependency."""
    mock_fastmcp = MagicMock()
    # Make FastMCP().tool() return a no-op decorator
    mock_mcp_inst = MagicMock()
    mock_mcp_inst.tool.return_value = lambda fn: fn
    mock_fastmcp.FastMCP.return_value = mock_mcp_inst

    saved_modules = {}
    for mod_name in ["mcp", "mcp.server", "mcp.server.fastmcp", "fastmcp"]:
        saved_modules[mod_name] = sys.modules.get(mod_name)

    sys.modules["mcp"] = MagicMock()
    sys.modules["mcp.server"] = MagicMock()
    sys.modules["mcp.server.fastmcp"] = mock_fastmcp
    sys.modules["fastmcp"] = mock_fastmcp

    os.environ.setdefault("OBSAI_ADMIN_URL", "http://localhost:8000/api/admin")
    os.environ.setdefault("OBSAI_HEALTH_URL", "http://localhost:8000")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    # Force fresh import
    if "mcp_server" in sys.modules:
        del sys.modules["mcp_server"]

    import mcp_server as mod
    yield mod

    # Cleanup — restore patched modules
    for mod_name, original in saved_modules.items():
        if original is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = original
    # Reset client state
    mod._client = None
    mod._health_client = None


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestAutoLogin:
    """Test _auto_login."""

    def test_no_password_returns_empty(self, mcp_mod):
        with patch.object(mcp_mod, "AUTH_PASS", ""):
            assert mcp_mod._auto_login() == ""

    def test_successful_login(self, mcp_mod):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.cookies = {"access_token": "jwt-token-123"}
        with patch.object(mcp_mod, "AUTH_PASS", "secret"):
            with patch("httpx.post", return_value=mock_resp):
                token = mcp_mod._auto_login()
                assert token == "jwt-token-123"

    def test_failed_login(self, mcp_mod):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.cookies = {}
        with patch.object(mcp_mod, "AUTH_PASS", "wrong"):
            with patch("httpx.post", return_value=mock_resp):
                assert mcp_mod._auto_login() == ""

    def test_connection_error(self, mcp_mod):
        with patch.object(mcp_mod, "AUTH_PASS", "secret"):
            with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
                assert mcp_mod._auto_login() == ""


class TestClientManagement:
    """Test _get_client and _reset_client."""

    def test_reset_client_clears(self, mcp_mod):
        mcp_mod._client = MagicMock()
        mcp_mod._reset_client()
        assert mcp_mod._client is None

    def test_reset_client_none_safe(self, mcp_mod):
        mcp_mod._client = None
        mcp_mod._reset_client()
        assert mcp_mod._client is None

    def test_get_client_creates_on_first_call(self, mcp_mod):
        mcp_mod._client = None
        with patch.object(mcp_mod, "_auto_login", return_value="tok"):
            client = mcp_mod._get_client()
            assert client is not None
        mcp_mod._client = None  # cleanup

    def test_get_client_reuses_existing(self, mcp_mod):
        fake = MagicMock()
        mcp_mod._client = fake
        assert mcp_mod._get_client() is fake
        mcp_mod._client = None


# ---------------------------------------------------------------------------
# HTTP method tests with 401 auto-retry
# ---------------------------------------------------------------------------


def _ok_response(data=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data or {"status": "ok"}
    resp.text = json.dumps(data or {"status": "ok"})
    resp.raise_for_status = MagicMock()
    return resp


def _401_response():
    resp = MagicMock()
    resp.status_code = 401
    resp.json.return_value = {"detail": "Authentication required"}
    resp.text = '{"detail":"Authentication required"}'
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=resp)
    )
    return resp


class TestAPIGet:
    """Test _api_get."""

    def test_success(self, mcp_mod):
        client = MagicMock()
        client.get.return_value = _ok_response({"version": "3.5.0"})
        with patch.object(mcp_mod, "_get_client", return_value=client):
            result = mcp_mod._api_get("/version")
            assert result["version"] == "3.5.0"

    def test_params_passed(self, mcp_mod):
        client = MagicMock()
        client.get.return_value = _ok_response()
        with patch.object(mcp_mod, "_get_client", return_value=client):
            mcp_mod._api_get("/test", params={"a": 1})
            client.get.assert_called_with("/test", params={"a": 1})

    def test_401_retries_with_fresh_client(self, mcp_mod):
        """On 401, should reset client and retry once."""
        old_client = MagicMock()
        old_client.get.return_value = _401_response()
        new_client = MagicMock()
        new_client.get.return_value = _ok_response({"retried": True})

        calls = [0]
        def side_effect():
            calls[0] += 1
            return old_client if calls[0] == 1 else new_client

        with patch.object(mcp_mod, "_get_client", side_effect=side_effect):
            with patch.object(mcp_mod, "_reset_client"):
                result = mcp_mod._api_get("/test")
                assert result.get("retried") is True

    def test_connect_error(self, mcp_mod):
        client = MagicMock()
        client.get.side_effect = httpx.ConnectError("refused")
        with patch.object(mcp_mod, "_get_client", return_value=client):
            result = mcp_mod._api_get("/test")
            assert "error" in result
            assert "connect" in result["error"].lower() or "Cannot connect" in result["error"]

    def test_http_500(self, mcp_mod):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=resp)
        )
        client = MagicMock()
        client.get.return_value = resp
        with patch.object(mcp_mod, "_get_client", return_value=client):
            result = mcp_mod._api_get("/test")
            assert "error" in result
            assert "500" in result["error"]


class TestAPIPost:
    """Test _api_post."""

    def test_success(self, mcp_mod):
        client = MagicMock()
        client.post.return_value = _ok_response({"created": True})
        with patch.object(mcp_mod, "_get_client", return_value=client):
            result = mcp_mod._api_post("/test", json_data={"key": "val"})
            assert result["created"] is True

    def test_401_retries(self, mcp_mod):
        old_client = MagicMock()
        old_client.post.return_value = _401_response()
        new_client = MagicMock()
        new_client.post.return_value = _ok_response({"ok": True})

        calls = [0]
        def side_effect():
            calls[0] += 1
            return old_client if calls[0] == 1 else new_client

        with patch.object(mcp_mod, "_get_client", side_effect=side_effect):
            with patch.object(mcp_mod, "_reset_client"):
                result = mcp_mod._api_post("/test")
                assert result.get("ok") is True


class TestAPIPatch:
    """Test _api_patch."""

    def test_success(self, mcp_mod):
        client = MagicMock()
        client.patch.return_value = _ok_response({"updated": True})
        with patch.object(mcp_mod, "_get_client", return_value=client):
            result = mcp_mod._api_patch("/test", json_data={"k": "v"})
            assert result["updated"] is True

    def test_401_retries(self, mcp_mod):
        old_client = MagicMock()
        old_client.patch.return_value = _401_response()
        new_client = MagicMock()
        new_client.patch.return_value = _ok_response({"ok": True})

        calls = [0]
        def side_effect():
            calls[0] += 1
            return old_client if calls[0] == 1 else new_client

        with patch.object(mcp_mod, "_get_client", side_effect=side_effect):
            with patch.object(mcp_mod, "_reset_client"):
                result = mcp_mod._api_patch("/test")
                assert result.get("ok") is True


# ---------------------------------------------------------------------------
# MCP tool function existence
# ---------------------------------------------------------------------------


class TestToolFunctions:
    """Verify all MCP tool functions exist and are callable."""

    EXPECTED = [
        "check_health", "get_dashboard", "get_version", "get_version_changelog",
        "get_collections", "search_chunks", "browse_collection",
        "get_collection_facets", "manage_collection", "reindex",
        "get_reindex_status", "get_settings", "update_settings",
        "get_settings_history", "get_config", "update_config",
        "get_config_restart_policy", "get_llm_config", "update_llm_config",
        "get_features", "toggle_feature",
        "get_orchestration_strategies", "get_orchestration_stats",
        "set_orchestration_strategy", "get_kg_stats",
        "query_knowledge_graph", "browse_kg_entities",
        "get_skill_catalog", "search_skills", "get_skills_for_intent",
        "get_agent_catalog", "search_agents", "get_best_agent",
        "get_agentic_status", "get_execution_log", "get_dispatch_log",
        "get_agent_metrics", "get_installed_skills", "get_skill_metrics",
        "get_users", "get_roles", "get_user_activity",
        "get_cache_stats", "search_cache", "clear_cache",
        "get_containers", "get_container_health", "get_container_runtime",
        "get_uploads", "trigger_ingestion",
        "get_search_telemetry", "get_observability", "get_activity",
        "get_prompts", "update_prompt",
        "get_feedback", "get_feature_requests",
        "list_backups", "create_backup", "list_config_backups",
        "get_ssl_status", "get_ports",
        "get_profiles", "get_workflow_history",
        "get_idle_worker_status", "get_learning_dashboard",
        "get_splunkbase_catalog", "get_outdated_apps",
        "get_mcp_servers", "get_organization_config", "get_index_mappings",
        "get_pending_approvals", "run_network_test", "get_docs_data",
    ]

    def test_all_exist(self, mcp_mod):
        missing = [n for n in self.EXPECTED if not hasattr(mcp_mod, n)]
        assert not missing, f"Missing functions: {missing}"

    def test_all_callable(self, mcp_mod):
        for name in self.EXPECTED:
            fn = getattr(mcp_mod, name, None)
            if fn is not None:
                assert callable(fn), f"{name} not callable"

    def test_module_constants(self, mcp_mod):
        assert hasattr(mcp_mod, "ADMIN_URL")
        assert hasattr(mcp_mod, "HEALTH_URL")
        assert hasattr(mcp_mod, "AUTH_USER")
        assert hasattr(mcp_mod, "AUTH_PASS")
        assert hasattr(mcp_mod, "AUTH_TOKEN")


# ---------------------------------------------------------------------------
# MCP tool invocations with mocked HTTP
# ---------------------------------------------------------------------------


class TestToolInvocations:
    """Test each MCP tool calls the correct API path."""

    @pytest.fixture(autouse=True)
    def _mock_http(self, mcp_mod):
        self.mod = mcp_mod
        self.mock_get = patch.object(mcp_mod, "_api_get", return_value={"ok": True}).start()
        self.mock_post = patch.object(mcp_mod, "_api_post", return_value={"ok": True}).start()
        self.mock_patch = patch.object(mcp_mod, "_api_patch", return_value={"ok": True}).start()
        # Health uses a different client
        health_client = MagicMock()
        health_resp = MagicMock()
        health_resp.status_code = 200
        health_resp.json.return_value = {"status": "alive"}
        health_resp.raise_for_status = MagicMock()
        health_client.get.return_value = health_resp
        patch.object(mcp_mod, "_get_health_client", return_value=health_client).start()
        self.health_client = health_client
        yield
        patch.stopall()

    # ---------- Health ----------
    def test_check_health(self):
        self.mod.check_health()
        self.health_client.get.assert_called()

    # ---------- Dashboard ----------
    def test_get_dashboard(self):
        self.mod.get_dashboard()
        self.mock_get.assert_called_with("/dashboard")

    # ---------- Version ----------
    def test_get_version(self):
        self.mod.get_version()
        self.mock_get.assert_called_with("/version")

    def test_get_version_changelog(self):
        self.mod.get_version_changelog()
        self.mock_get.assert_called_with("/version/changelog")

    # ---------- Collections ----------
    def test_get_collections(self):
        self.mod.get_collections()
        self.mock_get.assert_called_with("/collections")

    def test_search_chunks(self):
        self.mod.search_chunks(query="test", collection="coll1", n_results=3)
        self.mock_post.assert_called_once()
        args = self.mock_post.call_args
        assert args[0][0] == "/collections/search"

    def test_browse_collection(self):
        self.mod.browse_collection(collection="coll1", offset=0, limit=10)
        self.mock_get.assert_called_once()
        path = self.mock_get.call_args[0][0]
        assert "coll1" in path and "chunks" in path

    def test_get_collection_facets(self):
        self.mod.get_collection_facets(collection="coll1")
        path = self.mock_get.call_args[0][0]
        assert "coll1" in path and "facets" in path

    def test_manage_collection(self):
        self.mod.manage_collection(collection="coll1", action="enable")
        self.mock_post.assert_called_once()

    def test_reindex(self):
        self.mod.reindex()
        self.mock_post.assert_called_once()

    def test_get_reindex_status(self):
        self.mod.get_reindex_status()
        self.mock_get.assert_called()

    # ---------- Settings ----------
    def test_get_settings(self):
        self.mod.get_settings()
        self.mock_get.assert_called_with("/settings")

    def test_update_settings(self):
        self.mod.update_settings(section="retrieval", values={"top_k": 10})
        self.mock_patch.assert_called_once()

    def test_get_settings_history(self):
        self.mod.get_settings_history()
        self.mock_get.assert_called()

    # ---------- Config ----------
    def test_get_config(self):
        self.mod.get_config()
        self.mock_get.assert_called()

    def test_update_config(self):
        self.mod.update_config(section="retrieval", values={"top_k": 5})

    def test_get_config_restart_policy(self):
        self.mod.get_config_restart_policy()
        self.mock_get.assert_called()

    # ---------- LLM ----------
    def test_get_llm_config(self):
        self.mod.get_llm_config()
        self.mock_get.assert_called_with("/llm")

    def test_update_llm_config(self):
        self.mod.update_llm_config(values={"temperature": 0.5})
        self.mock_patch.assert_called_once()

    # ---------- Features ----------
    def test_get_features(self):
        self.mod.get_features()
        self.mock_get.assert_called_with("/features")

    def test_toggle_feature(self):
        self.mod.toggle_feature(feature="knowledge_graph", enabled=True)

    # ---------- Orchestration ----------
    def test_get_orchestration_strategies(self):
        self.mod.get_orchestration_strategies()
        self.mock_get.assert_called_with("/orchestration/strategies")

    def test_get_orchestration_stats(self):
        self.mod.get_orchestration_stats()
        # Calls both /orchestration/stats and /orchestration/quality
        self.mock_get.assert_any_call("/orchestration/stats")

    def test_set_orchestration_strategy(self):
        self.mod.set_orchestration_strategy(strategy="single_agent")
        self.mock_post.assert_called_once()

    # ---------- Knowledge Graph ----------
    def test_get_kg_stats(self):
        self.mod.get_kg_stats()
        self.mock_get.assert_called_with("/knowledge-graph/stats")

    def test_query_knowledge_graph(self):
        self.mod.query_knowledge_graph(query="stats command")
        self.mock_get.assert_called()

    def test_browse_kg_entities(self):
        self.mod.browse_kg_entities()
        self.mock_get.assert_called()

    # ---------- Skills ----------
    def test_get_skill_catalog(self):
        self.mod.get_skill_catalog()
        self.mock_get.assert_called_with("/skill-catalog")

    def test_search_skills(self):
        self.mod.search_skills(query="spl")
        self.mock_get.assert_called()

    def test_get_skills_for_intent(self):
        self.mod.get_skills_for_intent(intent="spl_help")
        self.mock_get.assert_called()

    def test_get_installed_skills(self):
        self.mod.get_installed_skills()
        self.mock_get.assert_called_with("/skills")

    def test_get_skill_metrics(self):
        self.mod.get_skill_metrics()
        self.mock_get.assert_called_with("/skills/metrics")

    # ---------- Agents ----------
    def test_get_agent_catalog(self):
        self.mod.get_agent_catalog()
        self.mock_get.assert_called_with("/agent-catalog")

    def test_search_agents(self):
        self.mod.search_agents(query="security")
        self.mock_get.assert_called()

    def test_get_best_agent(self):
        self.mod.get_best_agent(intent="spl_help")
        self.mock_get.assert_called()

    # ---------- Agentic Framework ----------
    def test_get_agentic_status(self):
        self.mod.get_agentic_status()
        self.mock_get.assert_called_with("/agentic/status")

    def test_get_execution_log(self):
        self.mod.get_execution_log()
        self.mock_get.assert_called_with("/agentic/execution-log")

    def test_get_dispatch_log(self):
        self.mod.get_dispatch_log()
        self.mock_get.assert_called_with("/agentic/dispatch-log")

    def test_get_agent_metrics(self):
        self.mod.get_agent_metrics()
        self.mock_get.assert_called_with("/agents/metrics")

    # ---------- Users & Roles ----------
    def test_get_users(self):
        self.mod.get_users()
        self.mock_get.assert_called_with("/users")

    def test_get_roles(self):
        self.mod.get_roles()
        self.mock_get.assert_called_with("/roles")

    def test_get_user_activity(self):
        self.mod.get_user_activity(username="admin")
        self.mock_get.assert_called()

    # ---------- Cache ----------
    def test_get_cache_stats(self):
        self.mod.get_cache_stats()
        self.mock_get.assert_called_with("/cache/stats")

    def test_search_cache(self):
        self.mod.search_cache(pattern="*")
        self.mock_post.assert_called()

    def test_clear_cache(self):
        self.mod.clear_cache()
        self.mock_post.assert_called()

    # ---------- Containers ----------
    def test_get_containers(self):
        self.mod.get_containers()
        self.mock_get.assert_called_with("/containers")

    def test_get_container_health(self):
        self.mod.get_container_health(service="chat_ui_app")
        self.mock_get.assert_called()

    def test_get_container_runtime(self):
        self.mod.get_container_runtime()
        self.mock_get.assert_called()

    # ---------- Uploads ----------
    def test_get_uploads(self):
        self.mod.get_uploads()
        self.mock_get.assert_called_with("/uploads")

    def test_trigger_ingestion(self):
        self.mod.trigger_ingestion()
        self.mock_post.assert_called()

    # ---------- Telemetry ----------
    def test_get_search_telemetry(self):
        self.mod.get_search_telemetry()
        self.mock_get.assert_called()

    def test_get_observability(self):
        self.mod.get_observability()
        self.mock_get.assert_called_with("/observability")

    def test_get_activity(self):
        self.mod.get_activity()
        self.mock_get.assert_called_with("/activity")

    # ---------- Prompts ----------
    def test_get_prompts(self):
        self.mod.get_prompts()
        self.mock_get.assert_called_with("/prompts")

    def test_update_prompt(self):
        self.mod.update_prompt(name="system", content="You are helpful")

    # ---------- Feedback ----------
    def test_get_feedback(self):
        self.mod.get_feedback()
        self.mock_get.assert_called_with("/feedback")

    def test_get_feature_requests(self):
        self.mod.get_feature_requests()
        self.mock_get.assert_called()

    # ---------- Backup ----------
    def test_list_backups(self):
        self.mod.list_backups()
        self.mock_get.assert_called()

    def test_create_backup(self):
        self.mod.create_backup()
        self.mock_post.assert_called()

    def test_list_config_backups(self):
        self.mod.list_config_backups()
        self.mock_get.assert_called()

    # ---------- SSL ----------
    def test_get_ssl_status(self):
        self.mod.get_ssl_status()
        self.mock_get.assert_called_with("/ssl/status")

    def test_get_ports(self):
        self.mod.get_ports()
        self.mock_get.assert_called_with("/ports")

    # ---------- Profiles ----------
    def test_get_profiles(self):
        self.mod.get_profiles()
        self.mock_get.assert_called()

    # ---------- Workflow ----------
    def test_get_workflow_history(self):
        self.mod.get_workflow_history()
        self.mock_get.assert_called_with("/workflows/history")

    # ---------- Learning ----------
    def test_get_learning_dashboard(self):
        self.mod.get_learning_dashboard()
        self.mock_get.assert_called_with("/learning/dashboard")

    def test_get_idle_worker_status(self):
        self.mod.get_idle_worker_status()
        self.mock_get.assert_called_with("/idle-worker")

    # ---------- Splunkbase ----------
    def test_get_splunkbase_catalog(self):
        self.mod.get_splunkbase_catalog()
        self.mock_get.assert_called_with("/splunkbase/catalog")

    def test_get_outdated_apps(self):
        self.mod.get_outdated_apps()
        self.mock_get.assert_called_with("/splunkbase/outdated")

    # ---------- MCP Gateway ----------
    def test_get_mcp_servers(self):
        self.mod.get_mcp_servers()
        self.mock_get.assert_called()

    # ---------- Organization ----------
    def test_get_organization_config(self):
        self.mod.get_organization_config()
        self.mock_get.assert_called()

    def test_get_index_mappings(self):
        self.mod.get_index_mappings()
        self.mock_get.assert_called()

    # ---------- Approvals ----------
    def test_get_pending_approvals(self):
        self.mod.get_pending_approvals()
        self.mock_get.assert_called_with("/approvals")

    # ---------- Network ----------
    def test_run_network_test(self):
        self.mod.run_network_test(target="localhost", test_type="ping")
        self.mock_post.assert_called()

    # ---------- Docs ----------
    def test_get_docs_data(self):
        self.mod.get_docs_data()
        self.mock_get.assert_called_with("/docs/data")
