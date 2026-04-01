"""
Pydantic model definitions for application settings.

All BaseModel subclasses that make up the Settings object.
Imported by settings.py which handles config loading and get_settings().
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# Placeholder URL patterns that indicate unconfigured integrations
_PLACEHOLDER_PATTERNS = ("placeholder", "example.com", "yourorg", "yourrepo", "yourcompany")


def _is_placeholder_url(url: str) -> bool:
    """Return True if the URL is empty or contains a placeholder pattern."""
    if not url or not url.strip():
        return True
    url_lower = url.lower()
    return any(p in url_lower for p in _PLACEHOLDER_PATTERNS)


class DatabaseSettings(BaseModel):
    """PostgreSQL connection settings."""

    url: str = Field(default="", description="Async connection string (asyncpg).")

    @model_validator(mode="before")
    @classmethod
    def _resolve_url(cls, values: Any) -> Any:
        if isinstance(values, dict) and not values.get("url"):
            values["url"] = (
                os.getenv("CHAINLIT_DB_CONNINFO")
                or os.getenv("DATABASE_URL")
                or ""
            )
        return values


class OllamaSettings(BaseModel):
    """Ollama LLM settings."""

    base_url: str = "http://127.0.0.1:11430"
    model: str = "qwen2.5:3b"
    embed_model: str = "mxbai-embed-large"
    temperature: float = 0.01
    num_ctx: int = 2048
    num_predict: int = 1024  # Max response tokens — caps generation time
    spl_model: Optional[str] = None
    spl_temperature: float = 0.05
    spl_num_predict: int = 512
    timeout: int = 90  # LLM response timeout in seconds

    @model_validator(mode="before")
    @classmethod
    def _resolve_ollama(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        # base_url: env > yaml > default
        if not values.get("base_url"):
            values["base_url"] = (
                os.getenv("OLLAMA_BASE_URL")
                or os.getenv("OLLAMA_HOST")
                or "http://127.0.0.1:11430"
            )
        return values


class ChromaSettings(BaseModel):
    """ChromaDB vector store settings."""

    dir: str = "/app/chroma_store"
    http_url: str = "http://127.0.0.1:8001"
    secondary_http_url: Optional[str] = None
    collection: Optional[str] = None
    secondary_collection: Optional[str] = None
    secondary_dir: Optional[str] = None
    secondary_embed_model: Optional[str] = None
    feedback_collection: Optional[str] = None
    additional_collections: str = ""
    exclude_collections: str = ""

    @model_validator(mode="before")
    @classmethod
    def _resolve_chroma(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        if not values.get("secondary_http_url"):
            values["secondary_http_url"] = (
                os.getenv("CHROMA_SECONDARY_HTTP_URL")
                or values.get("http_url")
                or os.getenv("CHROMA_HTTP_URL")
                or "http://127.0.0.1:8001"
            )
        return values


class CacheSettings(BaseModel):
    """Redis caching settings."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 6379
    password: Optional[str] = None
    ttl: int = 3600
    prompt_ttl: int = 300  # TTL for assembled prompt cache (seconds)
    salt: str = "chainlit-salt"


class RetentionSettings(BaseModel):
    """Data retention policies for various subsystems.

    A value of 0 means permanent (no expiry).
    """

    chat_history_days: int = 90
    feedback_days: int = 365
    learned_qa_days: int = 0  # 0 = permanent
    audit_log_days: int = 365
    execution_journal_days: int = 30
    pipeline_traces_days: int = 14


class JournalSettings(BaseModel):
    """Persistent execution journal settings."""

    enabled: bool = True
    base_dir: str = "/app/data/execution_logs"
    retention_days: int = 30
    flush_interval: float = 5.0


class ChunkingSettings(BaseModel):
    """Text chunking configuration."""

    chunk_size: int = 500
    chunk_overlap: int = 100
    pdf_chunk_size: int = 500
    pdf_chunk_overlap: int = 100
    code_chunk_size: int = 500
    code_chunk_overlap: int = 100
    chat_chunk_size: Optional[int] = None
    chat_chunk_overlap: Optional[int] = None
    max_final_chunk_size: int = 1500
    # Token-based chunking (used by smart_chunker)
    smart_chunk_tokens: int = 250
    smart_chunk_overlap_tokens: int = 40
    # Conf/spec file chunking (stanza-aware)
    # Must stay under mxbai-embed-large's 512 token limit (~2048 chars)
    conf_max_chunk_size: int = 1200
    conf_chunk_overlap: int = 150

    @model_validator(mode="after")
    def _defaults(self) -> "ChunkingSettings":
        if self.chat_chunk_size is None:
            self.chat_chunk_size = self.code_chunk_size
        if self.chat_chunk_overlap is None:
            self.chat_chunk_overlap = self.code_chunk_overlap
        return self


