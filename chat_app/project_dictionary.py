"""Project Dictionary — comprehensive catalog of all system resources.

Single source of truth for every named entity in the system:
- Modules and their public APIs
- All API endpoints with methods and roles
- All MCP tools with schemas
- All skills and agents with metadata
- All slash commands
- All configuration sections
- All collections and their purposes
- All environment variables
- All external URLs and service endpoints

Usage:
    from chat_app.project_dictionary import get_project_dictionary

    d = get_project_dictionary()
    # Get any resource by category
    endpoints = d.get("api_endpoints")
    modules = d.get("modules")
    env_vars = d.get("environment_variables")

    # Full manifest
    manifest = d.build_manifest()
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Environment Variables Catalog
# ---------------------------------------------------------------------------

ENVIRONMENT_VARIABLES: List[Dict[str, str]] = [
    # Core
    {"name": "GATEWAY_PORT", "default": "8000", "description": "Nginx gateway published port", "category": "networking"},
    {"name": "APP_INTERNAL_PORT", "default": "8090", "description": "App internal listen port", "category": "networking"},
    {"name": "ENABLE_AUTHENTICATION", "default": "false", "description": "Enable login screen and JWT auth", "category": "security"},
    {"name": "ADMIN_USER", "default": "admin", "description": "Default admin username", "category": "security"},
    {"name": "ADMIN_PASSWORD", "default": "", "description": "Default admin password (hashed)", "category": "security"},
    {"name": "CHAINLIT_AUTH_SECRET", "default": "", "description": "JWT signing secret for Chainlit auth", "category": "security"},
    {"name": "JWT_SECRET", "default": "", "description": "JWT secret for token generation", "category": "security"},
    {"name": "SERVICE_API_KEY", "default": "", "description": "Service-to-service auth key (internal)", "category": "security"},
    {"name": "API_KEYS", "default": "", "description": "Comma-separated external API keys", "category": "security"},
    {"name": "MFA_POLICY", "default": "admin_required", "description": "MFA enforcement: disabled, optional, admin_required, all_required", "category": "security"},
    {"name": "SCIM_BEARER_TOKEN", "default": "", "description": "Bearer token for SCIM provisioning endpoints", "category": "security"},
    # Database
    {"name": "DATABASE_URL", "default": "postgresql+asyncpg://chainlit:chainlit@chat_db_app:5432/chainlit", "description": "PostgreSQL connection string", "category": "database"},
    {"name": "DATABASE_PASSWORD", "default": "chainlit", "description": "PostgreSQL password", "category": "database"},
    # LLM
    {"name": "OLLAMA_BASE_URL", "default": "http://llm_api_service:11430", "description": "Ollama API endpoint", "category": "llm"},
    {"name": "LLM_MODEL", "default": "llama3", "description": "Default LLM model name", "category": "llm"},
    {"name": "EMBEDDING_MODEL", "default": "mxbai-embed-large", "description": "Embedding model for vector search", "category": "llm"},
    # Vector Store
    {"name": "CHROMA_HTTP_URL", "default": "http://chat_chroma_db:8001", "description": "ChromaDB HTTP endpoint", "category": "retrieval"},
    {"name": "CHROMA_SERVER_HTTP_PORT", "default": "8001", "description": "ChromaDB listen port", "category": "retrieval"},
    # Cache
    {"name": "REDIS_HOST", "default": "redis_cache", "description": "Redis hostname", "category": "cache"},
    {"name": "REDIS_PORT", "default": "6379", "description": "Redis port", "category": "cache"},
    {"name": "REDIS_PASSWORD", "default": "", "description": "Redis password", "category": "cache"},
    # Splunk
    {"name": "SPLUNK_HOST", "default": "", "description": "Splunk management host", "category": "splunk"},
    {"name": "SPLUNK_PORT", "default": "8089", "description": "Splunk management port", "category": "splunk"},
    {"name": "SPLUNK_PASSWORD", "default": "", "description": "Splunk admin password", "category": "splunk"},
    {"name": "SPLUNK_HEC_TOKEN", "default": "", "description": "Splunk HEC token for event ingestion", "category": "splunk"},
    {"name": "SPLUNK_READ_TOKEN", "default": "", "description": "Splunk read-only token (least-privilege)", "category": "splunk"},
    {"name": "SPLUNK_WRITE_TOKEN", "default": "", "description": "Splunk write token (least-privilege)", "category": "splunk"},
    {"name": "SPLUNK_ADMIN_TOKEN", "default": "", "description": "Splunk admin token (least-privilege)", "category": "splunk"},
    # Monitoring
    {"name": "GF_SECURITY_ADMIN_PASSWORD", "default": "admin", "description": "Grafana admin password", "category": "monitoring"},
    # Organization
    {"name": "ORG_NAME", "default": "", "description": "Organization short name (overrides config.yaml)", "category": "organization"},
    {"name": "ORG_FULL_NAME", "default": "", "description": "Organization full name", "category": "organization"},
    # Data
    {"name": "AUDIT_LOG_DIR", "default": "/app/data/audit", "description": "Immutable audit log directory", "category": "data"},
    {"name": "RBAC_OVERRIDES_PATH", "default": "/app/data/rbac_overrides.json", "description": "Per-user RBAC overrides file", "category": "data"},
    {"name": "TENANTS_FILE", "default": "/app/data/tenants.json", "description": "Tenant definitions file", "category": "data"},
    {"name": "SCIM_USERS_FILE", "default": "/app/data/scim_users.json", "description": "SCIM provisioned users file", "category": "data"},
]


# ---------------------------------------------------------------------------
# Collections Catalog
# ---------------------------------------------------------------------------

COLLECTIONS: List[Dict[str, str]] = [
    {"name": "spl_docs", "description": "Splunk SPL command documentation (174 docs)", "type": "knowledge"},
    {"name": "org_configs", "description": "Organization Splunk configuration files (.conf)", "type": "knowledge"},
    {"name": "ingest_specs", "description": "Splunk .conf.spec reference files (68 specs)", "type": "knowledge"},
    {"name": "metadata", "description": "CIM reference, MLTK reference, RAG context, rules", "type": "knowledge"},
    {"name": "org_savedsearches", "description": "Organization saved searches and alerts", "type": "knowledge"},
    {"name": "org_macros", "description": "Organization search macros", "type": "knowledge"},
    {"name": "ingested_docs", "description": "User-ingested documents (PDFs, HTML, markdown)", "type": "user"},
    {"name": "self_learned_qa", "description": "Self-generated Q&A pairs from learning pipeline", "type": "learned"},
    {"name": "feedback_qa", "description": "User feedback polished into Q&A pairs", "type": "learned"},
    {"name": "cribl_docs", "description": "Cribl Stream documentation", "type": "knowledge"},
]


# ---------------------------------------------------------------------------
# Service Endpoints
# ---------------------------------------------------------------------------

SERVICE_ENDPOINTS: List[Dict[str, Any]] = [
    {"name": "App (Chainlit)", "internal_url": "http://chat_ui_app:8090", "container": "chat_ui_app", "port": 8090},
    {"name": "Nginx Gateway", "internal_url": "http://nginx_gateway:8000", "container": "nginx_gateway", "port": 8000, "published": True},
    {"name": "PostgreSQL", "internal_url": "postgresql://chat_db_app:5432", "container": "chat_db_app", "port": 5432},
    {"name": "ChromaDB", "internal_url": "http://chat_chroma_db:8001", "container": "chat_chroma_db", "port": 8001},
    {"name": "Ollama", "internal_url": "http://llm_api_service:11430", "container": "llm_api_service", "port": 11430},
    {"name": "Redis", "internal_url": "redis://redis_cache:6379", "container": "redis_cache", "port": 6379},
    {"name": "Search Optimizer", "internal_url": "http://search_opt_service:9005", "container": "search_opt_service", "port": 9005},
    {"name": "Prometheus", "internal_url": "http://prometheus_monitoring:9090", "container": "prometheus_monitoring", "port": 9090},
    {"name": "Grafana", "internal_url": "http://grafana_monitoring:3100", "container": "grafana_monitoring", "port": 3100},
]


# ---------------------------------------------------------------------------
# Module Catalog
# ---------------------------------------------------------------------------

def _get_module_catalog() -> List[Dict[str, Any]]:
    """Catalog all Python modules in chat_app/ with purpose and key exports."""
    modules = []
    chat_app_dir = Path(__file__).parent
    for py_file in sorted(chat_app_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        name = py_file.stem
        try:
            lines = py_file.read_text(encoding="utf-8", errors="ignore").split("\n")
            docstring = ""
            if lines and lines[0].startswith('"""'):
                end = next((i for i, l in enumerate(lines[1:], 1) if '"""' in l), 0)
                docstring = " ".join(lines[0:end + 1]).replace('"""', "").strip()[:200]
            line_count = len(lines)
        except Exception as _exc:  # broad catch — resilience against all failures
            docstring = ""
            line_count = 0

        modules.append({
            "name": name,
            "file": f"chat_app/{py_file.name}",
            "lines": line_count,
            "description": docstring,
        })
    return modules


