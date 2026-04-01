"""
Centralized configuration via pydantic-settings.

Single source of truth for ALL application settings.  Env vars override
config.yaml values, which override defaults.

Usage::

    from chat_app.settings import get_settings

    settings = get_settings()
    print(settings.ollama.base_url)
    print(settings.chroma.http_url)
    print(settings.splunk.host)
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import BaseModel, Field

# Re-export all models for backward compatibility
from chat_app.settings_models import (  # noqa: F401
    AppSettings,
    AuthSettings,
    CacheSettings,
    ChromaSettings,
    ChunkingSettings,
    CriblSettings,
    DatabaseSettings,
    DoclingSettings,
    GitHubIngestionSettings,
    GitHubSettings,
    IdleWorkerSettings,
    IngestionSettings,
    JournalSettings,
    KnowledgeGraphSettings,
    LangfuseSettings,
    LearningSettings,
    MCPGatewaySettings,
    OllamaSettings,
    OrchestrationSettings,
    OrganizationSettings,
    OtelSettings,
    PathSettings,
    RateLimitSettings,
    RetrievalSettings,
    RetentionSettings,
    SPLValidationSettings,
    SSLSettings,
    SearchOptimizerSettings,
    SecuritySettings,
    SharePointIngestionSettings,
    SharePointSettings,
    SplunkSettings,
    SplunkbaseCatalogSettings,
    UISettings,
    _is_placeholder_url,
    _PLACEHOLDER_PATTERNS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration loader (runs once)
# Supports both: config/ directory (Splunk-style) and legacy config.yaml
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml_config() -> Dict[str, Any]:
    """Load configuration from config/ directory or config.yaml.

    Priority:
    1. config/ directory (if exists with .yaml files) — Splunk-style per-file config
    2. config.yaml (legacy single file)
    3. Empty dict (use defaults + env vars)
    """
    # Explicit CONFIG_YAML env var always takes priority
    explicit_path = os.getenv("CONFIG_YAML", "")
    if explicit_path:
        p = Path(explicit_path)
        try:
            if p.is_file():
                with open(p, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                    logger.info("Loaded config from CONFIG_YAML=%s", p)
                    return data
        except Exception as exc:
            logger.warning("Could not read CONFIG_YAML=%s: %s", p, exc)

    # Try config directory (Splunk-style per-file config)
    config_dirs = [
        Path(os.getenv("OBSAI_CONFIG_DIR", "")),
        Path("/app/config"),
        _PROJECT_ROOT / "config",
    ]
    for cdir in config_dirs:
        try:
            if cdir.is_dir() and any(cdir.glob("*.yaml")):
                from chat_app.config_loader import load_config_directory
                data = load_config_directory(cdir)
                if data:
                    logger.info("Loaded config from directory %s (%d sections)", cdir, len(data))
                    return data
        except Exception as exc:
            logger.debug("Config directory %s not usable: %s", cdir, exc)

    # Fall back to single config.yaml
    candidates = [
        Path("/app/config.yaml"),
        Path.cwd() / "config.yaml",
        _PROJECT_ROOT / "config.yaml",
    ]
    for path in candidates:
        try:
            if path.is_file():
                with open(path, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                    logger.info("Loaded config from %s", path)
                    return data
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
            logger.warning("Could not read %s: %s", path, exc)

    logger.info("No configuration found (using defaults + env vars)")
    return {}


def _active_profile(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return the active profile's LLM section from configuration."""
    active = os.getenv("ACTIVE_PROFILE") or cfg.get("active_profile", "LLM_LITE")
    return cfg.get("profiles", {}).get(active, {}).get("llm", {})


# ---------------------------------------------------------------------------
# Top-level Settings aggregator
# ---------------------------------------------------------------------------

