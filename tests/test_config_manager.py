"""
Tests for ConfigManager and config.yaml CRUD API endpoints.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "active_profile": "LLM_MED",
    "profiles": {
        "LLM_LITE": {
            "description": "Fast CPU-only",
            "hardware": {"gpu_enabled": False, "min_ram_gb": 8},
            "llm": {"model": "qwen2.5:3b", "context_length": 4096, "temperature": 0.01},
            "performance": {"expected_query_time_seconds": 30, "max_concurrent_queries": 2},
        },
        "LLM_MED": {
            "description": "Balanced",
            "hardware": {"gpu_enabled": False, "min_ram_gb": 12},
            "llm": {"model": "qwen2.5-coder:7b", "context_length": 8192, "temperature": 0.1},
            "performance": {"expected_query_time_seconds": 120, "max_concurrent_queries": 1},
        },
        "LLM_MAX": {
            "description": "GPU",
            "hardware": {"gpu_enabled": True, "gpu_memory_gb": 8},
            "llm": {"model": "codellama:13b-instruct", "context_length": 16384, "temperature": 0.1},
            "performance": {"expected_query_time_seconds": 15, "max_concurrent_queries": 4},
        },
    },
    "directories": {
        "host_base_path": "/mnt/c/tools",
        "app_root": "/app",
        "chroma_store": "/app/chroma_store",
    },
    "database": {
        "postgres": {"host": "127.0.0.1", "port": 5432, "database": "chainlit"},
        "chromadb": {"host": "127.0.0.1", "port": 8001},
    },
    "ingestion": {
        "chunking": {"spec_files": {"chunk_size": 800}},
        "performance": {"max_workers": 4, "max_file_size_mb": 50},
    },
    "retrieval": {
        "top_k": {"feedback": 3, "specs": 5, "primary": 5},
        "similarity_threshold": {"feedback": 0.7, "specs": 0.6},
        "strategy": "multi_collection",
    },
    "prompts": {"default_splunk_version": "9.5.4", "strict_mode": True},
    "ui": {"framework": "chainlit", "host": "0.0.0.0", "port": 8000},
    "security": {
        "rate_limiting": {"enabled": True, "max_queries_per_minute": 10},
        "cors": {"enabled": True, "allowed_origins": ["http://localhost:8000"]},
    },
    "features": {
        "hybrid_search": False,
        "query_caching": True,
        "health_checks": True,
    },
    "mcp_gateway": {
        "enabled": True,
        "servers": [
            {"name": "splunk-mcp", "client_type": "sse", "endpoint": "http://127.0.0.1:8181", "enabled": True},
        ],
    },
    "organization": {
        "index_mappings": {"authentication": "wineventlog", "network": "firewall"},
        "field_mappings": {"user": "user", "source_ip": "src_ip"},
    },
}


@pytest.fixture
def tmp_config(tmp_path):
    """Create a temporary config.yaml for testing."""
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as fh:
        yaml.dump(SAMPLE_CONFIG, fh, default_flow_style=False, sort_keys=False)
    return config_file


@pytest.fixture
def config_mgr(tmp_config):
    """Create a ConfigManager pointed at the temp config."""
    from chat_app.config_manager import ConfigManager
    return ConfigManager(config_path=str(tmp_config))


@pytest.fixture
def config_app(tmp_config, monkeypatch):
    """Create a FastAPI TestClient with config.yaml pointing to temp file."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chat_app.admin_api import (
        router as admin_router, public_router as admin_public_router,
        config_router, settings_router, tools_router, users_router,
        security_router, observability_router, skills_router,
        collections_router, learning_router, operations_router,
        dashboard_router, pages_router, pages_public_router,
        interactive_tools_public_router, interactive_tools_router,
    )
    from chat_app.admin_config_helpers import config_ext_router

    # Patch the config manager singleton
    from chat_app import config_manager as cm_mod
    from chat_app.config_manager import ConfigManager
    mgr = ConfigManager(config_path=str(tmp_config))
    monkeypatch.setattr(cm_mod, "_manager", mgr)

    from chat_app.auth_dependencies import get_authenticated_user, require_admin
    from chat_app.admin_shared import _rate_limit, _csrf_check, _track_audit_user

    async def _fake_user():
        return {
            "identifier": "test_admin",
            "metadata": {"role": "ADMIN", "provider": "test"},
        }

    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(admin_public_router)
    for _sub in [config_router, config_ext_router, settings_router, tools_router,
                 users_router, security_router, observability_router, skills_router,
                 collections_router, learning_router, operations_router,
                 dashboard_router, pages_router, pages_public_router,
                 interactive_tools_public_router, interactive_tools_router]:
        app.include_router(_sub)
    app.dependency_overrides[get_authenticated_user] = _fake_user
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[_rate_limit] = lambda: None
    app.dependency_overrides[_csrf_check] = lambda: None
    app.dependency_overrides[_track_audit_user] = lambda: None
    return TestClient(app)