class PathSettings(BaseModel):
    """Document and directory paths."""

    documents_root: str = "/app/public/documents"
    docs_base_url: str = "/public"
    local_docs_root: Optional[str] = None
    repo_docs_root: str = "/app/docs"
    org_repo_root: Optional[str] = None
    spec_src_root: str = "/tmp/specs"
    spec_static_root: Optional[str] = None
    spec_ingest_root: Optional[str] = None
    spl_docs_root: Optional[str] = None
    cribl_docs_root: Optional[str] = None
    feedback_root: Optional[str] = None
    specs_public_path: str = "/public/ingest_specs"
    blob_storage_path: str = "/app/.chainlit/blobs"

    @model_validator(mode="after")
    def _computed_paths(self) -> "PathSettings":
        root = self.documents_root
        if self.local_docs_root is None:
            self.local_docs_root = f"{root}/pdfs"
        if self.org_repo_root is None:
            self.org_repo_root = f"{root}/repo"
        if self.spec_static_root is None:
            self.spec_static_root = f"{root}/specs"
        if self.spec_ingest_root is None:
            self.spec_ingest_root = f"{root}/specs"
        if self.spl_docs_root is None:
            self.spl_docs_root = f"{root}/commands"
        if self.cribl_docs_root is None:
            self.cribl_docs_root = f"{root}/cribl"
        if self.feedback_root is None:
            self.feedback_root = f"{root}/feedback"
        self.docs_base_url = self.docs_base_url.rstrip("/")
        return self


class CriblSettings(BaseModel):
    """Cribl Stream API connection settings."""

    base_url: str = ""
    auth_token: str = ""
    username: str = ""
    password: str = ""
    verify_ssl: bool = True
    default_group: str = "default"

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url) and (bool(self.auth_token) or (bool(self.username) and bool(self.password)))


class SplunkSettings(BaseModel):
    """Splunk API connection settings."""

    host: Optional[str] = None
    port: int = 8089
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    verify_ssl: bool = True
    splunk_verify_ssl: bool = True
    splunk_ca_bundle: str = ""  # Path to CA bundle file

    # Splunk validator (sidecar container)
    validator_host: str = "localhost"
    validator_port: int = 8089
    validator_user: str = "admin"
    validator_pass: str = ""

    def get_ssl_verify(self):
        """Return verify parameter for requests: ca_bundle path if set, else bool."""
        if self.splunk_ca_bundle:
            return self.splunk_ca_bundle
        return self.splunk_verify_ssl

    @property
    def is_configured(self) -> bool:
        return bool(self.host) and (bool(self.token) or (bool(self.username) and bool(self.password)))


class SearchOptimizerSettings(BaseModel):
    """Search optimizer microservice settings."""

    url: str = "http://127.0.0.1:9005"
    enabled: bool = True
    data_dir: str = "/app/data"
    auto_analyze: bool = True


class IngestionSettings(BaseModel):
    """Ingestion pipeline settings (maps to config.yaml ingestion section)."""

    spec_chunk_size: int = 800
    spec_chunk_overlap: int = 200
    doc_chunk_size: int = 900
    doc_chunk_overlap: int = 400
    max_workers: int = 4
    batch_size: int = 1000
    max_file_size_mb: int = 50
    skip_dedup: bool = False
    force_reindex: bool = False


class SecuritySettings(BaseModel):
    """Security settings (maps to config.yaml security section)."""

    rate_limiting_enabled: bool = True
    max_queries_per_minute: int = 10
    max_queries_per_hour: int = 100
    cors_enabled: bool = True
    cors_allowed_origins: List[str] = ["https://localhost:8000", "https://127.0.0.1:8000"]


class OrganizationSettings(BaseModel):
    """Organization-specific config (maps to config.yaml organization section)."""

    config_paths: List[str] = ["documents/repo/splunk/", "ingest_specs/"]
    index_mappings: Dict[str, str] = {}
    field_mappings: Dict[str, str] = {}


class MCPGatewaySettings(BaseModel):
    """MCP gateway settings (maps to config.yaml mcp_gateway section)."""

    enabled: bool = True
    connection_timeout: int = 30
    max_retries: int = 2
    servers: List[Dict[str, Any]] = []