class Settings(BaseModel):  # noqa: F811 — re-declared here, not in settings_models
    """
    Unified application configuration.

    All settings can be overridden via environment variables.
    Env vars take precedence over config.yaml values.
    """

    app: AppSettings = Field(default_factory=AppSettings)
    ui: UISettings = Field(default_factory=UISettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    chroma: ChromaSettings = Field(default_factory=ChromaSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    splunk: SplunkSettings = Field(default_factory=SplunkSettings)
    cribl: CriblSettings = Field(default_factory=CriblSettings)
    search_optimizer: SearchOptimizerSettings = Field(default_factory=SearchOptimizerSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    spl_validation: SPLValidationSettings = Field(default_factory=SPLValidationSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    learning: LearningSettings = Field(default_factory=LearningSettings)
    knowledge_graph: KnowledgeGraphSettings = Field(default_factory=KnowledgeGraphSettings)
    orchestration: OrchestrationSettings = Field(default_factory=OrchestrationSettings)
    docling: DoclingSettings = Field(default_factory=DoclingSettings)
    splunkbase_catalog: SplunkbaseCatalogSettings = Field(default_factory=SplunkbaseCatalogSettings)
    organization: OrganizationSettings = Field(default_factory=OrganizationSettings)
    mcp_gateway: MCPGatewaySettings = Field(default_factory=MCPGatewaySettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    sharepoint: SharePointSettings = Field(default_factory=SharePointSettings)
    github_ingestion: GitHubIngestionSettings = Field(default_factory=GitHubIngestionSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    otel: OtelSettings = Field(default_factory=OtelSettings)
    journal: JournalSettings = Field(default_factory=JournalSettings)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    idle_worker: IdleWorkerSettings = Field(default_factory=IdleWorkerSettings)

    @property
    def fast_mode(self) -> bool:
        """True when running on a CPU-only / lightweight profile.

        In fast_mode the pipeline skips non-essential LLM calls (orchestration
        skill execution, episodic memory lookup, etc.) to keep end-to-end
        latency under 30 seconds on CPU hardware.
        """
        return self.app.active_profile.upper() in ("LLM_LITE",)


# ---------------------------------------------------------------------------
# Settings builder
# ---------------------------------------------------------------------------

def _build_settings() -> Settings:
    """
    Build Settings from env vars + config.yaml.

    Priority: environment variable > config.yaml > code default.
    """
    cfg = _load_yaml_config()
    profile = _active_profile(cfg)
    cfg.get("database", {}).get("postgres", {})
    chroma_cfg = cfg.get("database", {}).get("chromadb", {})
    dirs_cfg = cfg.get("directories", {})
    ingest_cfg = cfg.get("ingestion", {}).get("chunking", {})
    sec_cfg = cfg.get("security", {}).get("rate_limiting", {})

    def env(key: str, *fallbacks: Any, cast: type = str) -> Any:
        """Return first truthy env var or fallback."""
        val = os.getenv(key)
        if val:
            return cast(val)
        for fb in fallbacks:
            if fb is not None:
                return cast(fb) if not isinstance(fb, cast) else fb
        return None

    def envbool(key: str, default: bool = False) -> bool:
        val = os.getenv(key)
        if val is None:
            return default
        return val.lower() in ("true", "1", "yes")

    # --- Build sub-models ---
    ui_cfg = cfg.get("ui", {})
    ui = UISettings(
        framework=env("UI_FRAMEWORK", ui_cfg.get("framework"), "chainlit"),
    )

    app = AppSettings(
        log_level=env("APP_LOG_LEVEL", "INFO"),
        environment=env("APP_ENVIRONMENT", "production"),
        version=env("APP_VERSION", "3.5.1"),
        active_profile=env("ACTIVE_PROFILE", cfg.get("active_profile"), "LLM_LITE"),
        org_name=env("ORG_NAME", cfg.get("org_name"), "MY_ORG"),
        org_full_name=env("ORG_FULL_NAME", cfg.get("org_full_name"), "My Organization"),
    )

    database = DatabaseSettings(
        url=(
            os.getenv("CHAINLIT_DB_CONNINFO")
            or os.getenv("DATABASE_URL")
            or ""
        ),
    )

    ollama = OllamaSettings(
        base_url=env("OLLAMA_BASE_URL", os.getenv("OLLAMA_HOST"), "http://127.0.0.1:11430"),
        model=env("OLLAMA_MODEL", profile.get("model"), "qwen2.5:3b"),
        embed_model=env("OLLAMA_EMBED_MODEL", profile.get("embed_model"), "mxbai-embed-large"),
        temperature=float(env("OLLAMA_TEMPERATURE", profile.get("temperature"), 0.01, cast=str)),
        num_ctx=int(env("OLLAMA_NUM_CTX", profile.get("context_length"), 4096, cast=str)),
        spl_model=env("SPL_MODEL", profile.get("spl_model")),
        spl_temperature=float(env("SPL_TEMPERATURE", profile.get("spl_temperature"), 0.05, cast=str)),
        num_predict=int(env("OLLAMA_NUM_PREDICT", profile.get("num_predict"), 256, cast=str)),
        spl_num_predict=int(env("SPL_NUM_PREDICT", 512, cast=str)),
    )

    chroma = ChromaSettings(
        dir=env("CHROMA_DIR", dirs_cfg.get("chroma_store"), "/app/chroma_store"),
        http_url=env("CHROMA_HTTP_URL", f"http://{chroma_cfg.get('host', '127.0.0.1')}:{chroma_cfg.get('port', 8001)}"),
        secondary_http_url=os.getenv("CHROMA_SECONDARY_HTTP_URL"),
        collection=os.getenv("CHROMA_COLLECTION"),
        secondary_collection=os.getenv("CHROMA_SECONDARY_COLLECTION"),
        secondary_dir=os.getenv("CHROMA_SECONDARY_DIR"),
        secondary_embed_model=os.getenv("CHROMA_SECONDARY_EMBED_MODEL"),
        feedback_collection=os.getenv("CHROMA_FEEDBACK_COLLECTION", "feedback_qa_mxbai_embed_large"),
        additional_collections=os.getenv("CHROMA_ADDITIONAL_COLLECTIONS", ""),
        exclude_collections=os.getenv("CHROMA_EXCLUDE_COLLECTIONS", ""),
    )

    doc_chunk = ingest_cfg.get("documents", {})
    chunking = ChunkingSettings(
        chunk_size=int(env("CHUNK_SIZE", doc_chunk.get("chunk_size"), 500, cast=str)),
        chunk_overlap=int(env("CHUNK_OVERLAP", doc_chunk.get("chunk_overlap"), 100, cast=str)),
        pdf_chunk_size=int(env("PDF_CHUNK_SIZE", 500, cast=str)),
        pdf_chunk_overlap=int(env("PDF_CHUNK_OVERLAP", 100, cast=str)),
        code_chunk_size=int(env("CODE_CHUNK_SIZE", 500, cast=str)),
        code_chunk_overlap=int(env("CODE_CHUNK_OVERLAP", 100, cast=str)),
        max_final_chunk_size=int(env("MAX_FINAL_CHUNK_SIZE", 1500, cast=str)),
    )

    documents_root = env("DOCUMENTS_ROOT", "/app/public/documents")
    paths = PathSettings(
        documents_root=documents_root,
        docs_base_url=env("DOCS_BASE_URL", "/public"),
        local_docs_root=os.getenv("LOCAL_DOCS_ROOT"),
        repo_docs_root=env("REPO_DOCS_ROOT", "/app/docs"),
        org_repo_root=os.getenv("ORG_REPO_ROOT"),
        spec_src_root=env("SPEC_SRC_ROOT", "/tmp/specs"),
        spec_static_root=os.getenv("SPEC_STATIC_ROOT"),
        spec_ingest_root=os.getenv("SPEC_INGEST_ROOT"),
        spl_docs_root=os.getenv("SPL_DOCS_ROOT"),
        cribl_docs_root=os.getenv("CRIBL_DOCS_ROOT"),
        feedback_root=os.getenv("FEEDBACK_ROOT"),
        specs_public_path=env("SPECS_PUBLIC_PATH", "/public/ingest_specs"),
        blob_storage_path=env("BLOB_STORAGE_PATH", "/app/.chainlit/blobs"),
    )

    splunk = SplunkSettings(
        host=os.getenv("SPLUNK_HOST"),
        port=int(env("SPLUNK_PORT", 8089, cast=str)),
        username=os.getenv("SPLUNK_USERNAME"),
        password=os.getenv("SPLUNK_PASSWORD"),
        token=os.getenv("SPLUNK_TOKEN"),
        verify_ssl=envbool("SPLUNK_VERIFY", True),
        validator_host=env("SPLUNK_VALIDATOR_HOST", "localhost"),
        validator_port=int(env("SPLUNK_VALIDATOR_PORT", 8089, cast=str)),
        validator_user=env("SPLUNK_VALIDATOR_USER", "admin"),
        validator_pass=env("SPLUNK_VALIDATOR_PASS", ""),
    )

    cribl_cfg = cfg.get("cribl", {})
    cribl = CriblSettings(
        base_url=env("CRIBL_BASE_URL", cribl_cfg.get("base_url"), ""),
        auth_token=env("CRIBL_AUTH_TOKEN", cribl_cfg.get("auth_token"), ""),
        username=env("CRIBL_USERNAME", cribl_cfg.get("username"), ""),
        password=env("CRIBL_PASSWORD", cribl_cfg.get("password"), ""),
        verify_ssl=envbool("CRIBL_VERIFY_SSL", cribl_cfg.get("verify_ssl", True)),
        default_group=env("CRIBL_DEFAULT_GROUP", cribl_cfg.get("default_group"), "default"),
    )

    _default_opt_url = "http://localhost:9005"
    search_optimizer = SearchOptimizerSettings(
        url=env("SEARCH_OPT_URL", _default_opt_url),
        enabled=envbool("SEARCH_OPT_ENABLED", True),
        data_dir=env("SEARCH_OPT_DATA_DIR", "/app/data"),
        auto_analyze=envbool("AUTO_ANALYZE", True),
    )

    auth_cfg = cfg.get("auth", {})
    auth = AuthSettings(
        enabled=envbool("ENABLE_AUTHENTICATION", True),
        admin_user=env("ADMIN_USER", "admin"),
        admin_password=env("ADMIN_PASSWORD", ""),
        providers=auth_cfg.get("providers", []),
    )

    rate_limit = RateLimitSettings(
        global_rate=float(env("RATE_LIMIT_GLOBAL", sec_cfg.get("max_queries_per_minute"), 10, cast=str)),
        user_rate=float(env("RATE_LIMIT_USER", 2, cast=str)),
    )

    retrieval_cfg = cfg.get("retrieval", {})
    retrieval = RetrievalSettings(
        top_k=retrieval_cfg.get("top_k", {"feedback": 3, "specs": 5, "primary": 5}),
        similarity_threshold=retrieval_cfg.get("similarity_threshold", {"feedback": 0.7, "specs": 0.6, "primary": 0.6}),
        strategy=retrieval_cfg.get("strategy", "multi_collection"),
        k_multiplier=int(env("K_MULTIPLIER", retrieval_cfg.get("k_multiplier"), 3, cast=str)),
    )

    spl_validation = SPLValidationSettings(
        safe_time_range=int(env("SPL_SAFE_TIME_RANGE", 604800, cast=str)),
        block_threshold=int(env("SPL_BLOCK_THRESHOLD", 80, cast=str)),
    )

    orch_cfg = cfg.get("orchestration", {})
    orchestration = OrchestrationSettings(
        default_strategy=env("ORCHESTRATION_STRATEGY", orch_cfg.get("default_strategy"), "adaptive"),
        max_iterations=int(env("ORCH_MAX_ITERATIONS", orch_cfg.get("max_iterations"), 3, cast=str)),
        max_parallel_agents=int(env("ORCH_MAX_PARALLEL", orch_cfg.get("max_parallel_agents"), 3, cast=str)),
        quality_threshold=float(env("ORCH_QUALITY_THRESHOLD", orch_cfg.get("quality_threshold"), 0.7, cast=str)),
        max_duration_seconds=float(env("ORCH_MAX_DURATION", orch_cfg.get("max_duration_seconds"), 30.0, cast=str)),
        resource_fallback=envbool("ORCH_RESOURCE_FALLBACK", orch_cfg.get("resource_fallback", True)),
        critic_enabled=envbool("ORCH_CRITIC_ENABLED", orch_cfg.get("critic_enabled", True)),
        human_approval_intents=orch_cfg.get("human_approval_intents", []),
        strategy_overrides=orch_cfg.get("strategy_overrides", {}),
    )

    docling_cfg = cfg.get("docling", {})
    docling = DoclingSettings(
        enabled=envbool("DOCLING_ENABLED", docling_cfg.get("enabled", False)),
        base_url=env("DOCLING_URL", docling_cfg.get("base_url"), "http://127.0.0.1:5001"),
        timeout=int(env("DOCLING_TIMEOUT", docling_cfg.get("timeout"), 300, cast=str)),
        ocr_enabled=envbool("DOCLING_OCR_ENABLED", docling_cfg.get("ocr_enabled", False)),
        extract_tables=docling_cfg.get("extract_tables", True),
        chunk_tokens=int(env("DOCLING_CHUNK_TOKENS", docling_cfg.get("chunk_tokens"), 250, cast=str)),
        max_doc_size_mb=int(env("DOCLING_MAX_SIZE_MB", docling_cfg.get("max_doc_size_mb"), 100, cast=str)),
    )

    sb_cfg = cfg.get("splunkbase_catalog", {})
    splunkbase_catalog = SplunkbaseCatalogSettings(
        enabled=envbool("SPLUNKBASE_CATALOG_ENABLED", sb_cfg.get("enabled", False)),
        catalog_path=env("SPLUNKBASE_CATALOG_PATH", sb_cfg.get("catalog_path"), "/app/data/splunkbase_catalog.json"),
        update_schedule=env("SPLUNKBASE_UPDATE_SCHEDULE", sb_cfg.get("update_schedule"), "weekly"),
        splunk_url=env("SPLUNKBASE_SPLUNK_URL", sb_cfg.get("splunk_url"), ""),
        splunk_token=env("SPLUNKBASE_SPLUNK_TOKEN", sb_cfg.get("splunk_token"), ""),
        max_apps_per_fetch=int(env("SPLUNKBASE_MAX_APPS", sb_cfg.get("max_apps_per_fetch"), 100, cast=str)),
        include_private=envbool("SPLUNKBASE_INCLUDE_PRIVATE", sb_cfg.get("include_private", False)),
        auto_compare=envbool("SPLUNKBASE_AUTO_COMPARE", sb_cfg.get("auto_compare", True)),
    )

    return Settings(
        app=app,
        ui=ui,
        database=database,
        ollama=ollama,
        chroma=chroma,
        cache=CacheSettings(
            enabled=envbool("ENABLE_CACHE", False),
            host=env("REDIS_HOST", "127.0.0.1"),
            port=int(env("REDIS_PORT", 6379, cast=str)),
            password=os.getenv("REDIS_PASSWORD"),
            ttl=int(env("CACHE_TTL", 3600, cast=str)),
            salt=env("CACHE_SALT", "chainlit-salt"),
        ),
        chunking=chunking,
        paths=paths,
        splunk=splunk,
        cribl=cribl,
        search_optimizer=search_optimizer,
        auth=auth,
        rate_limit=rate_limit,
        spl_validation=spl_validation,
        retrieval=retrieval,
        ingestion=IngestionSettings(
            spec_chunk_size=int(ingest_cfg.get("spec_files", {}).get("chunk_size", 800)),
            spec_chunk_overlap=int(ingest_cfg.get("spec_files", {}).get("chunk_overlap", 200)),
            doc_chunk_size=int(ingest_cfg.get("documents", {}).get("chunk_size", 900)),
            doc_chunk_overlap=int(ingest_cfg.get("documents", {}).get("chunk_overlap", 400)),
            max_workers=int(cfg.get("ingestion", {}).get("performance", {}).get("max_workers", 4)),
            batch_size=int(cfg.get("ingestion", {}).get("performance", {}).get("batch_size", 1000)),
            max_file_size_mb=int(cfg.get("ingestion", {}).get("performance", {}).get("max_file_size_mb", 50)),
            skip_dedup=cfg.get("ingestion", {}).get("performance", {}).get("skip_dedup", False),
            force_reindex=cfg.get("ingestion", {}).get("performance", {}).get("force_reindex", False),
        ),
        security=SecuritySettings(
            rate_limiting_enabled=sec_cfg.get("enabled", True),
            max_queries_per_minute=int(sec_cfg.get("max_queries_per_minute", 10)),
            max_queries_per_hour=int(sec_cfg.get("max_queries_per_hour", 100)),
            cors_enabled=cfg.get("security", {}).get("cors", {}).get("enabled", True),
            cors_allowed_origins=cfg.get("security", {}).get("cors", {}).get("allowed_origins", [
                "https://localhost:8000", "https://127.0.0.1:8000"
            ]),
        ),
        orchestration=orchestration,
        docling=docling,
        splunkbase_catalog=splunkbase_catalog,
        knowledge_graph=KnowledgeGraphSettings(
            enabled=envbool("KG_ENABLED", cfg.get("knowledge_graph", {}).get("enabled", True)),
            cache_path=env("KG_CACHE_PATH", cfg.get("knowledge_graph", {}).get("cache_path"), "/app/data/knowledge_graph.json"),
            max_context_facts=int(env("KG_MAX_FACTS", cfg.get("knowledge_graph", {}).get("max_context_facts"), 8, cast=str)),
            max_query_depth=int(env("KG_MAX_DEPTH", cfg.get("knowledge_graph", {}).get("max_query_depth"), 2, cast=str)),
            rebuild_on_startup=envbool("KG_REBUILD", cfg.get("knowledge_graph", {}).get("rebuild_on_startup", False)),
            spl_docs_dir=env("KG_SPL_DOCS_DIR", cfg.get("knowledge_graph", {}).get("spl_docs_dir"), "/app/shared/public/documents/commands"),
            metadata_dir=env("KG_METADATA_DIR", cfg.get("knowledge_graph", {}).get("metadata_dir"), "/app/metadata"),
            spec_dir=env("KG_SPEC_DIR", cfg.get("knowledge_graph", {}).get("spec_dir"), "/app/shared/public/documents/specs"),
        ),
        github=GitHubSettings(
            repo_url=env("GITHUB_REPO_URL",
                         cfg.get("github", {}).get("repo_url", ""),
                         "https://github.com/obsai-project/obs-ai"),
            repo_owner=env("GITHUB_REPO_OWNER",
                           cfg.get("github", {}).get("repo_owner", ""),
                           "obsai-project"),
            repo_name=env("GITHUB_REPO_NAME",
                          cfg.get("github", {}).get("repo_name", ""),
                          "chainlit"),
            token=os.getenv("GITHUB_TOKEN"),
            check_interval_hours=int(
                env("VERSION_CHECK_INTERVAL",
                    cfg.get("github", {}).get("version_check_interval_hours") or 24,
                    24)),
        ),
        organization=OrganizationSettings(
            config_paths=cfg.get("organization", {}).get("config_paths", ["documents/repo/splunk/", "ingest_specs/"]),
            index_mappings=cfg.get("organization", {}).get("index_mappings", {}),
            field_mappings=cfg.get("organization", {}).get("field_mappings", {}),
        ),
        mcp_gateway=MCPGatewaySettings(
            enabled=cfg.get("mcp_gateway", {}).get("enabled", True),
            connection_timeout=int(cfg.get("mcp_gateway", {}).get("connection_timeout", 30)),
            max_retries=int(cfg.get("mcp_gateway", {}).get("max_retries", 2)),
            servers=cfg.get("mcp_gateway", {}).get("servers", []),
        ),
        sharepoint=SharePointSettings(
            enabled=envbool("SHAREPOINT_ENABLED", cfg.get("sharepoint", {}).get("enabled", False)),
            tenant_id=env("SHAREPOINT_TENANT_ID", cfg.get("sharepoint", {}).get("tenant_id"), ""),
            client_id=env("SHAREPOINT_CLIENT_ID", cfg.get("sharepoint", {}).get("client_id"), ""),
            client_secret=env("SHAREPOINT_CLIENT_SECRET", cfg.get("sharepoint", {}).get("client_secret"), ""),
            site_url=env("SHAREPOINT_SITE_URL", cfg.get("sharepoint", {}).get("site_url"), ""),
            ingestion=SharePointIngestionSettings(
                include_libraries=cfg.get("sharepoint", {}).get("ingestion", {}).get("include_libraries", []),
                exclude_libraries=cfg.get("sharepoint", {}).get("ingestion", {}).get("exclude_libraries",
                                                                                      ["Form Templates", "Site Assets", "Style Library"]),
                max_docs_per_library=cfg.get("sharepoint", {}).get("ingestion", {}).get("max_docs_per_library"),
                sync_schedule=cfg.get("sharepoint", {}).get("ingestion", {}).get("sync_schedule", "0 2 * * *"),
                incremental=cfg.get("sharepoint", {}).get("ingestion", {}).get("incremental", True),
            ),
            collection_name=cfg.get("sharepoint", {}).get("collection", {}).get("name", "sharepoint_docs"),
            collection_description=cfg.get("sharepoint", {}).get("collection", {}).get("description", "SharePoint document library content"),
        ),
        github_ingestion=GitHubIngestionSettings(
            enabled=envbool("GITHUB_INGESTION_ENABLED", cfg.get("github", {}).get("enabled", False)),
            repo_url=env("GITHUB_INGESTION_REPO_URL", cfg.get("github", {}).get("repo_url"), ""),
            token=env("GITHUB_INGESTION_TOKEN", cfg.get("github", {}).get("token")),
            branches=cfg.get("github", {}).get("branches", ["main", "develop"]),
            include_patterns=cfg.get("github", {}).get("include_patterns", ["*.md", "*.py", "*.yml", "*.yaml", "*.json"]),
            exclude_patterns=cfg.get("github", {}).get("exclude_patterns", ["node_modules/**", "venv/**", "*.pyc", "__pycache__/**"]),
            sync_schedule=cfg.get("github", {}).get("ingestion", {}).get("sync_schedule", "0 */4 * * *"),
            incremental=cfg.get("github", {}).get("ingestion", {}).get("incremental", True),
            collection_name=cfg.get("github", {}).get("collection", {}).get("name", "github_repo"),
            collection_description=cfg.get("github", {}).get("collection", {}).get("description", "GitHub repository content"),
        ),
        langfuse=LangfuseSettings(
            enabled=envbool("LANGFUSE_ENABLED", cfg.get("langfuse", {}).get("enabled", False)),
            host=env("LANGFUSE_HOST", cfg.get("langfuse", {}).get("host"), "http://langfuse_api:3200"),
            public_key=env("LANGFUSE_PUBLIC_KEY", cfg.get("langfuse", {}).get("public_key"), ""),
            secret_key=env("LANGFUSE_SECRET_KEY", cfg.get("langfuse", {}).get("secret_key"), ""),
        ),
        otel=OtelSettings(
            enabled=envbool("OTEL_TRACING_ENABLED", cfg.get("otel", {}).get("enabled", True)),
            endpoint=env("OTEL_EXPORTER_OTLP_ENDPOINT", cfg.get("otel", {}).get("endpoint"), ""),
            service_name=env("OTEL_SERVICE_NAME", cfg.get("otel", {}).get("service_name"), "obsai-app"),
            console_export=envbool("OTEL_TRACE_CONSOLE", cfg.get("otel", {}).get("console_export", False)),
            max_spans=int(env("OTEL_MAX_SPANS", cfg.get("otel", {}).get("max_spans"), 500, cast=str)),
        ),
        retention=RetentionSettings(
            chat_history_days=int(cfg.get("retention", {}).get("chat_history_days", 90)),
            feedback_days=int(cfg.get("retention", {}).get("feedback_days", 365)),
            learned_qa_days=int(cfg.get("retention", {}).get("learned_qa_days", 0)),
            audit_log_days=int(cfg.get("retention", {}).get("audit_log_days", 365)),
            execution_journal_days=int(cfg.get("retention", {}).get("execution_journal_days", 30)),
            pipeline_traces_days=int(cfg.get("retention", {}).get("pipeline_traces_days", 14)),
        ),
        idle_worker=IdleWorkerSettings(
            enabled=envbool("IDLE_WORKER_ENABLED", cfg.get("idle_worker", {}).get("enabled", True)),
            idle_threshold_seconds=int(env("IDLE_WORKER_THRESHOLD", cfg.get("idle_worker", {}).get("idle_threshold_seconds"), 60, cast=str)),
            min_cycle_interval=int(env("IDLE_WORKER_CYCLE_INTERVAL", cfg.get("idle_worker", {}).get("min_cycle_interval"), 300, cast=str)),
            max_tasks_per_cycle=int(env("IDLE_WORKER_MAX_TASKS", cfg.get("idle_worker", {}).get("max_tasks_per_cycle"), 12, cast=str)),
            config_drift_interval=int(cfg.get("idle_worker", {}).get("config_drift_interval", 300)),
            collection_freshness_interval=int(cfg.get("idle_worker", {}).get("collection_freshness_interval", 600)),
            pipeline_quality_interval=int(cfg.get("idle_worker", {}).get("pipeline_quality_interval", 900)),
            max_results_history=int(cfg.get("idle_worker", {}).get("max_results_history", 200)),
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    Built once, cached forever.  To reload (e.g., in tests), call
    ``get_settings.cache_clear()`` first.
    """
    settings = _build_settings()
    logger.info(
        "Settings loaded: profile=%s model=%s base_url=%s",
        settings.app.active_profile,
        settings.ollama.model,
        settings.ollama.base_url,
    )
    return settings


def reload_settings() -> Settings:
    """Force-reload settings (clears cache and rebuilds)."""
    get_settings.cache_clear()
    return get_settings()