# ---------------------------------------------------------------------------
# ConfigManager Unit Tests
# ---------------------------------------------------------------------------

class TestConfigManagerLoad:
    """Test config loading and caching."""

    def test_load_config(self, config_mgr):
        data = config_mgr.load()
        assert data["active_profile"] == "LLM_MED"
        assert "profiles" in data
        assert "LLM_LITE" in data["profiles"]

    def test_load_returns_copy(self, config_mgr):
        """Loaded data should be a deep copy, not the internal cache."""
        d1 = config_mgr.load()
        d2 = config_mgr.load()
        assert d1 is not d2
        d1["active_profile"] = "CHANGED"
        assert config_mgr.load()["active_profile"] == "LLM_MED"

    def test_load_caching(self, config_mgr):
        config_mgr.load()
        assert config_mgr._cache is not None

    def test_load_force_refresh(self, config_mgr):
        config_mgr.load()
        config_mgr._cache["active_profile"] = "STALE"
        data = config_mgr.load(force=True)
        assert data["active_profile"] == "LLM_MED"

    def test_load_missing_file(self, tmp_path):
        """When the explicit path doesn't exist, falls back to project config.yaml."""
        from chat_app.config_manager import ConfigManager
        mgr = ConfigManager(config_path=str(tmp_path / "missing.yaml"))
        data = mgr.load()
        # Falls back to project root config.yaml if it exists, or empty dict
        assert isinstance(data, dict)


class TestConfigManagerSave:
    """Test saving config with backup."""

    def test_save_creates_backup(self, config_mgr, tmp_config):
        data = config_mgr.load()
        data["active_profile"] = "LLM_LITE"
        config_mgr.save(data, reason="test save")

        # Check backup dir created
        backup_dir = tmp_config.parent / "config_backups"
        assert backup_dir.is_dir()
        backups = list(backup_dir.glob("config_*.yaml"))
        assert len(backups) >= 1

    def test_save_creates_bak_file(self, config_mgr, tmp_config):
        data = config_mgr.load()
        config_mgr.save(data)
        assert tmp_config.with_suffix(".yaml.bak").is_file()

    def test_save_persists_changes(self, config_mgr):
        data = config_mgr.load()
        data["active_profile"] = "LLM_MAX"
        config_mgr.save(data)

        # Force reload
        data2 = config_mgr.load(force=True)
        assert data2["active_profile"] == "LLM_MAX"

    def test_save_updates_cache(self, config_mgr):
        data = config_mgr.load()
        data["active_profile"] = "LLM_LITE"
        config_mgr.save(data)
        assert config_mgr._cache["active_profile"] == "LLM_LITE"


