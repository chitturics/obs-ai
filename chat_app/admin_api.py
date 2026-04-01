"""
Admin Configuration & Dashboard API — Management endpoints for ObsAI.

This module is the thin orchestrator that:
1. Defines the main `router` (auth-protected) and `public_router` (no auth)
2. Registers all sub-routers for specific endpoint groups
3. Re-exports shared helpers/stores for backward compatibility

Mount with:
    from chat_app.admin_api import router as admin_router, public_router as admin_public_router
    app.include_router(admin_router)
    app.include_router(admin_public_router)

    # API Services (external consumer API)
    from chat_app.api_services import services_router
    app.include_router(services_router)
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared helpers (canonical source: admin_shared.py)
# ---------------------------------------------------------------------------
from chat_app.admin_shared import (  # noqa: F401
    _append_audit,
    _arun,
    _collection_hit_counts,
    _compose_cmd,
    _compose_dir,
    _compute_diff,
    _config_audit_trail,
    _container_cmd,
    _csrf_check,
    _feature_flags,
    _feature_requests,
    _get_feature_flags,
    _human_size,
    _intent_counts,
    _MAX_AUDIT_ENTRIES,
    _MAX_RECENT_QUERIES,
    _MAX_VOLUME_BUCKETS,
    _now_iso,
    _PROJECT_ROOT_ADMIN,
    _query_volume,
    _rate_limit,
    _rate_limit_store,
    _RATE_LIMIT_MAX_REQUESTS,
    _recent_queries,
    _safe_error,
    _track_audit_user,
    _UTILITY_OPS,
    _validate_password_complexity,
    ApprovalDecision,
    ContainerActionRequest,
    ContainerBuildRequest,
    FeatureToggleRequest,
    PromptUpdateRequest,
    record_query,
)

from chat_app.auth_dependencies import (
    require_admin,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Router definitions
# ---------------------------------------------------------------------------

# All admin endpoints require ADMIN role by default.
router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)

# Public router — no auth required. Shares the /api/admin prefix.
public_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-public"],
    dependencies=[Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Include sub-routers (extracted for maintainability)
# ---------------------------------------------------------------------------

from chat_app.admin_settings_routes import _get_feature_flags as _gff_settings  # noqa: E402,F401
from chat_app.admin_collections_routes import _do_collection_backup  # noqa: E402,F401

# Re-import models used by other modules for backward compatibility
from chat_app.admin_settings_routes import _mask_secrets, _build_section_model_map  # noqa: E402,F401
from chat_app.admin_config_routes import _get_config_mgr, _apply_config_change  # noqa: E402,F401
from chat_app.admin_config_routes import ConfigSectionUpdateRequest  # noqa: E402,F401
from chat_app.admin_users_routes import _get_engine  # noqa: E402,F401

# Re-export sub-routers for backward compatibility with tests and external callers
from chat_app.admin_config_routes import config_router  # noqa: E402,F401
from chat_app.admin_config_helpers import config_ext_router  # noqa: E402,F401
from chat_app.admin_settings_routes import settings_router  # noqa: E402,F401
from chat_app.admin_tools_routes import tools_router  # noqa: E402,F401
from chat_app.admin_users_routes import users_router  # noqa: E402,F401
from chat_app.admin_security_routes import security_router  # noqa: E402,F401
from chat_app.admin_observability_routes import observability_router  # noqa: E402,F401
from chat_app.admin_skills_routes import skills_router  # noqa: E402,F401
from chat_app.admin_skills_orchestration_routes import skills_orch_router  # noqa: E402,F401
from chat_app.admin_skills_workflow_routes import workflow_templates_router  # noqa: E402,F401
from chat_app.admin_collections_routes import collections_router  # noqa: E402,F401
from chat_app.admin_learning_routes import learning_router  # noqa: E402,F401
from chat_app.admin_learning_ext_routes import learning_ext_router  # noqa: E402,F401
from chat_app.admin_operations_routes import operations_router  # noqa: E402,F401
from chat_app.admin_dashboard_routes import dashboard_router  # noqa: E402,F401
from chat_app.admin_pages_routes import pages_router, pages_public_router  # noqa: E402,F401
from chat_app.admin_interactive_tools_routes import (  # noqa: E402,F401
    interactive_tools_public_router,
    interactive_tools_router,
)
from chat_app.admin_network_routes import network_router  # noqa: E402,F401
from chat_app.admin_upgrade_routes import upgrade_router  # noqa: E402,F401
from chat_app.admin_upgrade_platform_routes import upgrade_platform_router  # noqa: E402,F401
from chat_app.admin_data_sources_routes import data_sources_router  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Pydantic models — re-exported from sub-modules for backward compatibility
# ---------------------------------------------------------------------------

from chat_app.admin_tools import (  # noqa: F401
    NetworkTestRequest,
    SyslogTestRequest,
    RegexAIRequest,
    RegexGenerateRequest,
    FSMonitorRequest,
    ToolsAIChatRequest,
    TransformAIRequest,
    AnsibleValidateRequest,
    AnsibleAnalyzeRequest,
    AnsibleGenerateRequest,
    ShellAnalyzeRequest,
    ShellGenerateRequest,
    PythonAnalyzeRequest,
    PythonGenerateRequest,
    UpdateSavedSearchRequest,
    CreateKnowledgeObjectRequest,
)


class QueryRecord(BaseModel):
    """Record a user query for activity tracking."""
    query: str
    intent: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None


class LLMUpdateRequest(BaseModel):
    """Update LLM configuration."""
    model: Optional[str] = None
    embed_model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    num_ctx: Optional[int] = Field(default=None, ge=512, le=131072, description="Context window size (tokens). Smaller = faster inference. Default: 2048")
    num_predict: Optional[int] = Field(default=None, ge=64, le=4096, description="Max response tokens. Caps generation time. Default: 1024")
    timeout: Optional[int] = Field(default=None, ge=10, le=600, description="LLM response timeout in seconds. Default: 90")
    base_url: Optional[str] = None


class _RestartServiceRequest(BaseModel):
    """Request to restart a specific container service."""
    service: str = Field(..., description="Container/service name to restart (e.g. 'chat_ui_app').")


class ConfigSectionReplaceRequest(BaseModel):
    """Replace a config.yaml section entirely."""
    data: Any = Field(..., description="New section data (dict, list, or scalar).")
    auto_restart: bool = Field(
        default=False,
        description="Auto-restart affected containers after saving.",
    )


class ProfileSwitchRequest(BaseModel):
    """Switch the active deployment profile."""
    profile: str = Field(..., description="Profile name: LLM_LITE, LLM_MED, or LLM_MAX")
    auto_restart: bool = Field(
        default=False,
        description="Auto-restart the app container after switching.",
    )


class ConfigImportRequest(BaseModel):
    """Import a complete config.yaml."""
    config: Dict[str, Any] = Field(..., description="Full config.yaml content as dict.")
    auto_restart: bool = Field(
        default=False,
        description="Auto-restart all containers after import.",
    )


class MCPServerConfigRequest(BaseModel):
    """Add/update an MCP server in config.yaml."""
    name: str
    client_type: str = Field(default="sse", pattern="^(sse|streamable-http|stdio)$")
    endpoint: Optional[str] = None
    command: Optional[str] = None
    auth_scheme: str = Field(default="none", pattern="^(none|bearer|api_key|oauth2)$")
    auth_hints: Optional[Dict[str, str]] = None
    enabled: bool = True
    description: str = ""


class ConfigRestoreRequest(BaseModel):
    """Restore config from backup."""
    filename: str


class _TokenCreateRequest(BaseModel):
    """Request body for creating an API token."""
    label: str = Field(default="", description="Human-readable label for this token")
    role: str = Field(default="ADMIN", description="Role assigned to this token (ADMIN, USER, ANALYST, VIEWER)")


class CreateRoleRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=30)
    description: str = Field(default="", max_length=200)
    permissions: list = Field(default_factory=list)


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "USER"


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    password: Optional[str] = None


class ConfigRollbackRequest(BaseModel):
    auto_restart: bool = Field(
        default=False,
        description="Auto-restart affected containers after rollback.",
    )


class ConfAnalyzeRequest(BaseModel):
    apps_dir: str = Field(default="/opt/splunk/etc/apps", description="Path to Splunk apps directory")
    output_format: str = Field(default="json", pattern="^(json|csv|yaml)$", description="Output format")


class _ConfAnalysisRequest(BaseModel):
    """Request body for Splunk conf analysis and Cribl migration comparison."""
    apps_dir: str = Field(default="", description="Direct path to Splunk apps directory (legacy).")
    splunk_repo: str = Field(default="", description="Splunk repo root.")
    cribl_repo: str = Field(default="", description="Cribl repo root.")
    btool_csv: str = Field(default="", description="btoolinfo CSV content.")
    app_filter: str = Field(default="", description="Regex filter for app names.")
    category_filter: str = Field(default="", description="Filter by app category.")
    group_filter: str = Field(default="", description="Filter by deployment group.")
    output_format: str = Field(default="json", description="Output format: json, csv, yaml")


class _StatusUpdate(BaseModel):
    sourcetype: str = Field(..., min_length=1, max_length=200)
    status: str = Field(..., description="not_started, in_progress, needs_review, done, not_applicable")
    priority: str = Field(default="", description="critical, high, medium, low")
    notes: str = Field(default="", max_length=2000)
    assignee: str = Field(default="", max_length=100)


# NetworkTestRequest through CreateKnowledgeObjectRequest are re-exported
# from admin_tools.py at the top of this file.


# ---------------------------------------------------------------------------
# Shared data kept here for backward compatibility with tests/other modules
# ---------------------------------------------------------------------------

# In-memory shared conversations store
_shared_conversations: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Config section restart policy (data in admin_api_data.py)
# ---------------------------------------------------------------------------

from chat_app.admin_api_data import (  # noqa: F401
    _SECTION_RESTART_POLICY,
    _PROMPT_CATALOG,
    _COMPOSITION_ORDER,
)


def _get_restart_policy(section: str) -> Dict[str, Any]:
    """Get the restart policy for a config section."""
    return _SECTION_RESTART_POLICY.get(section, {
        "action": "hot_reload",
        "services": [],
        "description": "Unknown section — attempting hot reload",
    })


# ---------------------------------------------------------------------------
# Settings helpers (kept for backward compat — canonical copy in sub-routers)
# ---------------------------------------------------------------------------

_SECTION_MODEL_MAP: Dict[str, type] = {}

_SECRET_FIELD_NAMES = frozenset({
    "password", "token", "secret", "api_key", "admin_password",
    "auth_secret", "salt", "validator_pass", "splunk_token",
})

_NON_SECRET_ALLOWLIST = frozenset({
    "smart_chunk_tokens", "smart_chunk_overlap_tokens",
    "chunk_tokens", "overlap_tokens",
})


def _settings_section_dict(section_name: str) -> Dict[str, Any]:
    """Serialise a settings section to a plain dict."""
    from chat_app.settings import get_settings
    settings = get_settings()
    section = getattr(settings, section_name, None)
    if section is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown settings section: {section_name}")
    return section.model_dump()


# ---------------------------------------------------------------------------
# Skills Manager helper (used by dashboard)
# ---------------------------------------------------------------------------

def _get_skills_manager():
    """Import and return the SkillsManager singleton."""
    from chat_app.skills_manager import get_skills_manager
    return get_skills_manager()


# User management helpers (kept for backward compat)
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

_DEFAULT_ROLES = ["ADMIN", "USER", "ANALYST", "VIEWER"]
_CUSTOM_ROLES_FILE = Path("/app/data/custom_roles.json")


def _load_custom_roles() -> list:
    """Load custom roles from persistent JSON file."""
    import json as _json
    try:
        if _CUSTOM_ROLES_FILE.is_file():
            data = _json.loads(_CUSTOM_ROLES_FILE.read_text())
            return data if isinstance(data, list) else []
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[ADMIN] Failed to load custom roles: %s", exc)
    try:
        fallback = _PROJECT_ROOT_ADMIN / "data" / "custom_roles.json"
        if fallback.is_file():
            data = _json.loads(fallback.read_text())
            return data if isinstance(data, list) else []
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ADMIN] Failed to load custom roles from fallback path: %s", exc)
    return []


def _save_custom_roles(roles: list):
    """Persist custom roles to JSON file."""
    import json as _json
    for p in [_CUSTOM_ROLES_FILE, _PROJECT_ROOT_ADMIN / "data" / "custom_roles.json"]:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_json.dumps(roles, indent=2))
            return
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ADMIN] Failed to save custom roles: %s", exc)
            continue


def _get_available_roles() -> list:
    """Return all roles: built-in + custom."""
    custom = _load_custom_roles()
    custom_names = [r["name"] for r in custom if isinstance(r, dict) and "name" in r]
    return _DEFAULT_ROLES + [n for n in custom_names if n not in _DEFAULT_ROLES]


# ---------------------------------------------------------------------------
# MCP server removal (config route kept here — single endpoint)
# ---------------------------------------------------------------------------

@router.delete("/config/mcp-gateway/servers/{name}", summary="Remove MCP server from config")
async def remove_mcp_server_from_config(name: str):
    """Remove an MCP server from config.yaml."""
    mgr = _get_config_mgr()
    data = mgr.load(force=True)
    mcp = data.get("mcp_gateway", {})
    servers = mcp.get("servers", [])

    original_count = len(servers)
    servers = [s for s in servers if s.get("name") != name]
    if len(servers) == original_count:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found.")

    mcp["servers"] = servers
    success = mgr.save(data, reason=f"remove MCP server '{name}'")

    if not success:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to save config.yaml.")

    _append_audit(section="config.mcp_gateway.servers", action="remove", changes={"name": name})
    return {"removed": name, "remaining": len(servers), "timestamp": _now_iso()}


# ---------------------------------------------------------------------------
# Skills management (install/uninstall/toggle/metrics — kept in main router)
# ---------------------------------------------------------------------------

@router.get("/skills", summary="List all installed skills")
async def list_skills(
    limit: int = 50,
    offset: int = 0,
):
    """Return all installed skills with status and metrics."""
    mgr = _get_skills_manager()
    skills = mgr.list_skills()
    if not skills:
        try:
            from chat_app.skill_catalog import get_skill_catalog
            catalog = get_skill_catalog()
            all_skills = catalog.list_all()
            skills = [
                {
                    "name": s.get("skill_name", s.get("name", "")),
                    "action": s.get("action", ""),
                    "family": s.get("family", ""),
                    "handler_key": s.get("handler_key", ""),
                    "enabled": True,
                    "description": s.get("description", ""),
                    "status": "available",
                }
                for s in all_skills
            ]
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[ADMIN] Failed to load skills from catalog: %s", exc)
    total = len(skills)
    page = skills[offset:offset + limit]
    return {"skills": page, "total": total, "timestamp": _now_iso()}


@router.get("/skills/discover", summary="Discover available skills")
async def discover_skills(limit: int = 50, offset: int = 0):
    """Scan the skills directory for available (installable) skill manifests."""
    mgr = _get_skills_manager()
    manifests = mgr.discover_skills()
    installed = {s["name"] for s in mgr.list_skills()}
    available = []
    for m in manifests:
        available.append({
            "name": m.name, "version": m.version, "description": m.description,
            "author": m.author, "category": m.category.value, "tags": m.tags,
            "actions": [a.name for a in m.actions], "dependencies": m.dependencies,
            "installed": m.name in installed, "icon": m.icon,
            "license": m.license, "homepage": m.homepage,
        })
    total = len(available)
    page = available[offset:offset + limit]
    return {"available": page, "total": total, "installed_count": len(installed),
            "skills_dir": str(mgr.skills_dir), "timestamp": _now_iso()}


@router.post("/skills/{name}/install", summary="Install a skill")
async def install_skill(name: str):
    """Install a skill from the skills directory by name."""
    from fastapi import HTTPException
    mgr = _get_skills_manager()
    existing = mgr.get_skill(name)
    if existing and existing.status.value not in ("uninstalled", "error"):
        raise HTTPException(status_code=409, detail=f"Skill '{name}' is already installed (status: {existing.status.value}).")
    try:
        instance = mgr.install_skill(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found in catalog")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, f"skill install '{name}'"))
    _append_audit(section="skills", action="install", changes={"name": name, "version": instance.manifest.version})
    return {"name": name, "version": instance.manifest.version, "status": instance.status.value,
            "actions": [a.name for a in instance.manifest.actions], "error": instance.error, "timestamp": _now_iso()}


@router.post("/skills/{name}/uninstall", summary="Uninstall a skill")
async def uninstall_skill(name: str):
    """Uninstall an installed skill."""
    from fastapi import HTTPException
    mgr = _get_skills_manager()
    if not mgr.get_skill(name):
        raise HTTPException(status_code=404, detail=f"Skill '{name}' is not installed.")
    success = mgr.uninstall_skill(name)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to uninstall skill '{name}'.")
    _append_audit(section="skills", action="uninstall", changes={"name": name})
    return {"name": name, "uninstalled": True, "timestamp": _now_iso()}


@router.put("/skills/{name}/toggle", summary="Enable or disable a skill")
async def toggle_skill(name: str, body: FeatureToggleRequest):
    """Enable or disable an installed skill at runtime."""
    from fastapi import HTTPException
    mgr = _get_skills_manager()
    instance = mgr.get_skill(name)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' is not installed.")
    previous_status = instance.status.value
    success = mgr.enable_skill(name) if body.enabled else mgr.disable_skill(name)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to toggle skill '{name}'.")
    new_status = mgr.get_skill(name).status.value
    _append_audit(section="skills", action="toggle",
                  changes={"name": name, "enabled": body.enabled, "status": new_status},
                  previous={"status": previous_status})
    return {"name": name, "enabled": body.enabled, "status": new_status,
            "previous_status": previous_status, "timestamp": _now_iso()}


@router.get("/skills/metrics", summary="Get skill execution metrics")
async def get_skill_metrics():
    """Return aggregated and per-skill execution metrics."""
    mgr = _get_skills_manager()
    aggregated = mgr.get_skill_metrics()
    per_skill = mgr.list_skills()
    history = mgr.get_execution_history(limit=50)
    return {
        "aggregated": aggregated,
        "per_skill": [{"name": s["name"], "status": s["status"], **s["metrics"]} for s in per_skill],
        "recent_executions": history,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# A2A Well-Known Discovery
# ---------------------------------------------------------------------------

wellknown_router = APIRouter(tags=["a2a-discovery"])


@wellknown_router.get("/.well-known/agent.json", summary="A2A agent discovery")
async def wellknown_agent_json():
    """Return the A2A discovery document at /.well-known/agent.json."""
    try:
        from chat_app.a2a_protocol import get_well_known_agent_json
        return get_well_known_agent_json()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[A2A] Well-known agent.json failed: %s", exc)
        return {"error": str(exc)}