# ---------------------------------------------------------------------------
# Project Dictionary
# ---------------------------------------------------------------------------

class ProjectDictionary:
    """Comprehensive catalog of all system resources."""

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._built_at: Optional[str] = None

    def get(self, category: str) -> Any:
        """Get a specific resource category."""
        manifest = self.build_manifest()
        return manifest.get(category)

    def build_manifest(self, force: bool = False) -> Dict[str, Any]:
        """Build the complete project manifest."""
        if self._cache and not force:
            return self._cache

        manifest = {
            "meta": {
                "project": "ObsAI",
                "version": self._get_version(),
                "built_at": datetime.now(timezone.utc).isoformat(),
                "description": "Observability AI Assistant for Splunk/Cribl administration",
            },
            "environment_variables": ENVIRONMENT_VARIABLES,
            "collections": COLLECTIONS,
            "service_endpoints": SERVICE_ENDPOINTS,
            "modules": _get_module_catalog(),
            "slash_commands": self._get_slash_commands(),
            "mcp_tools": self._get_mcp_tools(),
            "skills_summary": self._get_skills_summary(),
            "agents_summary": self._get_agents_summary(),
            "api_endpoints": self._get_api_endpoints(),
            "config_sections": self._get_config_sections(),
            "error_codes": self._get_error_codes(),
            "safety_levels": self._get_safety_levels(),
            "slo_definitions": self._get_slo_definitions(),
        }

        self._cache = manifest
        self._built_at = manifest["meta"]["built_at"]
        return manifest

    def _get_version(self) -> str:
        try:
            from chat_app.settings import get_settings
            return get_settings().app.version
        except Exception as _exc:  # broad catch — resilience against all failures
            return "unknown"

    def _get_slash_commands(self) -> List[Dict[str, str]]:
        try:
            from chat_app.registry import get_command_registry
            registry = get_command_registry()
            return [
                {"name": f"/{cmd.name}", "description": cmd.description, "category": cmd.category}
                for cmd in registry.values()
            ]
        except Exception as _exc:  # broad catch — resilience against all failures
            return []

    def _get_mcp_tools(self) -> List[Dict[str, Any]]:
        try:
            from chat_app.mcp_server_mode import MCP_TOOLS
            return [{"name": t["name"], "description": t["description"], "min_role": t["min_role"]}
                    for t in MCP_TOOLS]
        except Exception as _exc:  # broad catch — resilience against all failures
            return []

    def _get_skills_summary(self) -> Dict[str, Any]:
        try:
            from chat_app.skill_catalog import get_skill_catalog
            catalog = get_skill_catalog()
            skills = catalog.get_all_skills() if hasattr(catalog, "get_all_skills") else list(getattr(catalog, "skills", {}).values())
            families: Dict[str, int] = {}
            for s in skills:
                fam = getattr(s, "family", "unknown")
                fam_name = fam.value if hasattr(fam, "value") else str(fam)
                families[fam_name] = families.get(fam_name, 0) + 1
            return {"total": len(skills), "by_family": families}
        except Exception as _exc:  # broad catch — resilience against all failures
            return {"total": 0, "by_family": {}}

    def _get_agents_summary(self) -> Dict[str, Any]:
        try:
            from chat_app.agent_catalog import get_agent_catalog
            catalog = get_agent_catalog()
            agents = catalog.get_all_agents() if hasattr(catalog, "get_all_agents") else list(getattr(catalog, "agents", {}).values())
            depts: Dict[str, int] = {}
            for a in agents:
                dept = getattr(a, "department", "unknown")
                dept_name = dept.value if hasattr(dept, "value") else str(dept)
                depts[dept_name] = depts.get(dept_name, 0) + 1
            return {"total": len(agents), "by_department": depts}
        except Exception as _exc:  # broad catch — resilience against all failures
            return {"total": 0, "by_department": {}}

    def _get_api_endpoints(self) -> List[Dict[str, str]]:
        try:
            from chat_app.admin_api import router, public_router
            endpoints = []
            for r in list(router.routes) + list(public_router.routes):
                if hasattr(r, "methods") and hasattr(r, "path"):
                    methods = r.methods - {"HEAD"} if r.methods else set()
                    for m in sorted(methods):
                        endpoints.append({"method": m, "path": r.path,
                                          "summary": getattr(r, "summary", "") or getattr(r, "name", "")})
            return sorted(endpoints, key=lambda x: x["path"])
        except Exception as _exc:  # broad catch — resilience against all failures
            return []

    def _get_config_sections(self) -> List[str]:
        try:
            from chat_app.settings import get_settings
            s = get_settings()
            return [k for k in s.model_dump().keys() if not k.startswith("_")]
        except Exception as _exc:  # broad catch — resilience against all failures
            return []

    def _get_error_codes(self) -> List[str]:
        try:
            from chat_app.error_taxonomy import ErrorCode
            return [c.value for c in ErrorCode]
        except Exception as _exc:  # broad catch — resilience against all failures
            return []

    def _get_safety_levels(self) -> List[str]:
        try:
            from chat_app.safety_policies import ToolSafetyLevel
            return [l.value for l in ToolSafetyLevel]
        except Exception as _exc:  # broad catch — resilience against all failures
            return []

    def _get_slo_definitions(self) -> List[str]:
        try:
            from chat_app.slo_tracker import DEFAULT_SLOS
            return [s.name for s in DEFAULT_SLOS]
        except Exception as _exc:  # broad catch — resilience against all failures
            return []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[ProjectDictionary] = None


def get_project_dictionary() -> ProjectDictionary:
    """Get the global ProjectDictionary singleton."""
    global _instance
    if _instance is None:
        _instance = ProjectDictionary()
    return _instance