class TestConfigManagerSections:
    """Test section-level CRUD operations."""

    def test_get_section(self, config_mgr):
        dirs = config_mgr.get_section("directories")
        assert dirs["host_base_path"] == "/mnt/c/tools"

    def test_get_missing_section(self, config_mgr):
        result = config_mgr.get_section("nonexistent")
        assert result == {}

    def test_update_section_merge(self, config_mgr):
        success, updated = config_mgr.update_section("directories", {
            "chroma_store": "/new/path",
            "new_dir": "/extra",
        })
        assert success
        assert updated["chroma_store"] == "/new/path"
        assert updated["new_dir"] == "/extra"
        assert updated["host_base_path"] == "/mnt/c/tools"  # unchanged

    def test_replace_section(self, config_mgr):
        success, new_data = config_mgr.replace_section("features", {
            "hybrid_search": True,
            "new_feature": True,
        })
        assert success
        assert new_data["hybrid_search"] is True
        assert "query_caching" not in new_data  # replaced, not merged

    def test_delete_section_key(self, config_mgr):
        result = config_mgr.delete_section_key("features", "hybrid_search")
        assert result is True
        data = config_mgr.load(force=True)
        assert "hybrid_search" not in data["features"]

    def test_delete_missing_key(self, config_mgr):
        result = config_mgr.delete_section_key("features", "nonexistent")
        assert result is False

    def test_get_all_sections(self, config_mgr):
        sections = config_mgr.get_all_sections()
        assert "profiles" in sections
        assert sections["profiles"]["type"] == "object"
        assert sections["active_profile"]["value"] == "LLM_MED"


class TestConfigManagerProfiles:
    """Test profile management."""

    def test_get_active_profile(self, config_mgr):
        assert config_mgr.get_active_profile() == "LLM_MED"

    def test_get_profile(self, config_mgr):
        profile = config_mgr.get_profile("LLM_LITE")
        assert profile["description"] == "Fast CPU-only"
        assert profile["llm"]["model"] == "qwen2.5:3b"

    def test_get_missing_profile(self, config_mgr):
        assert config_mgr.get_profile("NONEXISTENT") == {}

    def test_list_profiles(self, config_mgr):
        profiles = config_mgr.list_profiles()
        assert len(profiles) == 3
        assert "LLM_LITE" in profiles
        assert "LLM_MED" in profiles
        assert "LLM_MAX" in profiles
        assert profiles["LLM_MED"]["llm_model"] == "qwen2.5-coder:7b"

    def test_switch_profile(self, config_mgr):
        success, msg = config_mgr.switch_profile("LLM_MAX")
        assert success
        assert "LLM_MAX" in msg
        assert config_mgr.get_active_profile() == "LLM_MAX"

    def test_switch_invalid_profile(self, config_mgr):
        success, msg = config_mgr.switch_profile("INVALID")
        assert not success
        assert "not found" in msg

    def test_update_profile(self, config_mgr):
        success, updated = config_mgr.update_profile("LLM_MED", {
            "llm": {"temperature": 0.5},
        })
        assert success
        assert updated["llm"]["temperature"] == 0.5
        assert updated["llm"]["model"] == "qwen2.5-coder:7b"  # preserved


class TestConfigManagerDeepMerge:
    """Test deep merge logic."""

    def test_deep_merge_simple(self, config_mgr):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = config_mgr._deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_deep_merge_nested(self, config_mgr):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 100}}
        result = config_mgr._deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 99, "z": 100}, "b": 3}


class TestConfigManagerValidation:
    """Test validation helpers."""

    def test_validate_retrieval_good(self, config_mgr):
        ok, errors = config_mgr.validate_section("retrieval", {
            "top_k": {"feedback": 3},
            "similarity_threshold": {"feedback": 0.7},
        })
        assert ok
        assert errors == []

    def test_validate_retrieval_bad_threshold(self, config_mgr):
        ok, errors = config_mgr.validate_section("retrieval", {
            "similarity_threshold": {"feedback": 1.5},
        })
        assert not ok
        assert any("similarity_threshold" in e for e in errors)

    def test_validate_database_bad_port(self, config_mgr):
        ok, errors = config_mgr.validate_section("database", {
            "postgres": {"port": 99999},
        })
        assert not ok

    def test_validate_security_bad_rate_limit(self, config_mgr):
        ok, errors = config_mgr.validate_section("security", {
            "rate_limiting": {"max_queries_per_minute": -1},
        })
        assert not ok

    def test_validate_unknown_section(self, config_mgr):
        """Unknown sections pass validation (no rules)."""
        ok, errors = config_mgr.validate_section("unknown", {"anything": True})
        assert ok


