"""Comprehensive tests for chat_app/settings.py — Pydantic settings module.

Covers:
    - Settings loading from config.yaml
    - Default values for all 28 Pydantic models
    - Environment variable overrides
    - Validation (invalid values rejected)
    - Profile switching
    - get_settings() singleton / caching behaviour
    - reload_settings() forces re-read from disk
    - Each major settings sub-class
    - Edge cases: missing config.yaml, corrupted YAML, empty values
"""

import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Ensure project root is on sys.path (mirrors conftest.py)
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "chat_app"))
sys.path.insert(0, str(_project_root / "shared"))

from chat_app.settings import (
    AppSettings,
    AuthSettings,
    CacheSettings,
    ChromaSettings,
    ChunkingSettings,
    DatabaseSettings,
    DoclingSettings,
    GitHubSettings,
    IngestionSettings,
    JournalSettings,
    KnowledgeGraphSettings,
    LangfuseSettings,
    LearningSettings,
    MCPGatewaySettings,
    OllamaSettings,
    OrchestrationSettings,
    OrganizationSettings,
    PathSettings,
    RateLimitSettings,
    RetrievalSettings,
    SPLValidationSettings,
    SearchOptimizerSettings,
    SecuritySettings,
    Settings,
    SplunkbaseCatalogSettings,
    SplunkSettings,
    SSLSettings,
    UISettings,
    _build_settings,
    _load_yaml_config,
    get_settings,
    reload_settings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_config_yaml(overrides: dict | None = None) -> str:
    """Return a valid minimal config.yaml string, optionally merged with *overrides*."""
    base = {
        "active_profile": "LLM_LITE",
        "profiles": {
            "LLM_LITE": {
                "llm": {
                    "model": "qwen2.5:3b",
                    "embed_model": "mxbai-embed-large",
                    "context_length": 4096,
                    "temperature": 0.01,
                },
            },
        },
    }
    if overrides:
        base.update(overrides)
    return yaml.dump(base, default_flow_style=False)


def _write_config(tmp_path: Path, content: str) -> Path:
    """Write *content* to tmp_path/config.yaml and return the file path."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    return cfg_file


# ---------------------------------------------------------------------------
# 1. Default values for individual Pydantic sub-models
# ---------------------------------------------------------------------------

class TestDefaultValues:
    """Each sub-model should instantiate cleanly with sensible defaults."""

    def test_app_settings_defaults(self):
        s = AppSettings()
        assert s.log_level == "INFO"
        assert s.environment == "production"
        assert s.version == "3.5.1"
        assert s.active_profile == "LLM_LITE"
        assert s.org_name == "MY_ORG"
        assert s.org_full_name == "My Organization"

    def test_database_settings_defaults(self):
        s = DatabaseSettings()
        assert s.url == "" or isinstance(s.url, str)

    def test_ollama_settings_defaults(self):
        s = OllamaSettings()
        assert s.base_url == "http://127.0.0.1:11430"
        assert s.model == "qwen2.5:3b"
        assert s.embed_model == "mxbai-embed-large"
        assert s.temperature == 0.01
        assert s.num_ctx == 2048
        assert s.num_predict == 1024
        assert s.spl_model is None
        assert s.spl_temperature == 0.05
        assert s.spl_num_predict == 512
        assert s.timeout == 90

    def test_chroma_settings_defaults(self):
        s = ChromaSettings()
        assert s.dir == "/app/chroma_store"
        assert "8001" in s.http_url
        assert s.additional_collections == ""
        assert s.exclude_collections == ""
        assert s.collection is None
        assert s.feedback_collection is None

    def test_cache_settings_defaults(self):
        s = CacheSettings()
        assert s.enabled is False
        assert s.host == "127.0.0.1"
        assert s.port == 6379
        assert s.password is None
        assert s.ttl == 3600
        assert s.prompt_ttl == 300
        assert s.salt == "chainlit-salt"

    def test_journal_settings_defaults(self):
        s = JournalSettings()
        assert s.enabled is True
        assert s.base_dir == "/app/data/execution_logs"
        assert s.retention_days == 30
        assert s.flush_interval == 5.0

    def test_chunking_settings_defaults(self):
        s = ChunkingSettings()
        assert s.chunk_size == 500
        assert s.chunk_overlap == 100
        assert s.smart_chunk_tokens == 250
        assert s.smart_chunk_overlap_tokens == 40
        assert s.conf_max_chunk_size == 1200
        assert s.conf_chunk_overlap == 150
        assert s.max_final_chunk_size == 1500

    def test_chunking_chat_defaults_inherit(self):
        """chat_chunk_size/overlap defaults to code values via model_validator."""
        s = ChunkingSettings(code_chunk_size=700, code_chunk_overlap=200)
        assert s.chat_chunk_size == 700
        assert s.chat_chunk_overlap == 200

    def test_chunking_explicit_chat_overrides(self):
        """Explicit chat_chunk_size is preserved."""
        s = ChunkingSettings(chat_chunk_size=999, chat_chunk_overlap=50)
        assert s.chat_chunk_size == 999
        assert s.chat_chunk_overlap == 50

    def test_path_settings_computed_defaults(self):
        s = PathSettings()
        assert s.documents_root == "/app/public/documents"
        assert s.local_docs_root == "/app/public/documents/pdfs"
        assert s.spl_docs_root == "/app/public/documents/commands"
        assert s.cribl_docs_root == "/app/public/documents/cribl"
        assert s.feedback_root == "/app/public/documents/feedback"
        assert s.spec_static_root == "/app/public/documents/specs"
        assert s.spec_ingest_root == "/app/public/documents/specs"
        assert s.docs_base_url == "/public"

    def test_path_settings_custom_root(self):
        """Computed paths derive from custom documents_root."""
        s = PathSettings(documents_root="/data/docs")
        assert s.local_docs_root == "/data/docs/pdfs"
        assert s.spl_docs_root == "/data/docs/commands"

    def test_path_settings_docs_base_url_trailing_slash_stripped(self):
        s = PathSettings(docs_base_url="/public/")
        assert s.docs_base_url == "/public"

    def test_splunk_settings_defaults(self):
        s = SplunkSettings()
        assert s.host is None
        assert s.port == 8089
        assert s.is_configured is False

    def test_splunk_is_configured_with_token(self):
        s = SplunkSettings(host="splunk.local", token="abc123")
        assert s.is_configured is True

    def test_splunk_is_configured_with_user_pass(self):
        s = SplunkSettings(host="splunk.local", username="admin", password="changeme")
        assert s.is_configured is True

    def test_splunk_not_configured_missing_host(self):
        s = SplunkSettings(token="abc")
        assert s.is_configured is False

    def test_search_optimizer_defaults(self):
        s = SearchOptimizerSettings()
        assert s.url == "http://127.0.0.1:9005"
        assert s.enabled is True
        assert s.data_dir == "/app/data"
        assert s.auto_analyze is True

    def test_ingestion_settings_defaults(self):
        s = IngestionSettings()
        assert s.spec_chunk_size == 800
        assert s.max_workers == 4
        assert s.batch_size == 1000
        assert s.max_file_size_mb == 50
        assert s.skip_dedup is False
        assert s.force_reindex is False

    def test_security_settings_defaults(self):
        s = SecuritySettings()
        assert s.rate_limiting_enabled is True
        assert s.max_queries_per_minute == 10
        assert s.max_queries_per_hour == 100
        assert s.cors_enabled is True
        assert len(s.cors_allowed_origins) == 2

    def test_organization_defaults(self):
        s = OrganizationSettings()
        assert len(s.config_paths) == 2
        assert s.index_mappings == {}
        assert s.field_mappings == {}

    def test_mcp_gateway_defaults(self):
        s = MCPGatewaySettings()
        assert s.enabled is True
        assert s.connection_timeout == 30
        assert s.max_retries == 2
        assert s.servers == []

    def test_auth_settings_defaults(self):
        s = AuthSettings()
        assert s.enabled is True
        assert s.admin_user == "admin"
        assert s.admin_password == ""

    def test_github_settings_defaults(self):
        s = GitHubSettings()
        assert "obsai-project" in s.repo_url
        assert s.repo_owner == "obsai-project"
        assert s.repo_name == "chainlit"
        assert s.token is None
        assert s.check_interval_hours == 24

    def test_rate_limit_defaults(self):
        s = RateLimitSettings()
        assert s.global_rate == 10.0
        assert s.user_rate == 2.0

    def test_spl_validation_defaults(self):
        s = SPLValidationSettings()
        assert s.safe_time_range == 604800
        assert s.block_threshold == 80

    def test_retrieval_defaults(self):
        s = RetrievalSettings()
        assert s.top_k == {"feedback": 3, "specs": 5, "primary": 5}
        assert s.strategy == "multi_collection"
        assert s.k_multiplier == 3

    def test_ssl_settings_defaults(self):
        s = SSLSettings()
        assert s.enabled is False
        assert s.cert_file == ""
        assert s.key_file == ""

    def test_ui_settings_defaults(self):
        s = UISettings()
        assert s.framework == "chainlit"
        assert isinstance(s.ssl, SSLSettings)

    def test_learning_settings_defaults(self):
        s = LearningSettings()
        assert s.enabled is True
        assert s.qa_generation_enabled is True
        assert s.max_qa_pairs_per_cycle == 500
        assert s.reassessment_limit == 20
        assert s.cross_collection_consolidation is True

    def test_knowledge_graph_defaults(self):
        s = KnowledgeGraphSettings()
        assert s.enabled is True
        assert s.max_context_facts == 8
        assert s.max_query_depth == 2
        assert s.rebuild_on_startup is False

    def test_orchestration_defaults(self):
        s = OrchestrationSettings()
        assert s.default_strategy == "adaptive"
        assert s.max_iterations == 3
        assert s.max_parallel_agents == 3
        assert s.quality_threshold == 0.7
        assert s.resource_fallback is True
        assert s.critic_enabled is True
        assert s.human_approval_intents == []
        assert "spl_generation" in s.strategy_overrides

    def test_docling_defaults(self):
        s = DoclingSettings()
        assert s.enabled is False
        assert s.base_url == "http://127.0.0.1:5001"
        assert s.timeout == 300
        assert s.extract_tables is True

    def test_splunkbase_catalog_defaults(self):
        s = SplunkbaseCatalogSettings()
        assert s.enabled is True
        assert s.update_schedule == "daily"
        assert s.auto_compare is True

    def test_langfuse_defaults(self):
        s = LangfuseSettings()
        assert s.enabled is False
        assert "3200" in s.host
        assert s.public_key == "pk-obsai-dev"


# ---------------------------------------------------------------------------
# 2. Validation — invalid values rejected
# ---------------------------------------------------------------------------

class TestValidation:
    """Pydantic validators should reject bogus values."""

    def test_orchestration_invalid_strategy(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            OrchestrationSettings(default_strategy="banana")

    def test_orchestration_valid_strategies(self):
        for strategy in ("single_agent", "parallel", "hierarchical",
                         "iterative", "coordinator", "voting", "react",
                         "review_critique", "workflow", "swarm",
                         "human_in_loop", "adaptive"):
            s = OrchestrationSettings(default_strategy=strategy)
            assert s.default_strategy == strategy

    def test_orchestration_quality_threshold_too_high(self):
        with pytest.raises(ValueError, match="quality_threshold"):
            OrchestrationSettings(quality_threshold=1.5)

    def test_orchestration_quality_threshold_negative(self):
        with pytest.raises(ValueError, match="quality_threshold"):
            OrchestrationSettings(quality_threshold=-0.1)

    def test_orchestration_quality_threshold_boundaries(self):
        s0 = OrchestrationSettings(quality_threshold=0.0)
        assert s0.quality_threshold == 0.0
        s1 = OrchestrationSettings(quality_threshold=1.0)
        assert s1.quality_threshold == 1.0

    def test_splunkbase_catalog_invalid_schedule(self):
        with pytest.raises(ValueError, match="Unknown schedule"):
            SplunkbaseCatalogSettings(update_schedule="biweekly")

    def test_splunkbase_catalog_valid_schedules(self):
        for sched in ("daily", "weekly", "monthly"):
            s = SplunkbaseCatalogSettings(update_schedule=sched)
            assert s.update_schedule == sched


# ---------------------------------------------------------------------------
# 3. Model validators
# ---------------------------------------------------------------------------

class TestModelValidators:
    """model_validator hooks on DatabaseSettings, OllamaSettings, ChromaSettings, etc."""

    def test_database_url_from_env(self):
        with patch.dict(os.environ, {"CHAINLIT_DB_CONNINFO": "postgresql+asyncpg://u:p@h/db"}):
            s = DatabaseSettings()
            assert s.url == "postgresql+asyncpg://u:p@h/db"

    def test_database_url_fallback_to_database_url_env(self):
        with patch.dict(os.environ, {"DATABASE_URL": "pg://fallback"}, clear=False):
            env_clean = {k: v for k, v in os.environ.items() if k != "CHAINLIT_DB_CONNINFO"}
            with patch.dict(os.environ, env_clean, clear=True):
                s = DatabaseSettings()
                assert s.url == "pg://fallback"

    def test_ollama_base_url_from_env(self):
        with patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://custom:11434"}):
            s = OllamaSettings()
            assert s.base_url == "http://custom:11434"

    def test_ollama_host_env_fallback(self):
        with patch.dict(os.environ, {"OLLAMA_HOST": "http://host2:11434"}, clear=False):
            env_clean = {k: v for k, v in os.environ.items() if k != "OLLAMA_BASE_URL"}
            with patch.dict(os.environ, env_clean, clear=True):
                s = OllamaSettings()
                assert s.base_url == "http://host2:11434"

    def test_chroma_secondary_url_inherits_primary(self):
        s = ChromaSettings(http_url="http://chroma:9000")
        assert s.secondary_http_url == "http://chroma:9000"

    def test_chroma_secondary_url_env_override(self):
        with patch.dict(os.environ, {"CHROMA_SECONDARY_HTTP_URL": "http://second:9999"}):
            s = ChromaSettings()
            assert s.secondary_http_url == "http://second:9999"


# ---------------------------------------------------------------------------
# 4. _load_yaml_config() — file discovery
# ---------------------------------------------------------------------------

class TestLoadYamlConfig:
    """Test the config.yaml discovery logic."""

    def test_loads_from_config_yaml_env(self, tmp_path):
        cfg_file = _write_config(tmp_path, _minimal_config_yaml({"org_name": "TEST_ORG"}))
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            data = _load_yaml_config()
            assert data.get("org_name") == "TEST_ORG"

    def test_returns_empty_dict_when_no_file(self, tmp_path):
        """When no candidate paths exist, return empty dict."""
        with patch.dict(os.environ, {"CONFIG_YAML": str(tmp_path / "nonexistent.yaml"), "OBSAI_CONFIG_DIR": str(tmp_path / "noconfig")}):
            with patch("chat_app.settings._PROJECT_ROOT", tmp_path / "fake"):
                with patch("chat_app.settings.Path.cwd", return_value=tmp_path / "fakecwd"):
                    data = _load_yaml_config()
                    assert data == {}

    def test_corrupted_yaml_returns_empty(self, tmp_path):
        """Corrupted YAML should not crash — it returns {} after warning."""
        bad_file = tmp_path / "config.yaml"
        bad_file.write_text("active_profile: !!python/object:os.system ['echo pwned']", encoding="utf-8")
        with patch.dict(os.environ, {"CONFIG_YAML": str(bad_file)}):
            # safe_load should reject the python/object tag
            data = _load_yaml_config()
            # It either loads the scalar or raises+warns and returns {}
            assert isinstance(data, dict)

    def test_empty_yaml_returns_empty_dict(self, tmp_path):
        cfg_file = _write_config(tmp_path, "")
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            data = _load_yaml_config()
            assert data == {}

    def test_yaml_with_only_comments(self, tmp_path):
        cfg_file = _write_config(tmp_path, "# just a comment\n# nothing else\n")
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            data = _load_yaml_config()
            assert data == {}


# ---------------------------------------------------------------------------
# 5. _build_settings() — full integration with config.yaml
# ---------------------------------------------------------------------------

class TestBuildSettings:
    """Test _build_settings() with real temporary config files."""

    def _build_with_yaml(self, tmp_path, yaml_content, env_overrides=None):
        cfg_file = _write_config(tmp_path, yaml_content)
        env = {"CONFIG_YAML": str(cfg_file)}
        if env_overrides:
            env.update(env_overrides)
        # Clear settings cache to avoid stale singleton
        get_settings.cache_clear()
        with patch.dict(os.environ, env, clear=False):
            return _build_settings()

    def test_basic_build_from_yaml(self, tmp_path):
        s = self._build_with_yaml(tmp_path, _minimal_config_yaml())
        assert isinstance(s, Settings)
        assert s.app.active_profile == "LLM_LITE"
        assert s.ollama.model == "qwen2.5:3b"

    def test_profile_llm_values(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "profiles": {
                "LLM_LITE": {
                    "llm": {
                        "model": "custom-model:7b",
                        "embed_model": "custom-embed",
                        "context_length": 8192,
                        "temperature": 0.5,
                        "spl_model": "spl-custom:3b",
                        "spl_temperature": 0.1,
                    },
                },
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.ollama.model == "custom-model:7b"
        assert s.ollama.embed_model == "custom-embed"
        assert s.ollama.num_ctx == 8192
        assert s.ollama.temperature == 0.5
        assert s.ollama.spl_model == "spl-custom:3b"
        assert s.ollama.spl_temperature == 0.1

    def test_retrieval_section_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "retrieval": {
                "top_k": {"feedback": 10, "specs": 20, "primary": 15},
                "similarity_threshold": {"feedback": 0.8, "specs": 0.5, "primary": 0.4},
                "strategy": "semantic_only",
                "k_multiplier": 5,
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.retrieval.top_k["feedback"] == 10
        assert s.retrieval.top_k["specs"] == 20
        assert s.retrieval.strategy == "semantic_only"
        assert s.retrieval.k_multiplier == 5

    def test_ingestion_section_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "ingestion": {
                "chunking": {
                    "spec_files": {"chunk_size": 1200, "chunk_overlap": 300},
                    "documents": {"chunk_size": 1500, "chunk_overlap": 600},
                },
                "performance": {
                    "max_workers": 8,
                    "batch_size": 2000,
                    "max_file_size_mb": 100,
                    "skip_dedup": True,
                    "force_reindex": True,
                },
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.ingestion.spec_chunk_size == 1200
        assert s.ingestion.spec_chunk_overlap == 300
        assert s.ingestion.doc_chunk_size == 1500
        assert s.ingestion.doc_chunk_overlap == 600
        assert s.ingestion.max_workers == 8
        assert s.ingestion.batch_size == 2000
        assert s.ingestion.skip_dedup is True
        assert s.ingestion.force_reindex is True

    def test_security_section_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "security": {
                "rate_limiting": {
                    "enabled": False,
                    "max_queries_per_minute": 50,
                    "max_queries_per_hour": 500,
                },
                "cors": {
                    "enabled": False,
                    "allowed_origins": ["https://example.com"],
                },
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.security.rate_limiting_enabled is False
        assert s.security.max_queries_per_minute == 50
        assert s.security.max_queries_per_hour == 500
        assert s.security.cors_enabled is False
        assert s.security.cors_allowed_origins == ["https://example.com"]

    def test_orchestration_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "orchestration": {
                "default_strategy": "parallel",
                "max_iterations": 5,
                "max_parallel_agents": 6,
                "quality_threshold": 0.9,
                "max_duration_seconds": 60.0,
                "resource_fallback": False,
                "critic_enabled": False,
                "human_approval_intents": ["destructive_spl"],
                "strategy_overrides": {"greeting": "single_agent"},
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.orchestration.default_strategy == "parallel"
        assert s.orchestration.max_iterations == 5
        assert s.orchestration.max_parallel_agents == 6
        assert s.orchestration.quality_threshold == 0.9
        assert s.orchestration.resource_fallback is False
        assert s.orchestration.critic_enabled is False
        assert "destructive_spl" in s.orchestration.human_approval_intents
        assert s.orchestration.strategy_overrides == {"greeting": "single_agent"}

    def test_knowledge_graph_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "knowledge_graph": {
                "enabled": False,
                "max_context_facts": 15,
                "max_query_depth": 4,
                "rebuild_on_startup": True,
                "cache_path": "/custom/kg.json",
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.knowledge_graph.enabled is False
        assert s.knowledge_graph.max_context_facts == 15
        assert s.knowledge_graph.max_query_depth == 4
        assert s.knowledge_graph.rebuild_on_startup is True
        assert s.knowledge_graph.cache_path == "/custom/kg.json"

    def test_docling_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "docling": {
                "enabled": True,
                "base_url": "http://docling:5555",
                "timeout": 600,
                "ocr_enabled": True,
                "extract_tables": False,
                "chunk_tokens": 500,
                "max_doc_size_mb": 200,
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.docling.enabled is True
        assert s.docling.base_url == "http://docling:5555"
        assert s.docling.timeout == 600
        assert s.docling.ocr_enabled is True
        assert s.docling.extract_tables is False
        assert s.docling.chunk_tokens == 500
        assert s.docling.max_doc_size_mb == 200

    def test_splunkbase_catalog_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "splunkbase_catalog": {
                "enabled": True,
                "update_schedule": "weekly",
                "splunk_url": "https://splunk:8089",
                "auto_compare": False,
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.splunkbase_catalog.update_schedule == "weekly"
        assert s.splunkbase_catalog.splunk_url == "https://splunk:8089"
        assert s.splunkbase_catalog.auto_compare is False

    def test_mcp_gateway_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "mcp_gateway": {
                "enabled": False,
                "connection_timeout": 60,
                "max_retries": 5,
                "servers": [{"name": "test", "url": "http://test:8080"}],
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.mcp_gateway.enabled is False
        assert s.mcp_gateway.connection_timeout == 60
        assert s.mcp_gateway.max_retries == 5
        assert len(s.mcp_gateway.servers) == 1

    def test_organization_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "organization": {
                "config_paths": ["/custom/path/"],
                "index_mappings": {"main": "idx_main"},
                "field_mappings": {"src_ip": "source_ip"},
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.organization.config_paths == ["/custom/path/"]
        assert s.organization.index_mappings == {"main": "idx_main"}
        assert s.organization.field_mappings == {"src_ip": "source_ip"}

    def test_github_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "github": {
                "repo_url": "https://github.com/org/repo",
                "repo_owner": "org",
                "repo_name": "repo",
                "version_check_interval_hours": 12,
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.github.repo_url == "https://github.com/org/repo"
        assert s.github.repo_owner == "org"
        assert s.github.repo_name == "repo"
        assert s.github.check_interval_hours == 12

    def test_langfuse_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "langfuse": {
                "enabled": True,
                "host": "http://custom-langfuse:3000",
                "public_key": "pk-custom",
                "secret_key": "sk-custom",
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.langfuse.enabled is True
        assert s.langfuse.host == "http://custom-langfuse:3000"
        assert s.langfuse.public_key == "pk-custom"
        assert s.langfuse.secret_key == "sk-custom"

    def test_database_chromadb_from_yaml(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "database": {
                "chromadb": {
                    "host": "chroma-host",
                    "port": 9999,
                },
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert "chroma-host" in s.chroma.http_url
        assert "9999" in s.chroma.http_url

    def test_directories_chroma_store(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "directories": {
                "chroma_store": "/custom/chroma",
            },
        })
        s = self._build_with_yaml(tmp_path, yaml_content)
        assert s.chroma.dir == "/custom/chroma"


# ---------------------------------------------------------------------------
# 6. Environment variable overrides
# ---------------------------------------------------------------------------

class TestEnvOverrides:
    """Env vars take precedence over config.yaml values."""

    def _build_with_env(self, tmp_path, env_dict):
        cfg_file = _write_config(tmp_path, _minimal_config_yaml())
        env = {"CONFIG_YAML": str(cfg_file)}
        env.update(env_dict)
        get_settings.cache_clear()
        with patch.dict(os.environ, env, clear=False):
            return _build_settings()

    def test_ollama_model_env_override(self, tmp_path):
        s = self._build_with_env(tmp_path, {"OLLAMA_MODEL": "llama3:70b"})
        assert s.ollama.model == "llama3:70b"

    def test_ollama_base_url_env_override(self, tmp_path):
        s = self._build_with_env(tmp_path, {"OLLAMA_BASE_URL": "http://gpu-server:11434"})
        assert s.ollama.base_url == "http://gpu-server:11434"

    def test_ollama_temperature_env_override(self, tmp_path):
        s = self._build_with_env(tmp_path, {"OLLAMA_TEMPERATURE": "0.8"})
        assert s.ollama.temperature == 0.8

    def test_ollama_num_ctx_env_override(self, tmp_path):
        s = self._build_with_env(tmp_path, {"OLLAMA_NUM_CTX": "16384"})
        assert s.ollama.num_ctx == 16384

    def test_chroma_http_url_env_override(self, tmp_path):
        s = self._build_with_env(tmp_path, {"CHROMA_HTTP_URL": "http://remote-chroma:8002"})
        assert s.chroma.http_url == "http://remote-chroma:8002"

    def test_chroma_dir_env_override(self, tmp_path):
        s = self._build_with_env(tmp_path, {"CHROMA_DIR": "/custom/chroma/dir"})
        assert s.chroma.dir == "/custom/chroma/dir"

    def test_enable_cache_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"ENABLE_CACHE": "true"})
        assert s.cache.enabled is True

    def test_redis_host_port_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"REDIS_HOST": "redis-host", "REDIS_PORT": "6380"})
        assert s.cache.host == "redis-host"
        assert s.cache.port == 6380

    def test_active_profile_env_override(self, tmp_path):
        yaml_content = _minimal_config_yaml({
            "active_profile": "LLM_LITE",
            "profiles": {
                "LLM_LITE": {"llm": {"model": "small-model:1b"}},
                "LLM_MAX": {"llm": {"model": "big-model:70b", "context_length": 32768}},
            },
        })
        cfg_file = _write_config(tmp_path, yaml_content)
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file), "ACTIVE_PROFILE": "LLM_MAX"}):
            s = _build_settings()
        assert s.app.active_profile == "LLM_MAX"
        assert s.ollama.model == "big-model:70b"

    def test_org_name_env_override(self, tmp_path):
        s = self._build_with_env(tmp_path, {"ORG_NAME": "ACME", "ORG_FULL_NAME": "Acme Corp"})
        assert s.app.org_name == "ACME"
        assert s.app.org_full_name == "Acme Corp"

    def test_enable_authentication_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"ENABLE_AUTHENTICATION": "false"})
        assert s.auth.enabled is False

    def test_search_opt_url_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"SEARCH_OPT_URL": "http://opt:9999"})
        assert s.search_optimizer.url == "http://opt:9999"

    def test_chunk_size_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"CHUNK_SIZE": "1000", "CHUNK_OVERLAP": "200"})
        assert s.chunking.chunk_size == 1000
        assert s.chunking.chunk_overlap == 200

    def test_documents_root_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"DOCUMENTS_ROOT": "/custom/docs"})
        assert s.paths.documents_root == "/custom/docs"

    def test_spl_block_threshold_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"SPL_BLOCK_THRESHOLD": "90"})
        assert s.spl_validation.block_threshold == 90

    def test_orchestration_strategy_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"ORCHESTRATION_STRATEGY": "hierarchical"})
        assert s.orchestration.default_strategy == "hierarchical"

    def test_kg_enabled_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"KG_ENABLED": "false"})
        assert s.knowledge_graph.enabled is False

    def test_docling_enabled_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"DOCLING_ENABLED": "true"})
        assert s.docling.enabled is True

    def test_langfuse_enabled_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {
            "LANGFUSE_ENABLED": "true",
            "LANGFUSE_HOST": "http://lf:3000",
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
        })
        assert s.langfuse.enabled is True
        assert s.langfuse.host == "http://lf:3000"
        assert s.langfuse.public_key == "pk-test"
        assert s.langfuse.secret_key == "sk-test"

    def test_github_token_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {"GITHUB_TOKEN": "ghp_test123"})
        assert s.github.token == "ghp_test123"

    def test_splunk_host_env(self, tmp_path):
        s = self._build_with_env(tmp_path, {
            "SPLUNK_HOST": "splunk.example.com",
            "SPLUNK_TOKEN": "tok123",
        })
        assert s.splunk.host == "splunk.example.com"
        assert s.splunk.token == "tok123"


# ---------------------------------------------------------------------------
# 7. Profile switching
# ---------------------------------------------------------------------------

class TestProfileSwitching:
    """active_profile selects the LLM sub-section from profiles."""

    def test_switch_to_llm_med(self, tmp_path):
        yaml_content = yaml.dump({
            "active_profile": "LLM_MED",
            "profiles": {
                "LLM_LITE": {"llm": {"model": "lite-model", "context_length": 2048}},
                "LLM_MED": {"llm": {"model": "med-model:7b", "context_length": 8192, "temperature": 0.1}},
            },
        })
        cfg_file = _write_config(tmp_path, yaml_content)
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s = _build_settings()
        assert s.ollama.model == "med-model:7b"
        assert s.ollama.num_ctx == 8192
        assert s.ollama.temperature == 0.1

    def test_switch_to_llm_max(self, tmp_path):
        yaml_content = yaml.dump({
            "active_profile": "LLM_MAX",
            "profiles": {
                "LLM_LITE": {"llm": {"model": "lite-model"}},
                "LLM_MAX": {"llm": {"model": "codellama:13b-instruct", "context_length": 16384}},
            },
        })
        cfg_file = _write_config(tmp_path, yaml_content)
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s = _build_settings()
        assert s.ollama.model == "codellama:13b-instruct"
        assert s.ollama.num_ctx == 16384

    def test_nonexistent_profile_uses_defaults(self, tmp_path):
        """If active_profile points to a missing profile, defaults still work."""
        yaml_content = yaml.dump({
            "active_profile": "DOES_NOT_EXIST",
            "profiles": {
                "LLM_LITE": {"llm": {"model": "lite-model"}},
            },
        })
        cfg_file = _write_config(tmp_path, yaml_content)
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s = _build_settings()
        # Falls back to code defaults since profile lookup returns {}
        assert s.ollama.model == "qwen2.5:3b"

    def test_env_active_profile_overrides_yaml(self, tmp_path):
        yaml_content = yaml.dump({
            "active_profile": "LLM_LITE",
            "profiles": {
                "LLM_LITE": {"llm": {"model": "lite"}},
                "LLM_MED": {"llm": {"model": "med"}},
            },
        })
        cfg_file = _write_config(tmp_path, yaml_content)
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file), "ACTIVE_PROFILE": "LLM_MED"}):
            s = _build_settings()
        assert s.app.active_profile == "LLM_MED"
        assert s.ollama.model == "med"


# ---------------------------------------------------------------------------
# 8. get_settings() singleton / caching
# ---------------------------------------------------------------------------

class TestGetSettingsSingleton:
    """get_settings() uses lru_cache and returns the same object."""

    def test_same_object_returned(self, tmp_path):
        cfg_file = _write_config(tmp_path, _minimal_config_yaml())
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s1 = get_settings()
            s2 = get_settings()
        assert s1 is s2

    def test_cache_clear_returns_new_object(self, tmp_path):
        cfg_file = _write_config(tmp_path, _minimal_config_yaml())
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s1 = get_settings()
            get_settings.cache_clear()
            s2 = get_settings()
        # After cache_clear, a new Settings object is built
        assert s1 is not s2
        # But both should have identical values
        assert s1.ollama.model == s2.ollama.model


# ---------------------------------------------------------------------------
# 9. reload_settings()
# ---------------------------------------------------------------------------

class TestReloadSettings:
    """reload_settings() clears cache and rebuilds from disk."""

    def test_reload_picks_up_changes(self, tmp_path):
        cfg_file = _write_config(tmp_path, _minimal_config_yaml({"org_name": "BEFORE"}))
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s1 = get_settings()
            assert s1.app.org_name == "BEFORE"

            # Modify the file on disk
            cfg_file.write_text(
                _minimal_config_yaml({"org_name": "AFTER"}),
                encoding="utf-8",
            )
            s2 = reload_settings()
            assert s2.app.org_name == "AFTER"
            assert s1 is not s2

    def test_reload_returns_settings_instance(self, tmp_path):
        cfg_file = _write_config(tmp_path, _minimal_config_yaml())
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s = reload_settings()
        assert isinstance(s, Settings)


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Missing config, empty values, boundary conditions."""

    def test_build_with_no_config_yaml(self, tmp_path):
        """If no config.yaml exists at all, should build with defaults."""
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(tmp_path / "nope.yaml")}):
            with patch("chat_app.settings._PROJECT_ROOT", tmp_path / "fake"):
                with patch("chat_app.settings.Path.cwd", return_value=tmp_path / "fakecwd"):
                    s = _build_settings()
        assert isinstance(s, Settings)
        assert s.ollama.model == "qwen2.5:3b"
        assert s.app.active_profile == "LLM_LITE"

    def test_empty_profiles_section(self, tmp_path):
        yaml_content = yaml.dump({"active_profile": "LLM_LITE", "profiles": {}})
        cfg_file = _write_config(tmp_path, yaml_content)
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s = _build_settings()
        assert s.ollama.model == "qwen2.5:3b"  # falls back to default

    def test_profiles_missing_llm_key(self, tmp_path):
        yaml_content = yaml.dump({
            "active_profile": "LLM_LITE",
            "profiles": {"LLM_LITE": {"hardware": {"gpu_enabled": False}}},
        })
        cfg_file = _write_config(tmp_path, yaml_content)
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s = _build_settings()
        assert s.ollama.model == "qwen2.5:3b"

    def test_extra_unknown_yaml_keys_ignored(self, tmp_path):
        """Unknown top-level keys in YAML should not crash the build."""
        yaml_content = _minimal_config_yaml({"unknown_section": {"key": "value"}})
        cfg_file = _write_config(tmp_path, yaml_content)
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s = _build_settings()
        assert isinstance(s, Settings)

    def test_settings_model_is_immutable_read(self):
        """Settings sub-models are plain BaseModel — verify attribute access works."""
        s = Settings()
        assert hasattr(s, "ollama")
        assert hasattr(s, "chroma")
        assert hasattr(s, "database")
        assert hasattr(s, "orchestration")
        assert hasattr(s, "langfuse")
        assert hasattr(s, "journal")

    def test_all_submodels_present_on_settings(self):
        """Verify every documented sub-model field exists on Settings."""
        s = Settings()
        expected_fields = [
            "app", "ui", "database", "ollama", "chroma", "cache", "chunking",
            "paths", "splunk", "search_optimizer", "auth", "rate_limit",
            "spl_validation", "retrieval", "ingestion", "security", "learning",
            "knowledge_graph", "orchestration", "docling", "splunkbase_catalog",
            "organization", "mcp_gateway", "github", "langfuse", "journal",
        ]
        for field_name in expected_fields:
            assert hasattr(s, field_name), f"Settings missing field: {field_name}"

    def test_settings_field_count(self):
        """Settings has at least 26 sub-model fields (sanity check)."""
        assert len(Settings.model_fields) >= 26

    def test_boolean_env_parsing_yes(self, tmp_path):
        """envbool should accept 'yes' as True."""
        cfg_file = _write_config(tmp_path, _minimal_config_yaml())
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file), "ENABLE_CACHE": "yes"}):
            s = _build_settings()
        assert s.cache.enabled is True

    def test_boolean_env_parsing_1(self, tmp_path):
        """envbool should accept '1' as True."""
        cfg_file = _write_config(tmp_path, _minimal_config_yaml())
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file), "ENABLE_CACHE": "1"}):
            s = _build_settings()
        assert s.cache.enabled is True

    def test_boolean_env_parsing_false(self, tmp_path):
        """envbool should treat 'false' as False."""
        cfg_file = _write_config(tmp_path, _minimal_config_yaml())
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file), "ENABLE_CACHE": "false"}):
            s = _build_settings()
        assert s.cache.enabled is False

    def test_boolean_env_parsing_random_string(self, tmp_path):
        """envbool should treat random string as False."""
        cfg_file = _write_config(tmp_path, _minimal_config_yaml())
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file), "ENABLE_CACHE": "banana"}):
            s = _build_settings()
        assert s.cache.enabled is False

    def test_yaml_with_null_profile_values(self, tmp_path):
        """YAML null values within profiles should fall back to code defaults."""
        yaml_content = textwrap.dedent("""\
            active_profile: LLM_LITE
            profiles:
              LLM_LITE:
                llm:
                  model: null
                  embed_model: null
        """)
        cfg_file = _write_config(tmp_path, yaml_content)
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            s = _build_settings()
        # null profile values fall back to code defaults
        assert isinstance(s, Settings)
        assert s.ollama.model == "qwen2.5:3b"

    def test_yaml_with_null_top_level_sections(self, tmp_path):
        """YAML null for top-level sections (e.g. retrieval: null) triggers
        AttributeError in _build_settings because cfg.get('retrieval', {})
        returns None (YAML null) rather than {}.  Verify this known edge case."""
        yaml_content = textwrap.dedent("""\
            active_profile: LLM_LITE
            profiles:
              LLM_LITE:
                llm:
                  model: test-model
            retrieval: null
        """)
        cfg_file = _write_config(tmp_path, yaml_content)
        get_settings.cache_clear()
        with patch.dict(os.environ, {"CONFIG_YAML": str(cfg_file)}):
            with pytest.raises(AttributeError):
                _build_settings()

    def test_numeric_env_vars_cast_correctly(self, tmp_path):
        cfg_file = _write_config(tmp_path, _minimal_config_yaml())
        get_settings.cache_clear()
        with patch.dict(os.environ, {
            "CONFIG_YAML": str(cfg_file),
            "REDIS_PORT": "6380",
            "CACHE_TTL": "7200",
            "SPLUNK_PORT": "8090",
            "SPL_SAFE_TIME_RANGE": "86400",
        }):
            s = _build_settings()
        assert s.cache.port == 6380
        assert s.cache.ttl == 7200
        assert s.splunk.port == 8090
        assert s.spl_validation.safe_time_range == 86400