class AuthSettings(BaseModel):
    """Authentication and security settings."""

    enabled: bool = True
    admin_user: str = "admin"
    admin_password: str = ""
    providers: List[Dict[str, Any]] = Field(default_factory=list)


class GitHubSettings(BaseModel):
    """GitHub repository settings for version checking and upgrades."""

    repo_url: str = "https://github.com/obsai-project/obs-ai"
    repo_owner: str = "obsai-project"
    repo_name: str = "chainlit"
    token: Optional[str] = None
    check_interval_hours: int = 24


class SharePointIngestionSettings(BaseModel):
    """SharePoint ingestion sub-settings."""

    include_libraries: List[str] = Field(default_factory=list)
    exclude_libraries: List[str] = Field(default_factory=lambda: ["Form Templates", "Site Assets", "Style Library"])
    max_docs_per_library: Optional[int] = None
    sync_schedule: str = "0 2 * * *"
    incremental: bool = True


class SharePointSettings(BaseModel):
    """SharePoint integration settings (maps to config.yaml sharepoint section)."""

    enabled: bool = False
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    site_url: str = ""
    ingestion: SharePointIngestionSettings = Field(default_factory=SharePointIngestionSettings)
    collection_name: str = "sharepoint_docs"
    collection_description: str = "SharePoint document library content"

    @model_validator(mode="after")
    def _disable_on_placeholder(self) -> "SharePointSettings":
        """Force enabled=False when site_url contains placeholder values."""
        if self.enabled and _is_placeholder_url(self.site_url):
            logger.warning(
                "SharePoint disabled: site_url is empty or contains a placeholder value (%r)",
                self.site_url,
            )
            self.enabled = False
        return self


class GitHubIngestionSettings(BaseModel):
    """GitHub repository ingestion settings (maps to config.yaml github section)."""

    enabled: bool = False
    repo_url: str = ""
    token: Optional[str] = None
    branches: List[str] = Field(default_factory=lambda: ["main", "develop"])
    include_patterns: List[str] = Field(default_factory=lambda: ["*.md", "*.py", "*.yml", "*.yaml", "*.json"])
    exclude_patterns: List[str] = Field(default_factory=lambda: ["node_modules/**", "venv/**", "*.pyc", "__pycache__/**"])
    sync_schedule: str = "0 */4 * * *"
    incremental: bool = True
    collection_name: str = "github_repo"
    collection_description: str = "GitHub repository content"

    @model_validator(mode="after")
    def _disable_on_placeholder(self) -> "GitHubIngestionSettings":
        """Force enabled=False when repo_url contains placeholder values."""
        if self.enabled and _is_placeholder_url(self.repo_url):
            logger.warning(
                "GitHub ingestion disabled: repo_url is empty or contains a placeholder value (%r)",
                self.repo_url,
            )
            self.enabled = False
        return self


class RateLimitSettings(BaseModel):
    """Rate limiting configuration."""

    global_rate: float = 10.0
    user_rate: float = 2.0


class SPLValidationSettings(BaseModel):
    """SPL validation thresholds."""

    safe_time_range: int = 604800  # 7 days
    block_threshold: int = 80


class RetrievalSettings(BaseModel):
    """Retrieval settings."""

    top_k: Dict[str, int] = {"feedback": 3, "specs": 5, "primary": 5}
    similarity_threshold: Dict[str, float] = {"feedback": 0.7, "specs": 0.6, "primary": 0.6}
    strategy: str = "multi_collection"
    k_multiplier: int = 3


class SSLSettings(BaseModel):
    """SSL/TLS configuration."""

    enabled: bool = False
    cert_file: str = ""
    key_file: str = ""
    ca_file: str = ""


class UISettings(BaseModel):
    """UI framework selection."""

    framework: str = "chainlit"  # "chainlit" or "open-webui"
    ssl: SSLSettings = SSLSettings()


class LearningSettings(BaseModel):
    """Self-learning pipeline settings."""

    enabled: bool = True
    qa_generation_enabled: bool = True
    reassessment_enabled: bool = True
    fact_learning_enabled: bool = True
    daily_learning_cycle: bool = True
    max_qa_pairs_per_cycle: int = 500
    reassessment_limit: int = 20
    min_episodes_for_facts: int = 3
    cross_collection_consolidation: bool = True
    consolidation_max_insights: int = 50
    consolidation_interval_hours: int = 24


class KnowledgeGraphSettings(BaseModel):
    """Knowledge graph configuration."""

    enabled: bool = True
    cache_path: str = "/app/data/knowledge_graph.json"
    max_context_facts: int = 8
    max_query_depth: int = 2
    rebuild_on_startup: bool = False
    spl_docs_dir: str = "/app/shared/public/documents/commands"
    metadata_dir: str = "/app/metadata"
    spec_dir: str = "/app/shared/public/documents/specs"


