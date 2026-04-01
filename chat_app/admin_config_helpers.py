"""Admin Config Extended Routes — Index/field mappings, MCP servers, backup, reload, versioning.

Extracted from admin_config_routes.py to keep file sizes manageable.
Contains: index-mappings, field-mappings, MCP server CRUD, backup/restore,
reload/restart/export/import, restart-policy, apply, config versioning.

Models and helpers (_get_config_mgr, _apply_config_change, etc.) are imported
from admin_config_routes.
"""

import logging
import os

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from chat_app.auth_dependencies import require_admin
from chat_app.settings import reload_settings
from chat_app.admin_shared import (
    _append_audit,
    _arun,
    _container_cmd,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _safe_error,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

config_ext_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-config"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)

# Import helpers and models from main config routes module
from chat_app.admin_config_routes import (  # noqa: E402
    _get_config_mgr,
    _get_restart_policy,
    _apply_config_change,
    MCPServerConfigRequest,
    _RestartServiceRequest,
    ConfigRollbackRequest,
    ConfigRestoreRequest,
    ConfigSectionUpdateRequest,
    ConfigImportRequest,
)


# --- Index & Field Mappings ---

@config_ext_router.get("/config/organization/index-mappings", summary="Get index mappings")
async def get_index_mappings():
    """Get intent-to-index mappings used for NLP-to-SPL generation."""
    mgr = _get_config_mgr()
    org = mgr.get_section("organization")
    return {
        "index_mappings": org.get("index_mappings", {}),
        "timestamp": _now_iso(),
    }


@config_ext_router.patch("/config/organization/index-mappings", summary="Update index mappings")
async def update_index_mappings(body: ConfigSectionUpdateRequest):
    """Add or update intent-to-index mappings."""
    mgr = _get_config_mgr()
    data = mgr.load(force=True)
    org = data.setdefault("organization", {})
    mappings = org.setdefault("index_mappings", {})
    previous = dict(mappings)
    mappings.update(body.values)
    success = mgr.save(data, reason="update index mappings")

    if not success:
        raise HTTPException(status_code=500, detail="Failed to save config.yaml.")

    _append_audit(
        section="config.organization.index_mappings",
        action="update",
        changes=body.values,
        previous={k: previous.get(k) for k in body.values if k in previous},
    )

    await _apply_config_change("organization", auto_restart=False)
    return {"index_mappings": mappings, "timestamp": _now_iso()}


@config_ext_router.get("/config/organization/field-mappings", summary="Get field mappings")
async def get_field_mappings():
    """Get generic-to-org field name mappings."""
    mgr = _get_config_mgr()
    org = mgr.get_section("organization")
    return {
        "field_mappings": org.get("field_mappings", {}),
        "timestamp": _now_iso(),
    }


@config_ext_router.patch("/config/organization/field-mappings", summary="Update field mappings")
async def update_field_mappings(body: ConfigSectionUpdateRequest):
    """Add or update field name mappings."""
    mgr = _get_config_mgr()
    data = mgr.load(force=True)
    org = data.setdefault("organization", {})
    mappings = org.setdefault("field_mappings", {})
    previous = dict(mappings)
    mappings.update(body.values)
    success = mgr.save(data, reason="update field mappings")

    if not success:
        raise HTTPException(status_code=500, detail="Failed to save config.yaml.")

    _append_audit(
        section="config.organization.field_mappings",
        action="update",
        changes=body.values,
        previous={k: previous.get(k) for k in body.values if k in previous},
    )

    await _apply_config_change("organization", auto_restart=False)
    return {"field_mappings": mappings, "timestamp": _now_iso()}


# --- MCP Server CRUD ---

@config_ext_router.get("/config/mcp-gateway/servers", summary="List MCP servers from config")
async def list_mcp_servers():
    """List MCP servers configured in config.yaml, with fallback to mcp_registry."""
    mgr = _get_config_mgr()
    mcp = mgr.get_section("mcp_gateway")
    servers = mcp.get("servers", [])
    enabled = mcp.get("enabled", False)

    if not servers:
        try:
            from chat_app.mcp_registry import load_registry
            registry = load_registry()
            servers = registry.get("servers", [])
            enabled = registry.get("enabled", True)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[ADMIN] Failed to load MCP registry fallback: %s", exc)

    return {
        "servers": servers,
        "enabled": enabled,
        "total": len(servers),
        "source": "config" if mcp.get("servers") else "registry_fallback",
        "timestamp": _now_iso(),
    }


@config_ext_router.get("/mcp/servers", summary="List MCP servers (compatibility alias)")
async def list_mcp_servers_compat():
    """Compatibility alias for /config/mcp-gateway/servers (old path removed in v3.5)."""
    return await list_mcp_servers()


@config_ext_router.post("/config/mcp-gateway/servers", summary="Add MCP server to config")
async def add_mcp_server_to_config(body: MCPServerConfigRequest):
    """Add a new MCP server to config.yaml."""
    mgr = _get_config_mgr()
    data = mgr.load(force=True)
    mcp = data.setdefault("mcp_gateway", {})
    servers = mcp.setdefault("servers", [])

    for s in servers:
        if s.get("name") == body.name:
            raise HTTPException(status_code=409, detail=f"Server '{body.name}' already exists.")

    server = body.model_dump(exclude_none=True)
    servers.append(server)
    success = mgr.save(data, reason=f"add MCP server '{body.name}'")

    if not success:
        raise HTTPException(status_code=500, detail="Failed to save config.yaml.")

    _append_audit(section="config.mcp_gateway.servers", action="add", changes=server)
    return {"server": server, "total_servers": len(servers), "timestamp": _now_iso()}


@config_ext_router.delete("/config/mcp-gateway/servers/{name}", summary="Remove MCP server from config")
async def remove_mcp_server_from_config(name: str):
    """Remove an MCP server from config.yaml."""
    mgr = _get_config_mgr()
    data = mgr.load(force=True)
    mcp = data.get("mcp_gateway", {})
    servers = mcp.get("servers", [])

    original_count = len(servers)
    servers = [s for s in servers if s.get("name") != name]
    if len(servers) == original_count:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found.")

    mcp["servers"] = servers
    success = mgr.save(data, reason=f"remove MCP server '{name}'")

    if not success:
        raise HTTPException(status_code=500, detail="Failed to save config.yaml.")

    _append_audit(section="config.mcp_gateway.servers", action="remove", changes={"name": name})
    return {"removed": name, "remaining": len(servers), "timestamp": _now_iso()}


# --- Config Backup/Restore ---

@config_ext_router.get("/config/backups", summary="List config backups")
async def list_config_backups(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List available config.yaml backups."""
    mgr = _get_config_mgr()
    backups = mgr.get_backups()
    backup_dir = str(Path(mgr._config_path).parent / "config_backups")
    total = len(backups)
    page = backups[offset:offset + limit]
    return {
        "status": "ok",
        "backups": page,
        "total": total,
        "backup_directory": backup_dir,
        "message": (
            f"{total} backup(s) available"
            if backups
            else "No backups yet. Use POST /api/admin/config/backup to create one."
        ),
        "timestamp": _now_iso(),
    }


@config_ext_router.get("/config/backup", summary="List config backups (singular alias)")
async def list_config_backups_alias():
    """Alias for GET /config/backups — returns available backups."""
    return await list_config_backups()


@config_ext_router.post("/config/backup", summary="Create a config backup")
async def create_config_backup():
    """Manually create a backup of the current config.yaml."""
    mgr = _get_config_mgr()
    backup_path = mgr._backup()
    if backup_path:
        _append_audit(section="config", action="manual_backup", changes={"file": str(backup_path)})
        return {"status": "ok", "file": str(backup_path), "timestamp": _now_iso()}
    return {"status": "error", "message": "No config file to backup", "timestamp": _now_iso()}


@config_ext_router.post("/config/restore", summary="Restore config from backup")
async def restore_config(body: ConfigRestoreRequest):
    """Restore config.yaml from a backup file."""
    mgr = _get_config_mgr()
    success, message = mgr.restore_backup(body.filename)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    _append_audit(
        section="config",
        action="restore",
        changes={"filename": body.filename},
    )

    return {"message": message, "filename": body.filename, "timestamp": _now_iso()}


# --- Config Reload / Restart / Export / Import ---

@config_ext_router.post("/config/reload", summary="Force reload settings from config.yaml")
async def reload_config():
    """Force reload all settings from config.yaml into memory."""
    try:
        reload_settings()
        logger.info("[CONFIG] Settings force-reloaded via admin API")
        _append_audit(section="config", action="reload", changes={"trigger": "admin_api"})
        return {
            "success": True,
            "message": "Settings reloaded from config.yaml",
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[CONFIG] Force-reload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=_safe_error(exc, "config reload"))


@config_ext_router.post("/config/restart-service", summary="Restart a specific container service")
async def restart_service(body: _RestartServiceRequest):
    """Restart a specific container service by name."""
    svc = body.service.strip()
    if not svc:
        raise HTTPException(status_code=400, detail="Service name must not be empty.")

    runtime = _container_cmd()
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail="No container runtime (podman/docker) available inside this container. "
                   f"Restart from host: podman restart {svc}",
        )

    try:
        proc = await _arun(
            [runtime, "restart", svc],
            capture_output=True, text=True, timeout=120,
        )
        restarted = proc.returncode == 0
        _append_audit(
            section="config.service",
            action="restart",
            changes={"service": svc, "restarted": restarted, "runtime": runtime},
        )
        if restarted:
            logger.info("[CONFIG] Restarted service '%s' via %s", svc, runtime)
            return {
                "success": True,
                "service": svc,
                "restarted": True,
                "timestamp": _now_iso(),
            }
        else:
            detail = proc.stderr.strip()[:300] if proc.stderr else "unknown error"
            raise HTTPException(
                status_code=500,
                detail=f"Failed to restart '{svc}': {detail}",
            )
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, f"restart {svc}"))


@config_ext_router.post("/config/export", summary="Export full config")
async def export_config():
    """Export the full config.yaml as JSON with metadata."""
    mgr = _get_config_mgr()
    config_data = mgr.get_full_config()
    version = config_data.get("version", "unknown")
    return {
        "config": config_data,
        "metadata": {
            "version": version,
            "sections_count": len(config_data),
            "sections": list(config_data.keys()),
            "config_path": mgr.config_path,
        },
        "config_path": mgr.config_path,
        "timestamp": _now_iso(),
    }


@config_ext_router.post("/config/import", summary="Import full config")
async def import_config(body: ConfigImportRequest):
    """Import a complete config.yaml (backs up current first)."""
    mgr = _get_config_mgr()

    backups_before = {b["filename"] for b in mgr.get_backups()}
    success, message = mgr.import_config(body.config)

    if not success:
        raise HTTPException(status_code=500, detail=message)

    backups_after = mgr.get_backups()
    new_backups = [b for b in backups_after if b["filename"] not in backups_before]
    backup_id = new_backups[0]["filename"] if new_backups else None

    _append_audit(
        section="config",
        action="import",
        changes={"sections": list(body.config.keys()), "backup_id": backup_id},
    )

    apply_result = {"settings_reloaded": False, "containers_restarted": [], "restart_needed": []}
    try:
        reload_settings()
        apply_result["settings_reloaded"] = True
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[ADMIN] Failed to reload settings after config import: %s", exc)

    if body.auto_restart:
        compose_dir = "/app" if os.path.exists("/app/docker-compose.yml") else str(Path(__file__).resolve().parent.parent)
        try:
            proc = await _arun(
                ["docker", "compose", "restart"],
                capture_output=True, text=True, timeout=120,
                cwd=compose_dir,
            )
            if proc.returncode == 0:
                apply_result["containers_restarted"] = ["all"]
            else:
                apply_result["restart_needed"] = ["all"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("[ADMIN] Failed to restart containers after config import: %s", exc)
            apply_result["restart_needed"] = ["all"]

    return {
        "success": True,
        "message": message,
        "backup_id": backup_id,
        "sections_imported": list(body.config.keys()),
        "applied": apply_result,
        "timestamp": _now_iso(),
    }


@config_ext_router.get("/config/restart-policy", summary="Get restart policies for all config sections")
async def get_restart_policies():
    """Show which config sections require hot_reload, app_restart, or full_restart."""
    mgr = _get_config_mgr()
    data = mgr.load()
    policies = {}
    for section in data:
        policies[section] = _get_restart_policy(section)
    return {
        "policies": policies,
        "actions_explained": {
            "hot_reload": "Settings take effect immediately — no container restart needed",
            "app_restart": "Requires restarting the app container (chat_ui_app)",
            "full_restart": "Requires restarting multiple containers",
            "no_action": "Informational only",
        },
        "timestamp": _now_iso(),
    }


@config_ext_router.post("/config/apply", summary="Apply pending config changes")
async def apply_config_changes(
    sections: Optional[List[str]] = Query(None, description="Sections to apply (empty = all)"),
    restart: bool = Query(False, description="Also restart affected containers"),
):
    """Reload settings and optionally restart containers for the specified sections."""
    results = {}

    try:
        reload_settings()
        results["settings_reloaded"] = True
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        results["settings_reloaded"] = False
        results["reload_error"] = str(exc)

    if not sections:
        mgr = _get_config_mgr()
        sections = list(mgr.load().keys())

    services_to_restart = set()
    section_policies = {}
    for section in sections:
        policy = _get_restart_policy(section)
        section_policies[section] = policy
        if policy["action"] in ("app_restart", "full_restart"):
            services_to_restart.update(policy.get("services", []))

    results["section_policies"] = section_policies
    results["containers_restarted"] = []
    results["restart_needed"] = list(services_to_restart) if not restart else []

    if restart and services_to_restart:
        compose_dir = "/app" if os.path.exists("/app/docker-compose.yml") else str(Path(__file__).resolve().parent.parent)
        for svc in sorted(services_to_restart):
            try:
                proc = await _arun(
                    ["docker", "compose", "restart", svc],
                    capture_output=True, text=True, timeout=60,
                    cwd=compose_dir,
                )
                if proc.returncode == 0:
                    results["containers_restarted"].append(svc)
                else:
                    results["restart_needed"].append(svc)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning("[ADMIN] Failed to restart container service: %s", exc)
                results["restart_needed"].append(svc)

    results["timestamp"] = _now_iso()
    return results


# --- Config Versioning ---

@config_ext_router.get("/config/versions", summary="List config change history")
async def get_config_versions(
    section: Optional[str] = Query(None, description="Filter by section name"),
    limit: int = Query(50, ge=1, le=500, description="Max commits to return"),
    offset: int = Query(default=0, ge=0),
):
    """Return the version history of config changes with diffs."""
    try:
        from chat_app.config_versioning import get_config_version_store
        store = get_config_version_store()
        all_history = store.get_history(section=section, limit=500)
        total = len(all_history)
        page = all_history[offset:offset + limit]
        return {
            "commits": page,
            "total": total,
            "head": store.head,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, _safe_error(exc, "config versions"))


@config_ext_router.get("/config/versions/{commit_id}", summary="Get a specific config commit")
async def get_config_version_detail(commit_id: str):
    """Return a specific config commit with its diff and snapshot."""
    try:
        from chat_app.config_versioning import get_config_version_store
        store = get_config_version_store()
        commit = store.get_commit(commit_id)
        if not commit:
            raise HTTPException(404, f"Commit '{commit_id}' not found")
        return {"commit": commit, "timestamp": _now_iso()}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, _safe_error(exc, "config version detail"))


@config_ext_router.post("/config/rollback/{commit_id}", summary="Rollback config to a specific commit")
async def rollback_config_version(commit_id: str, body: ConfigRollbackRequest):
    """Rollback a config section to the state captured at a specific commit."""
    try:
        from chat_app.config_versioning import get_config_version_store
        store = get_config_version_store()

        commit = store.get_commit(commit_id)
        if not commit:
            raise HTTPException(404, f"Commit '{commit_id}' not found")

        snapshot = store.rollback(commit_id)
        if not snapshot:
            raise HTTPException(404, f"No snapshot available for commit '{commit_id}'")

        section = snapshot["section"]
        value = snapshot["value"]

        mgr = _get_config_mgr()
        previous = mgr.get_section(section)
        success, updated = mgr.replace_section(section, value)
        if not success:
            raise HTTPException(500, "Failed to apply rollback")

        _append_audit(
            section=f"config.{section}",
            action="rollback",
            changes={"rollback_to": commit_id, "section": section},
            previous=previous,
        )

        apply_result = await _apply_config_change(section, auto_restart=body.auto_restart)

        return {
            "success": True,
            "section": section,
            "rolled_back_to": commit_id,
            "apply_result": apply_result,
            "timestamp": _now_iso(),
        }
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, _safe_error(exc, "config rollback"))
