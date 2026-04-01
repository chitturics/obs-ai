"""Admin sub-router: Config.yaml management endpoints.

Handles these endpoint groups:
- GET  /api/admin/config                          — Full config.yaml content
- GET  /api/admin/config/sections                 — List all config sections
- GET  /api/admin/config/section/{section}        — Get a specific section
- PATCH /api/admin/config/section/{section}       — Update (merge) a section
- PUT  /api/admin/config/section/{section}        — Replace a section entirely
- GET  /api/admin/config/profiles                 — List deployment profiles
- GET  /api/admin/config/profiles/{name}          — Get a specific profile
- POST /api/admin/config/profiles/switch          — Switch active profile
- PATCH /api/admin/config/profiles/{name}         — Update a profile
- GET  /api/admin/config/directories              — Directory configuration
- GET  /api/admin/config/database                 — Database configuration
- GET  /api/admin/config/ingestion                — Ingestion configuration
- GET  /api/admin/config/retrieval                — Retrieval configuration
- GET  /api/admin/config/prompts-config           — Prompt configuration
- GET  /api/admin/config/ui                       — UI configuration
- GET  /api/admin/config/security                 — Security configuration
- GET  /api/admin/config/features                 — Feature flags from config.yaml
- GET  /api/admin/config/mcp-gateway              — MCP gateway configuration
- GET  /api/admin/config/sharepoint               — SharePoint config
- GET  /api/admin/config/github                   — GitHub config
- GET  /api/admin/config/organization             — Organization config
- GET  /api/admin/config/organization/index-mappings
- PATCH /api/admin/config/organization/index-mappings
- GET  /api/admin/config/organization/field-mappings
- PATCH /api/admin/config/organization/field-mappings
- GET  /api/admin/config/mcp-gateway/servers      — List MCP servers
- GET  /api/admin/mcp/servers                     — Compatibility alias
- POST /api/admin/config/mcp-gateway/servers      — Add MCP server
- DELETE /api/admin/config/mcp-gateway/servers/{name}
- GET  /api/admin/config/backups                  — List config backups
- GET  /api/admin/config/backup                   — Alias for backups
- POST /api/admin/config/backup                   — Create a backup
- POST /api/admin/config/restore                  — Restore from backup
- POST /api/admin/config/reload                   — Force reload settings
- POST /api/admin/config/restart-service          — Restart a container
- POST /api/admin/config/export                   — Export full config
- POST /api/admin/config/import                   — Import full config
- GET  /api/admin/config/restart-policy           — Restart policies
- POST /api/admin/config/apply                    — Apply pending changes
- GET  /api/admin/config/versions                 — Config version history
- GET  /api/admin/config/versions/{commit_id}     — Specific commit
- POST /api/admin/config/rollback/{commit_id}     — Rollback config

Mount with:
    from chat_app.admin_config_routes import config_router
    router.include_router(config_router)
"""