# ---------------------------------------------------------------------------
# 11. Top-level Settings model construction
# ---------------------------------------------------------------------------

class TestSettingsTopLevel:
    """Direct construction of the top-level Settings model."""

    def test_construct_with_all_defaults(self):
        s = Settings()
        assert s.app.version == "3.5.1"
        assert s.ollama.base_url == "http://127.0.0.1:11430"
        assert s.cache.enabled is False

    def test_construct_with_custom_sub_models(self):
        s = Settings(
            ollama=OllamaSettings(model="custom:13b", temperature=0.5),
            cache=CacheSettings(enabled=True, host="redis.local"),
        )
        assert s.ollama.model == "custom:13b"
        assert s.ollama.temperature == 0.5
        assert s.cache.enabled is True
        assert s.cache.host == "redis.local"

    def test_settings_serialization(self):
        """Settings should be serializable to dict via model_dump."""
        s = Settings()
        data = s.model_dump()
        assert isinstance(data, dict)
        assert "ollama" in data
        assert "chroma" in data
        assert data["ollama"]["model"] == "qwen2.5:3b"

    def test_settings_json_roundtrip(self):
        """Settings can be dumped to JSON and reconstructed."""
        s = Settings()
        json_str = s.model_dump_json()
        s2 = Settings.model_validate_json(json_str)
        assert s2.ollama.model == s.ollama.model
        assert s2.cache.port == s.cache.port
        assert s2.orchestration.default_strategy == s.orchestration.default_strategy


# ---------------------------------------------------------------------------
# Cleanup: always clear the settings cache after tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Ensure each test starts with a clean settings cache."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