class TestConfigManagerBackups:
    """Test backup and restore."""

    def test_get_backups_empty(self, config_mgr):
        assert config_mgr.get_backups() == []

    def test_get_backups_after_save(self, config_mgr):
        data = config_mgr.load()
        config_mgr.save(data)
        backups = config_mgr.get_backups()
        assert len(backups) >= 1
        assert "filename" in backups[0]

    def test_restore_backup(self, config_mgr):
        # Save original
        data = config_mgr.load()
        config_mgr.save(data)

        # Get backup filename
        backups = config_mgr.get_backups()
        assert len(backups) >= 1
        filename = backups[0]["filename"]

        # Change config
        data["active_profile"] = "LLM_MAX"
        config_mgr.save(data)
        assert config_mgr.load()["active_profile"] == "LLM_MAX"

        # Restore
        success, msg = config_mgr.restore_backup(filename)
        assert success
        assert config_mgr.load(force=True)["active_profile"] == "LLM_MED"

    def test_restore_missing_backup(self, config_mgr):
        success, msg = config_mgr.restore_backup("nonexistent.yaml")
        assert not success

    def test_import_export(self, config_mgr):
        exported = config_mgr.get_full_config()
        exported["active_profile"] = "LLM_LITE"
        success, msg = config_mgr.import_config(exported)
        assert success
        assert config_mgr.load(force=True)["active_profile"] == "LLM_LITE"


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------