import logging

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.settings import reload_settings
from chat_app.admin_shared import (
    _append_audit,
    _arun,
    _compose_cmd,
    _compose_dir,
    _container_cmd,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

config_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-config"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_config_mgr():
    """Import and return the ConfigManager singleton."""
    from chat_app.config_manager import get_config_manager
    return get_config_manager()


# Restart classification for each config section.
_SECTION_RESTART_POLICY: Dict[str, Dict[str, Any]] = {
    "active_profile":  {"action": "app_restart",  "services": ["chat_ui_app"],
                        "description": "Profile switch changes LLM model, context length, and performance tuning"},
    "profiles":        {"action": "app_restart",  "services": ["chat_ui_app"],
                        "description": "Profile definitions affect LLM and performance settings"},
    "directories":     {"action": "app_restart",  "services": ["chat_ui_app"],
                        "description": "Path changes require app restart to re-mount directories"},
    "database":        {"action": "full_restart", "services": ["chat_db_app", "chat_ui_app"],
                        "description": "Database config changes require both DB and app restart"},
    "ingestion":       {"action": "hot_reload",   "services": [],
                        "description": "Chunking and ingestion settings reload dynamically"},
    "retrieval":       {"action": "hot_reload",   "services": [],
                        "description": "Retrieval top_k, thresholds, and strategy reload dynamically"},
    "prompts":         {"action": "hot_reload",   "services": [],
                        "description": "Prompt settings reload dynamically"},
    "ui":              {"action": "app_restart",  "services": ["chat_ui_app"],
                        "description": "UI framework changes require app restart"},
    "security":        {"action": "hot_reload",   "services": [],
                        "description": "Rate limiting and CORS settings reload dynamically"},
    "features":        {"action": "hot_reload",   "services": [],
                        "description": "Feature flags reload dynamically"},
    "mcp_gateway":     {"action": "app_restart",  "services": ["chat_ui_app"],
                        "description": "MCP server connections require app restart"},
    "sharepoint":      {"action": "hot_reload",   "services": [],
                        "description": "SharePoint ingestion settings reload dynamically"},
    "github":          {"action": "hot_reload",   "services": [],
                        "description": "GitHub ingestion settings reload dynamically"},
    "organization":    {"action": "hot_reload",   "services": [],
                        "description": "Index/field mappings reload dynamically"},
    "orchestration":   {"action": "hot_reload",   "services": [],
                        "description": "Orchestration strategy and thresholds reload dynamically"},
    "docling":         {"action": "hot_reload",   "services": [],
                        "description": "Docling conversion settings reload dynamically"},
    "splunkbase_catalog": {"action": "hot_reload", "services": [],
                           "description": "Splunkbase catalog settings reload dynamically"},
    "ports":             {"action": "full_restart", "services": ["chat_ui_app"],
                          "description": "Port changes require container restart with new port bindings"},
    "knowledge_graph":   {"action": "hot_reload",   "services": [],
                          "description": "Knowledge graph settings reload dynamically; rebuild via admin API"},
    "langfuse":          {"action": "hot_reload",   "services": [],
                          "description": "Langfuse deprecated — tracing handled by OpenTelemetry"},
}


def _get_restart_policy(section: str) -> Dict[str, Any]:
    """Get the restart policy for a config section."""
    return _SECTION_RESTART_POLICY.get(section, {
        "action": "hot_reload",
        "services": [],
        "description": "Unknown section — attempting hot reload",
    })


async def _apply_config_change(section: str, auto_restart: bool = False) -> Dict[str, Any]:
    """Apply config changes: reload settings + optionally restart containers."""
    result = {
        "settings_reloaded": False,
        "containers_restarted": [],
        "restart_needed": [],
        "policy": _get_restart_policy(section),
    }

    try:
        reload_settings()
        result["settings_reloaded"] = True
        logger.info("[CONFIG] Settings reloaded after '%s' update", section)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[CONFIG] Settings reload failed: %s", exc)

    policy = result["policy"]
    services = policy.get("services", [])

    if policy["action"] in ("app_restart", "full_restart") and services:
        if auto_restart:
            runtime = _container_cmd()
            if runtime is None:
                result["restart_needed"] = services
                result["error"] = (
                    "No container runtime available inside this container. "
                    "Restart from host: " + ", ".join(f"{runtime or 'podman'} restart {s}" for s in services)
                )
            else:
                compose = _compose_cmd()
                compose_dir = _compose_dir()
                for svc in services:
                    try:
                        proc = await _arun(
                            compose + ["restart", svc],
                            capture_output=True, text=True, timeout=60,
                            cwd=compose_dir,
                        )
                        if proc.returncode == 0:
                            result["containers_restarted"].append(svc)
                            logger.info("[CONFIG] Restarted container: %s", svc)
                        else:
                            result["restart_needed"].append(svc)
                            logger.warning("[CONFIG] Failed to restart %s: %s", svc, proc.stderr[:200])
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                        result["restart_needed"].append(svc)
                        logger.warning("[CONFIG] Could not restart %s: %s", svc, exc)
        else:
            result["restart_needed"] = services

    return result


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ConfigSectionUpdateRequest(BaseModel):
    """Update a config.yaml section with partial values."""
    values: Dict[str, Any] = Field(
        ..., description="Key-value pairs to merge into the section.",
    )
    auto_restart: bool = Field(
        default=False,
        description="Auto-restart affected containers after saving.",
    )


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


class ConfigRestoreRequest(BaseModel):
    """Restore config from backup."""
    filename: str


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


class _RestartServiceRequest(BaseModel):
    """Request to restart a specific container service."""
    service: str = Field(..., description="Container/service name to restart (e.g. 'chat_ui_app').")


class ConfigRollbackRequest(BaseModel):
    auto_restart: bool = Field(
        default=False,
        description="Auto-restart affected containers after rollback.",
    )


# ---------------------------------------------------------------------------
# Config CRUD Endpoints
# ---------------------------------------------------------------------------


@config_router.get("/config", summary="Get full config.yaml content")
async def get_full_config():
    """Return the full config.yaml content with section metadata."""
    mgr = _get_config_mgr()
    data = mgr.load(force=True)
    sections = mgr.get_all_sections()
    return {
        "config": data,
        "sections": sections,
        "active_profile": data.get("active_profile", "LLM_MED"),
        "config_path": mgr.config_path,
        "timestamp": _now_iso(),
    }


@config_router.get("/config/sections", summary="List all config sections with metadata")
async def list_config_sections():
    """List all top-level config.yaml sections with type info."""
    mgr = _get_config_mgr()
    return {
        "sections": mgr.get_all_sections(),
        "config_path": mgr.config_path,
        "timestamp": _now_iso(),
    }


@config_router.get("/config/section/{section}", summary="Get a specific config section")
async def get_config_section(section: str):
    """Return a specific section from config.yaml."""
    mgr = _get_config_mgr()
    data = mgr.load()
    if section not in data:
        raise HTTPException(
            status_code=404,
            detail=f"Section '{section}' not found. Available: {list(data.keys())}",
        )
    return {
        "section": section,
        "data": data[section],
        "type": type(data[section]).__name__,
        "timestamp": _now_iso(),
    }


@config_router.patch("/config/section/{section}", summary="Update a config section (merge)")
async def update_config_section(section: str, body: ConfigSectionUpdateRequest):
    """Partially update a config.yaml section by merging values.

    Set ``auto_restart: true`` to automatically restart affected containers.
    """
    mgr = _get_config_mgr()

    is_valid, errors = mgr.validate_section(section, body.values)
    if not is_valid:
        raise HTTPException(status_code=422, detail={"errors": errors})

    previous = mgr.get_section(section)
    success, updated = mgr.update_section(section, body.values)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to save config.yaml.")

    _append_audit(
        section=f"config.{section}",
        action="update",
        changes=body.values,
        previous=previous,
    )

    apply_result = await _apply_config_change(section, auto_restart=body.auto_restart)

    return {
        "section": section,
        "updated": updated,
        "previous": previous,
        "applied": apply_result,
        "timestamp": _now_iso(),
    }


@config_router.put("/config/section/{section}", summary="Replace a config section entirely")
async def replace_config_section(section: str, body: ConfigSectionReplaceRequest):
    """Replace an entire config.yaml section.

    Set ``auto_restart: true`` to automatically restart affected containers.
    """
    mgr = _get_config_mgr()
    previous = mgr.get_section(section)
    success, new_data = mgr.replace_section(section, body.data)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to save config.yaml.")

    _append_audit(
        section=f"config.{section}",
        action="replace",
        changes={"new_data": str(body.data)[:500]},
        previous=previous,
    )

    apply_result = await _apply_config_change(section, auto_restart=body.auto_restart)

    return {
        "section": section,
        "data": new_data,
        "applied": apply_result,
        "timestamp": _now_iso(),
    }


# --- Profile Management ---

@config_router.get("/config/profiles", summary="List deployment profiles")
async def list_profiles():
    """List all deployment profiles with summary info."""
    mgr = _get_config_mgr()
    return {
        "profiles": mgr.list_profiles(),
        "active_profile": mgr.get_active_profile(),
        "timestamp": _now_iso(),
    }


@config_router.get("/config/profiles/{name}", summary="Get a specific profile")
async def get_profile(name: str):
    """Get full configuration for a specific deployment profile."""
    mgr = _get_config_mgr()
    profile = mgr.get_profile(name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found.")
    return {
        "name": name,
        "profile": profile,
        "is_active": mgr.get_active_profile() == name,
        "timestamp": _now_iso(),
    }


@config_router.post("/config/profiles/switch", summary="Switch active deployment profile")
async def switch_profile(body: ProfileSwitchRequest):
    """Switch the active deployment profile.

    Set ``auto_restart: true`` to restart the app container automatically.
    """
    mgr = _get_config_mgr()
    previous = mgr.get_active_profile()
    success, message = mgr.switch_profile(body.profile)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    _append_audit(
        section="config.active_profile",
        action="switch_profile",
        changes={"profile": body.profile},
        previous={"profile": previous},
    )

    apply_result = await _apply_config_change("active_profile", auto_restart=body.auto_restart)

    return {
        "active_profile": body.profile,
        "previous_profile": previous,
        "message": message,
        "applied": apply_result,
        "timestamp": _now_iso(),
    }


@config_router.patch("/config/profiles/{name}", summary="Update a profile")
async def update_profile(name: str, body: ConfigSectionUpdateRequest):
    """Update settings within a specific profile."""
    mgr = _get_config_mgr()
    previous = mgr.get_profile(name)
    if not previous:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found.")

    success, updated = mgr.update_profile(name, body.values)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save config.yaml.")

    _append_audit(
        section=f"config.profiles.{name}",
        action="update",
        changes=body.values,
        previous=previous,
    )

    return {
        "name": name,
        "profile": updated,
        "timestamp": _now_iso(),
    }


# --- Specific Config Section Shortcuts ---

@config_router.get("/config/directories", summary="Get directory configuration")
async def get_directories():
    """Get all configured directory paths."""
    mgr = _get_config_mgr()
    from pathlib import Path as _Path
    dirs = mgr.get_section("directories")
    result = {}
    for key, val in dirs.items():
        if isinstance(val, str):
            p = _Path(val)
            result[key] = {"path": val, "exists": p.exists()}
        else:
            result[key] = val
    return {"directories": result, "timestamp": _now_iso()}


@config_router.get("/config/database", summary="Get database configuration")
async def get_database_config():
    """Get database (PostgreSQL + ChromaDB) configuration."""
    mgr = _get_config_mgr()
    return {"database": mgr.get_section("database"), "timestamp": _now_iso()}


@config_router.get("/config/ingestion", summary="Get ingestion configuration")
async def get_ingestion_config():
    """Get ingestion settings (chunking, file filtering, performance)."""
    mgr = _get_config_mgr()
    return {"ingestion": mgr.get_section("ingestion"), "timestamp": _now_iso()}


@config_router.get("/config/retrieval", summary="Get retrieval configuration")
async def get_retrieval_config():
    """Get retrieval settings (top_k, similarity thresholds, strategy)."""
    mgr = _get_config_mgr()
    return {"retrieval": mgr.get_section("retrieval"), "timestamp": _now_iso()}


@config_router.get("/config/prompts-config", summary="Get prompt configuration")
async def get_prompts_config():
    """Get prompt configuration (version, time range, strict mode, temperatures)."""
    mgr = _get_config_mgr()
    return {"prompts": mgr.get_section("prompts"), "timestamp": _now_iso()}


@config_router.get("/config/ui", summary="Get UI configuration")
async def get_ui_config():
    """Get UI framework and display configuration."""
    mgr = _get_config_mgr()
    return {"ui": mgr.get_section("ui"), "timestamp": _now_iso()}


@config_router.get("/config/security", summary="Get security configuration")
async def get_security_config():
    """Get security settings (rate limiting, CORS)."""
    mgr = _get_config_mgr()
    data = mgr.get_section("security")
    return {"security": data, "timestamp": _now_iso()}


@config_router.get("/config/features", summary="Get feature flags from config.yaml")
async def get_config_features():
    """Get feature flags as stored in config.yaml (vs runtime overrides)."""
    mgr = _get_config_mgr()
    return {"features": mgr.get_section("features"), "timestamp": _now_iso()}


@config_router.get("/config/mcp-gateway", summary="Get MCP gateway configuration")
async def get_mcp_gateway_config():
    """Get full MCP gateway and server registry configuration."""
    mgr = _get_config_mgr()
    return {"mcp_gateway": mgr.get_section("mcp_gateway"), "timestamp": _now_iso()}


@config_router.get("/config/sharepoint", summary="Get SharePoint ingestion config")
async def get_sharepoint_config():
    """Get SharePoint integration configuration."""
    mgr = _get_config_mgr()
    data = mgr.get_section("sharepoint")
    for key in ("client_secret", "tenant_id", "client_id"):
        if key in data and data[key] not in ("", "Set via ENV"):
            data[key] = "***masked***"
    return {"sharepoint": data, "timestamp": _now_iso()}


@config_router.get("/config/github", summary="Get GitHub ingestion config")
async def get_github_config():
    """Get GitHub repository ingestion configuration."""
    mgr = _get_config_mgr()
    data = mgr.get_section("github")
    if "token" in data and data["token"] not in ("", "Set via ENV"):
        data["token"] = "***masked***"
    return {"github": data, "timestamp": _now_iso()}


@config_router.get("/config/organization", summary="Get organization-specific config")
async def get_org_config():
    """Get organization-specific settings (index mappings, field mappings, CIM models)."""
    mgr = _get_config_mgr()
    return {"organization": mgr.get_section("organization"), "timestamp": _now_iso()}




# ---------------------------------------------------------------------------
# Config Directory Management (Splunk-style per-file config)
# ---------------------------------------------------------------------------

@config_router.get("/config/files", summary="List all config files")
async def list_config_files_endpoint():
    """List all configuration files in the config/ directory with metadata."""
    try:
        from chat_app.config_loader import list_config_files, _CONFIG_DIR
        files = list_config_files()
        return {
            "files": files,
            "total": len(files),
            "config_dir": str(_CONFIG_DIR),
            "categories": {
                "core": len([f for f in files if f["category"] == "core"]),
                "worker": len([f for f in files if f["category"] == "worker"]),
                "integration": len([f for f in files if f["category"] == "integration"]),
                "profile": len([f for f in files if f["category"] == "profile"]),
                "skill": len([f for f in files if f["category"] == "skill"]),
            },
            "timestamp": _now_iso(),
        }
    except Exception as exc:
        return {"files": [], "error": str(exc), "timestamp": _now_iso()}


@config_router.get("/config/file/{file_path:path}", summary="Read a config file")
async def read_config_file(file_path: str):
    """Read the contents of a specific config file."""
    import re
    if not re.match(r'^[a-zA-Z0-9_/\-\.]+\.yaml$', file_path):
        raise HTTPException(status_code=400, detail="Invalid file path")
    try:
        from chat_app.config_loader import _CONFIG_DIR, _load_yaml
        target = _CONFIG_DIR / file_path
        # Security check
        target.resolve().relative_to(_CONFIG_DIR.resolve())
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"Config file not found: {file_path}")
        data = _load_yaml(target)
        raw = target.read_text(encoding="utf-8")
        return {
            "path": file_path,
            "data": data,
            "raw_yaml": raw,
            "size_bytes": target.stat().st_size,
            "timestamp": _now_iso(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "read config file"))


@config_router.patch("/config/file/{file_path:path}", summary="Update a config file")
async def update_config_file(file_path: str, request: Request):
    """Update a config file with new values (merge). Creates backup first."""
    import re
    if not re.match(r'^[a-zA-Z0-9_/\-\.]+\.yaml$', file_path):
        raise HTTPException(status_code=400, detail="Invalid file path")
    try:
        from chat_app.config_loader import _CONFIG_DIR, _load_yaml, save_config_file
        body = await request.json()
        new_data = body.get("data", body)

        target = _CONFIG_DIR / file_path
        target.resolve().relative_to(_CONFIG_DIR.resolve())

        # Load existing data
        old_data = _load_yaml(target) if target.is_file() else {}

        # Create backup
        if target.is_file():
            from chat_app.config_manager import get_config_manager
            mgr = get_config_manager()
            mgr.create_backup(f"Before updating {file_path}")

        # Merge
        merged = {**old_data, **new_data}
        success = save_config_file(file_path, merged)

        if success:
            _append_audit(f"config_file:{file_path}", "update", {"changed_keys": list(new_data.keys())})
            return {"success": True, "path": file_path, "timestamp": _now_iso()}
        else:
            raise HTTPException(status_code=500, detail="Failed to save config file")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "update config file"))


@config_router.get("/config/workers", summary="List all worker configurations")
async def list_workers():
    """List all scheduled worker configurations from config/workers/."""
    try:
        from chat_app.config_loader import list_config_files
        files = list_config_files()
        workers = [f for f in files if f["category"] == "worker"]
        return {"workers": workers, "total": len(workers), "timestamp": _now_iso()}
    except Exception as exc:
        return {"workers": [], "error": str(exc), "timestamp": _now_iso()}


@config_router.get("/config/integrations", summary="List all integration configurations")
async def list_integrations():
    """List all external integration configurations from config/integrations/."""
    try:
        from chat_app.config_loader import list_config_files
        files = list_config_files()
        integrations = [f for f in files if f["category"] == "integration"]
        return {"integrations": integrations, "total": len(integrations), "timestamp": _now_iso()}
    except Exception as exc:
        return {"integrations": [], "error": str(exc), "timestamp": _now_iso()}


# ---------------------------------------------------------------------------
# Re-export extended config router for backward compatibility
# ---------------------------------------------------------------------------
from chat_app.admin_config_helpers import config_ext_router  # noqa: E402,F401