class OrchestrationSettings(BaseModel):
    """Multi-agent orchestration strategy configuration."""

    default_strategy: str = "adaptive"
    max_iterations: int = 3
    max_parallel_agents: int = 3
    quality_threshold: float = 0.7
    max_duration_seconds: float = 30.0
    resource_fallback: bool = True
    critic_enabled: bool = True
    human_approval_intents: List[str] = Field(default_factory=list)
    strategy_overrides: Dict[str, str] = Field(default_factory=lambda: {
        "spl_generation": "single_agent",
        "spl_optimization": "single_agent",
        "spl_explanation": "single_agent",
        "spl_validation": "single_agent",
        "general_qa": "single_agent",
        "greeting": "single_agent",
        "command_help": "single_agent",
    })

    @field_validator("default_strategy")
    @classmethod
    def _validate_strategy(cls, v: str) -> str:
        valid = {
            "single_agent", "parallel", "hierarchical", "iterative",
            "coordinator", "voting", "react", "review_critique",
            "workflow", "swarm", "human_in_loop", "adaptive",
            "democratic", "capitalist", "authoritarian", "parliament", "meritocratic",
            "supervisor",
            "two_stage_pipeline", "action_engine", "director_graph", "feedback_loop",
        }
        if v not in valid:
            raise ValueError(f"Unknown strategy '{v}'. Valid: {sorted(valid)}")
        return v

    @field_validator("quality_threshold")
    @classmethod
    def _validate_threshold(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("quality_threshold must be between 0.0 and 1.0")
        return v


class DoclingSettings(BaseModel):
    """Docling document conversion settings."""

    enabled: bool = False
    base_url: str = "http://127.0.0.1:5001"
    timeout: int = 300
    ocr_enabled: bool = False
    extract_tables: bool = True
    chunk_tokens: int = 250
    overlap_tokens: int = 40
    max_doc_size_mb: int = 100


class SplunkbaseCatalogSettings(BaseModel):
    """Splunkbase add-on version validator settings."""

    enabled: bool = True
    catalog_path: str = "/app/data/splunkbase_catalog.json"
    update_schedule: str = "daily"  # daily, weekly, monthly
    splunk_url: str = ""  # user's Splunk management URL (e.g. https://splunk:8089)
    splunk_token: str = ""  # auth token for Splunk REST API
    max_apps_per_fetch: int = 0  # 0 = fetch all available apps
    include_private: bool = False
    auto_compare: bool = True  # auto-compare on catalog update

    @field_validator("update_schedule")
    @classmethod
    def _validate_schedule(cls, v: str) -> str:
        valid = {"daily", "weekly", "monthly"}
        if v not in valid:
            raise ValueError(f"Unknown schedule '{v}'. Valid: {sorted(valid)}")
        return v


class OtelSettings(BaseModel):
    """OpenTelemetry distributed tracing settings."""

    enabled: bool = True
    endpoint: str = ""  # OTLP endpoint (e.g. http://jaeger:4317)
    service_name: str = "obsai-app"
    console_export: bool = False
    max_spans: int = 500  # In-memory span buffer for admin API


class LangfuseSettings(BaseModel):
    """Langfuse LLM observability settings.

    DEPRECATED: Langfuse has been replaced by OpenTelemetry (OtelSettings).
    This model is retained for backward compatibility with existing config.yaml
    files but is no longer used at runtime.
    """

    enabled: bool = False
    host: str = "http://localhost:3200"
    public_key: str = "pk-obsai-dev"
    secret_key: str = "sk-obsai-dev"


class IdleWorkerSettings(BaseModel):
    """Idle worker / smart job queue settings."""

    enabled: bool = True
    idle_threshold_seconds: int = 60
    min_cycle_interval: int = 300
    max_tasks_per_cycle: int = 12
    config_drift_interval: int = 300       # seconds between drift checks
    collection_freshness_interval: int = 600
    pipeline_quality_interval: int = 900
    max_results_history: int = 200         # max stored job results


class AppSettings(BaseModel):
    """General application settings."""

    log_level: str = "INFO"
    environment: str = "production"
    version: str = "3.5.1"
    active_profile: str = "LLM_LITE"
    org_name: str = "MY_ORG"
    org_full_name: str = "My Organization"


# Settings (top-level aggregator) is defined in settings.py to keep this
# file under 600 lines.  settings.py re-exports it here for backward compat.