class TestConfigAPIGetFull:
    """Test GET /api/admin/config."""

    def test_get_full_config(self, config_app):
        resp = config_app.get("/api/admin/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "config" in data
        assert "sections" in data
        assert data["active_profile"] == "LLM_MED"

    def test_list_sections(self, config_app):
        resp = config_app.get("/api/admin/config/sections")
        assert resp.status_code == 200
        sections = resp.json()["sections"]
        assert "profiles" in sections
        assert "directories" in sections


class TestConfigAPISections:
    """Test section-level CRUD API."""

    def test_get_section(self, config_app):
        resp = config_app.get("/api/admin/config/section/directories")
        assert resp.status_code == 200
        data = resp.json()
        assert data["section"] == "directories"
        assert "host_base_path" in data["data"]

    def test_get_unknown_section(self, config_app):
        resp = config_app.get("/api/admin/config/section/nonexistent")
        assert resp.status_code == 404

    def test_update_section(self, config_app):
        resp = config_app.patch(
            "/api/admin/config/section/directories",
            json={"values": {"chroma_store": "/new/path"}},
        )
        assert resp.status_code == 200
        assert resp.json()["updated"]["chroma_store"] == "/new/path"

    def test_replace_section(self, config_app):
        resp = config_app.put(
            "/api/admin/config/section/features",
            json={"data": {"hybrid_search": True, "new_flag": True}},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["hybrid_search"] is True

    def test_update_with_validation_error(self, config_app):
        resp = config_app.patch(
            "/api/admin/config/section/retrieval",
            json={"values": {"similarity_threshold": {"feedback": 5.0}}},
        )
        assert resp.status_code == 422


class TestConfigAPIProfiles:
    """Test profile management API."""

    def test_list_profiles(self, config_app):
        resp = config_app.get("/api/admin/config/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_profile"] == "LLM_MED"
        assert "LLM_LITE" in data["profiles"]

    def test_get_profile(self, config_app):
        resp = config_app.get("/api/admin/config/profiles/LLM_MED")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

    def test_get_missing_profile(self, config_app):
        resp = config_app.get("/api/admin/config/profiles/INVALID")
        assert resp.status_code == 404

    def test_switch_profile(self, config_app):
        resp = config_app.post(
            "/api/admin/config/profiles/switch",
            json={"profile": "LLM_MAX"},
        )
        assert resp.status_code == 200
        assert resp.json()["active_profile"] == "LLM_MAX"

    def test_switch_invalid_profile(self, config_app):
        resp = config_app.post(
            "/api/admin/config/profiles/switch",
            json={"profile": "INVALID"},
        )
        assert resp.status_code == 400

    def test_update_profile(self, config_app):
        resp = config_app.patch(
            "/api/admin/config/profiles/LLM_MED",
            json={"values": {"llm": {"temperature": 0.5}}},
        )
        assert resp.status_code == 200
        assert resp.json()["profile"]["llm"]["temperature"] == 0.5


class TestConfigAPIShortcuts:
    """Test section-specific shortcut endpoints."""

    def test_get_directories(self, config_app):
        resp = config_app.get("/api/admin/config/directories")
        assert resp.status_code == 200
        assert "directories" in resp.json()

    def test_get_database(self, config_app):
        resp = config_app.get("/api/admin/config/database")
        assert resp.status_code == 200
        assert "postgres" in resp.json()["database"]

    def test_get_ingestion(self, config_app):
        resp = config_app.get("/api/admin/config/ingestion")
        assert resp.status_code == 200
        assert "chunking" in resp.json()["ingestion"]

    def test_get_retrieval(self, config_app):
        resp = config_app.get("/api/admin/config/retrieval")
        assert resp.status_code == 200
        assert "top_k" in resp.json()["retrieval"]

    def test_get_prompts_config(self, config_app):
        resp = config_app.get("/api/admin/config/prompts-config")
        assert resp.status_code == 200
        assert "default_splunk_version" in resp.json()["prompts"]

    def test_get_ui(self, config_app):
        resp = config_app.get("/api/admin/config/ui")
        assert resp.status_code == 200
        assert resp.json()["ui"]["framework"] == "chainlit"

    def test_get_security(self, config_app):
        resp = config_app.get("/api/admin/config/security")
        assert resp.status_code == 200
        assert "rate_limiting" in resp.json()["security"]

    def test_get_config_features(self, config_app):
        resp = config_app.get("/api/admin/config/features")
        assert resp.status_code == 200
        assert resp.json()["features"]["query_caching"] is True

    def test_get_mcp_gateway(self, config_app):
        resp = config_app.get("/api/admin/config/mcp-gateway")
        assert resp.status_code == 200
        assert resp.json()["mcp_gateway"]["enabled"] is True

    def test_get_organization(self, config_app):
        resp = config_app.get("/api/admin/config/organization")
        assert resp.status_code == 200
        assert "index_mappings" in resp.json()["organization"]


class TestConfigAPIIndexFieldMappings:
    """Test index and field mapping CRUD."""

    def test_get_index_mappings(self, config_app):
        resp = config_app.get("/api/admin/config/organization/index-mappings")
        assert resp.status_code == 200
        mappings = resp.json()["index_mappings"]
        assert mappings["authentication"] == "wineventlog"

    def test_update_index_mappings(self, config_app):
        resp = config_app.patch(
            "/api/admin/config/organization/index-mappings",
            json={"values": {"dns": "dns_index", "authentication": "auth_new"}},
        )
        assert resp.status_code == 200
        mappings = resp.json()["index_mappings"]
        assert mappings["dns"] == "dns_index"
        assert mappings["authentication"] == "auth_new"
        assert mappings["network"] == "firewall"  # unchanged

    def test_get_field_mappings(self, config_app):
        resp = config_app.get("/api/admin/config/organization/field-mappings")
        assert resp.status_code == 200
        assert resp.json()["field_mappings"]["user"] == "user"

    def test_update_field_mappings(self, config_app):
        resp = config_app.patch(
            "/api/admin/config/organization/field-mappings",
            json={"values": {"hostname": "host", "user": "account_name"}},
        )
        assert resp.status_code == 200
        mappings = resp.json()["field_mappings"]
        assert mappings["hostname"] == "host"
        assert mappings["user"] == "account_name"


class TestConfigAPIMCPServers:
    """Test MCP server CRUD within config.yaml."""

    def test_list_mcp_servers(self, config_app):
        resp = config_app.get("/api/admin/config/mcp-gateway/servers")
        assert resp.status_code == 200
        servers = resp.json()["servers"]
        assert len(servers) == 1
        assert servers[0]["name"] == "splunk-mcp"

    def test_add_mcp_server(self, config_app):
        resp = config_app.post(
            "/api/admin/config/mcp-gateway/servers",
            json={
                "name": "github-mcp",
                "client_type": "streamable-http",
                "endpoint": "https://github.example.com/mcp",
                "enabled": False,
                "description": "GitHub MCP",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["server"]["name"] == "github-mcp"
        assert resp.json()["total_servers"] == 2

    def test_add_duplicate_mcp_server(self, config_app):
        resp = config_app.post(
            "/api/admin/config/mcp-gateway/servers",
            json={"name": "splunk-mcp", "client_type": "sse", "endpoint": "http://x"},
        )
        assert resp.status_code == 409

    def test_remove_mcp_server(self, config_app):
        resp = config_app.delete("/api/admin/config/mcp-gateway/servers/splunk-mcp")
        assert resp.status_code == 200
        assert resp.json()["removed"] == "splunk-mcp"
        assert resp.json()["remaining"] == 0

    def test_remove_unknown_mcp_server(self, config_app):
        resp = config_app.delete("/api/admin/config/mcp-gateway/servers/unknown")
        assert resp.status_code == 404


class TestConfigAPIBackupRestore:
    """Test backup and restore API."""

    def test_list_backups_empty(self, config_app):
        resp = config_app.get("/api/admin/config/backups")
        assert resp.status_code == 200
        assert resp.json()["backups"] == []

    def test_backup_created_on_update(self, config_app):
        # Update triggers save which creates backup
        config_app.patch(
            "/api/admin/config/section/directories",
            json={"values": {"chroma_store": "/new/path"}},
        )
        resp = config_app.get("/api/admin/config/backups")
        assert resp.status_code == 200
        assert len(resp.json()["backups"]) >= 1

    def test_export_config(self, config_app):
        resp = config_app.post("/api/admin/config/export")
        assert resp.status_code == 200
        assert "config" in resp.json()
        assert resp.json()["config"]["active_profile"] == "LLM_MED"

    def test_import_config(self, config_app):
        import copy
        new_config = copy.deepcopy(SAMPLE_CONFIG)
        new_config["active_profile"] = "LLM_LITE"
        resp = config_app.post(
            "/api/admin/config/import",
            json={"config": new_config},
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "Config imported successfully."

        # Verify
        resp = config_app.get("/api/admin/config")
        assert resp.json()["active_profile"] == "LLM_LITE"

    def test_restore_backup(self, config_app):
        # First change + save to create backup
        config_app.patch(
            "/api/admin/config/section/directories",
            json={"values": {"chroma_store": "/changed"}},
        )

        # Get backup
        resp = config_app.get("/api/admin/config/backups")
        backups = resp.json()["backups"]
        assert len(backups) >= 1

        # Change again
        config_app.patch(
            "/api/admin/config/section/directories",
            json={"values": {"chroma_store": "/changed_again"}},
        )

        # Restore
        resp = config_app.post(
            "/api/admin/config/restore",
            json={"filename": backups[0]["filename"]},
        )
        assert resp.status_code == 200

    def test_restore_missing_backup(self, config_app):
        resp = config_app.post(
            "/api/admin/config/restore",
            json={"filename": "nonexistent.yaml"},
        )
        assert resp.status_code == 400
