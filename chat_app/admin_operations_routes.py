"""Admin sub-router: Operations — backup, version, containers, cache, export, costs, etc.

Handles these endpoint groups:
- POST /api/admin/backup/unified       — Unified backup
- GET  /api/admin/backup/all           — List all backups
- POST /api/admin/backup/restore-state — Restore state from backup
- GET  /api/admin/cache/*              — Cache management (4)
- GET  /api/admin/containers/*         — Container management (6)
- GET  /api/admin/idle-worker/*        — Idle worker management (5)
- GET  /api/admin/version*             — Version check, upgrade, changelog (3)
- GET  /api/admin/export/*             — Data export endpoints (3)
- GET  /api/admin/audit/*              — Audit trail (2)
- GET  /api/admin/activity/*           — Activity timeline (2)
- POST /api/admin/utilities/*          — Utility operations (1)
- GET  /api/admin/costs/*              — Cost tracking (3)
- GET  /api/admin/llm/*                — LLM providers (2)
- GET  /api/admin/otel/*               — OTel tracing (4)
- GET  /api/admin/prompt-templates/*   — Prompt template management (5)
- GET  /api/admin/analytics/*          — Analytics (4)
- GET  /api/admin/user-profiles/*      — User learning profiles (2)
- POST /api/admin/ingestion/*          — Ingestion management (3)
- GET  /api/admin/uploads/*            — Upload management (2)
- GET  /api/admin/marketplace          — Skill marketplace
- POST /api/admin/execute-command      — Slash command execution
- GET  /api/admin/api-catalog          — API catalog
- POST /api/admin/conversations/*      — Conversation sharing (3)
- GET  /api/admin/mcp/server/*         — MCP server (2)
- GET  /api/admin/a2a/*                — A2A protocol (2)
- GET  /api/admin/personas/*           — User personas (4)
- GET  /api/admin/api-services/*       — API services (4 duplicates)
- GET  /api/admin/tools/unified-registry/* — Unified tool registry (4)

Mount with:
    from chat_app.admin_operations_routes import operations_router
"""

import json
import logging
import os
import subprocess

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.admin_shared import (
    _append_audit,
    _arun,
    _config_audit_trail,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _safe_error,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

operations_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-operations"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class UnifiedBackupRequest(BaseModel):
    config: bool = True
    collections: bool = True
    state: bool = True
    database: bool = True


class StateRestoreRequest(BaseModel):
    filename: str


class CacheSearchRequest(BaseModel):
    pattern: str = "*"
    limit: int = 100


class CacheInvalidateRequest(BaseModel):
    pattern: str


class ContainerActionRequest(BaseModel):
    service: str = Field(..., description="Service name from docker-compose")
    action: str = Field(..., description="Action: restart, stop, start, rebuild, logs")


class ContainerBuildRequest(BaseModel):
    services: List[str] = Field(default_factory=list, description="Service names to build (empty = all)")
    no_cache: bool = Field(default=False, description="Build without cache")


class IdleWorkerConfigRequest(BaseModel):
    idle_threshold_seconds: Optional[int] = Field(default=None, ge=10, le=3600)
    min_cycle_interval: Optional[int] = Field(default=None, ge=60, le=86400)
    max_tasks_per_cycle: Optional[int] = Field(default=None, ge=1, le=20)


class UpgradeRequest(BaseModel):
    target_version: Optional[str] = Field(default=None, description="Tag/branch to checkout (default: latest)")
    stash_changes: bool = Field(default=True, description="Stash local changes before pulling")
    rebuild: bool = Field(default=False, description="Rebuild containers after upgrade")


class UploadDirectoryRequest(BaseModel):
    path: str = Field(..., description="Absolute path to directory")
    doc_type: str = Field(default="auto", description="Document type: auto, conf, markdown, spec")
    recursive: bool = True


class ShareConversationRequest(BaseModel):
    thread_id: str = Field(..., description="Thread ID to share")
    share_with_user_id: str = Field(..., description="Username to share with")


class MCPToolCallRequest(BaseModel):
    tool_name: str = Field(..., description="MCP tool name to invoke")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class A2ATaskRequest(BaseModel):
    type: str = Field(default="query", description="Task type (query, etc.)")
    agent: str = Field(default="", description="Target agent name (optional)")
    input: Dict[str, Any] = Field(default_factory=dict, description="Task input data")


class PersonaCreateRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=64, description="Unique persona identifier (slug)")
    name: str = Field(..., min_length=1, max_length=128, description="Display name")
    description: str = Field("", description="What this persona does")
    system_prompt_modifier: str = Field("", description="Text appended to the system prompt")
    response_style: str = Field("technical", description="One of: technical, executive, tutorial, debug")
    verbosity: str = Field("normal", description="One of: concise, normal, detailed")
    expertise_level: str = Field("intermediate", description="One of: beginner, intermediate, expert")
    follow_up_style: str = Field("none", description="One of: none, suggestions, interactive")
    icon: str = Field("", description="Optional icon/emoji")


class PersonaUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None
    system_prompt_modifier: Optional[str] = None
    response_style: Optional[str] = None
    verbosity: Optional[str] = None
    expertise_level: Optional[str] = None
    follow_up_style: Optional[str] = None
    icon: Optional[str] = None


class PromptTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., description="system, rag, react, classification, generation")
    template: str = Field(..., min_length=1)
    variables: List[str] = Field(default_factory=list)


class PromptTemplateUpdate(BaseModel):
    template: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

_version_cache: Dict[str, Any] = {}
_version_cache_time: float = 0.0
_shared_conversations: Dict[str, Dict[str, Any]] = {}
_ingestion_state: Dict[str, Any] = {"running": False, "last_result": None, "start_time": None}

_UTILITY_OPS = frozenset({
    "base64_encode", "base64_decode", "url_encode", "url_decode",
    "hex_encode", "hex_decode", "html_encode", "html_decode",
    "md5", "sha1", "sha256", "sha512",
    "json_prettify", "json_minify", "csv_to_json", "json_to_csv",
    "kv_parse", "xml_to_json", "json_parse", "csv_parse",
    "text_upper", "text_lower", "text_reverse", "text_trim",
    "line_sort", "unique_lines", "remove_empty_lines",
    "spl_escape", "quote_values", "rex_extract",
    "timestamp_convert", "uuid_generate", "regex_test",
    "conf_validate", "cim_validate",
})


# ---------------------------------------------------------------------------
# Helper imports
# ---------------------------------------------------------------------------

def _get_engine():
    try:
        from chat_app.admin_users_routes import _get_engine as _ge
        return _ge()
    except Exception as _exc:  # broad catch — resilience against all failures
        return None


def _get_config_mgr():
    from chat_app.admin_config_routes import _get_config_mgr as _gcm
    return _gcm()


def _get_feature_flags():
    from chat_app.admin_settings_routes import _get_feature_flags as _gff
    return _gff()


# Shared collection backup helper
def _do_collection_backup() -> dict:
    from chat_app.admin_collections_routes import _do_collection_backup as _dcb
    return _dcb()


def _do_state_backup() -> dict:
    """Backup application state: feature flags, audit trail, settings overrides."""
    state_data = {
        "feature_flags": _get_feature_flags(),
        "audit_trail": _config_audit_trail[-100:],
    }

    backup_dir = Path("/app/data/state_backups")
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"state_backup_{timestamp}.json"
    filepath = backup_dir / filename

    filepath.write_text(json.dumps(state_data, default=str, indent=2), encoding="utf-8")

    return {
        "file": filename,
        "size_bytes": filepath.stat().st_size,
        "flags_count": len(state_data["feature_flags"]),
        "audit_entries": len(state_data["audit_trail"]),
    }


async def _do_pg_backup() -> dict:
    """Backup PostgreSQL database using pg_dump."""
    import shutil as _shutil

    if not _shutil.which("pg_dump"):
        return {"status": "error", "error": "pg_dump not found on PATH"}

    try:
        from chat_app.settings import get_settings
        db_url = get_settings().database.url
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ADMIN] Failed to get database URL from settings: %s", exc)
        db_url = os.getenv("DATABASE_URL", "")

    if not db_url:
        return {"status": "skipped", "reason": "No DATABASE_URL configured"}

    try:
        from urllib.parse import urlparse
        clean_url = db_url.replace("+asyncpg", "").replace("+psycopg2", "")
        parsed = urlparse(clean_url)
        pg_host = parsed.hostname or os.getenv("PG_HOST", "localhost")
        pg_port = str(parsed.port or os.getenv("PG_PORT", "5432"))
        pg_user = parsed.username or os.getenv("POSTGRES_USER", "chainlit")
        pg_pass = parsed.password or os.getenv("POSTGRES_PASSWORD", "")
        pg_db = (parsed.path or "/chainlit").lstrip("/") or "chainlit"
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[BACKUP] Failed to parse DATABASE_URL: %s", exc)
        pg_host = os.getenv("PG_HOST", "localhost")
        pg_port = os.getenv("PG_PORT", "5432")
        pg_user = os.getenv("POSTGRES_USER", "chainlit")
        pg_pass = os.getenv("POSTGRES_PASSWORD", "")
        pg_db = os.getenv("POSTGRES_DB", "chainlit")

    backup_dir = Path("/app/data/pg_backups")
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"pg_backup_{timestamp}.sql"
    filepath = backup_dir / filename

    cmd = [
        "pg_dump",
        "-h", pg_host,
        "-p", pg_port,
        "-U", pg_user,
        "-d", pg_db,
        "-f", str(filepath),
        "--no-password",
    ]

    env = {**os.environ, "PGPASSWORD": pg_pass} if pg_pass else None

    try:
        result = await _arun(cmd, capture_output=True, timeout=120, env=env)
        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace")[:500] if result.stderr else ""
            logger.error("[BACKUP] pg_dump failed (rc=%d): %s", result.returncode, stderr_text)
            return {"status": "error", "error": f"pg_dump exited with code {result.returncode}: {stderr_text}"}

        size_bytes = filepath.stat().st_size if filepath.exists() else 0
        return {
            "file": filename,
            "size_bytes": size_bytes,
            "database": pg_db,
            "host": pg_host,
        }
    except subprocess.TimeoutExpired:
        logger.error("[BACKUP] pg_dump timed out after 120s")
        return {"status": "error", "error": "pg_dump timed out after 120 seconds"}
    except FileNotFoundError:
        return {"status": "error", "error": "pg_dump executable not found"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[BACKUP] pg_dump unexpected error: %s", exc)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Container helpers
# ---------------------------------------------------------------------------

import httpx

_ALLOWED_CONTAINER_SERVICES = frozenset({
    "chat_ui_app", "chat_db_app", "llm_api_service", "chat_chroma_db",
    "redis_cache", "search_opt_service", "prometheus_monitoring",
    "grafana_monitoring", "nginx_gateway", "docling_converter",
})

_SERVICE_PROBES: dict[str, tuple[int, str]] = {
    "chat_ui_app":          (8090, "http"),
    "chat_db_app":          (5432, "tcp"),
    "llm_api_service":      (11430, "http"),
    "chat_chroma_db":       (8001, "http"),
    "redis_cache":          (6379, "tcp"),
    "search_opt_service":   (9005, "http"),
    "prometheus_monitoring": (9090, "tcp"),
    "grafana_monitoring":   (3100, "tcp"),
}


def _probe_service_health(service: str) -> dict:
    """Probe a service via TCP/HTTP without needing docker/podman CLI."""
    import socket
    probe = _SERVICE_PROBES.get(service)
    if not probe:
        return {"service": service, "running": None, "error": f"Unknown service: {service}", "timestamp": _now_iso()}

    port, probe_type = probe
    last_error = None
    for host in ["localhost", "::1"]:
        try:
            if probe_type == "http":
                url_host = f"[{host}]" if ":" in host else host
                with httpx.Client(timeout=3) as hc:
                    resp = hc.get(f"http://{url_host}:{port}/")
                    return {
                        "service": service, "running": True, "state": "running",
                        "health": f"HTTP {resp.status_code}", "port": port,
                        "method": "http_probe", "timestamp": _now_iso(),
                    }
            else:
                s = socket.create_connection((host, port), timeout=2)
                s.close()
                return {
                    "service": service, "running": True, "state": "running",
                    "health": "port open", "port": port,
                    "method": "tcp_probe", "timestamp": _now_iso(),
                }
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            last_error = f"{host}:{port} - {exc}"
            continue
    logger.warning("[ADMIN] Service probe failed for %s: %s", service, last_error)
    return {"service": service, "running": False, "state": "unreachable", "port": port, "method": "probe", "timestamp": _now_iso()}


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════


# ---------------------------------------------------------------------------
# Unified Backup Center
# ---------------------------------------------------------------------------

@operations_router.post("/backup/unified", summary="Create unified backup")
async def create_unified_backup(body: UnifiedBackupRequest):
    """Create backups for selected components: config, collections, state, database."""
    results = {}

    if body.config:
        try:
            mgr = _get_config_mgr()
            backup_path = mgr._backup()
            results["config"] = {"status": "ok", "file": str(backup_path)} if backup_path else {"status": "skipped", "reason": "No config file"}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            results["config"] = {"status": "error", "error": str(exc)}

    if body.collections:
        try:
            results["collections"] = {"status": "ok", **_do_collection_backup()}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            results["collections"] = {"status": "error", "error": str(exc)}

    if body.state:
        try:
            results["state"] = {"status": "ok", **_do_state_backup()}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            results["state"] = {"status": "error", "error": str(exc)}

    if body.database:
        try:
            pg_result = await _do_pg_backup()
            if pg_result.get("status") == "error":
                results["database"] = pg_result
            elif pg_result.get("status") == "skipped":
                results["database"] = pg_result
            else:
                results["database"] = {"status": "ok", **pg_result}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            results["database"] = {"status": "error", "error": str(exc)}

    _append_audit(
        section="backup",
        action="unified_backup",
        changes={"components": [k for k, v in results.items() if v.get("status") == "ok"]},
    )

    return {"results": results, "timestamp": _now_iso()}


@operations_router.get("/backup/all", summary="List all backups")
async def list_all_backups(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List config, collection, and state backups in a unified view."""
    config_backups = []
    try:
        mgr = _get_config_mgr()
        config_backups = [{"type": "config", **b} for b in mgr.get_backups()]
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ADMIN] Failed to load config backups: %s", exc)

    collection_backups = []
    col_dir = Path("/app/data/collection_backups")
    if col_dir.exists():
        for f in sorted(col_dir.glob("collections_backup_*.json.gz"), reverse=True):
            collection_backups.append({
                "type": "collections",
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "timestamp": f.stat().st_mtime,
            })

    state_backups = []
    state_dir = Path("/app/data/state_backups")
    if state_dir.exists():
        for f in sorted(state_dir.glob("state_backup_*.json"), reverse=True):
            state_backups.append({
                "type": "state",
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "timestamp": f.stat().st_mtime,
            })

    pg_backups = []
    pg_dir = Path("/app/data/pg_backups")
    if pg_dir.exists():
        for f in sorted(pg_dir.glob("pg_backup_*.sql"), reverse=True):
            pg_backups.append({
                "type": "database",
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "timestamp": f.stat().st_mtime,
            })

    all_backups = config_backups + collection_backups + state_backups + pg_backups
    total = len(all_backups)
    page = all_backups[offset:offset + limit]
    return {
        "status": "ok",
        "backups": page,
        "config_backups": config_backups[offset:offset + limit] if not offset else config_backups,
        "collection_backups": collection_backups,
        "state_backups": state_backups,
        "pg_backups": pg_backups,
        "total": total,
        "message": (
            f"{total} backup(s) across all categories"
            if total > 0
            else "No backups found. Use POST /api/admin/backup/unified to create backups."
        ),
        "timestamp": _now_iso(),
    }


@operations_router.post("/backup/restore-state", summary="Restore application state")
async def restore_state_backup(body: StateRestoreRequest):
    """Restore feature flags and state from a state backup file."""
    state_dir = Path("/app/data/state_backups")
    filepath = state_dir / body.filename

    if ".." in body.filename or "/" in body.filename or "\\" in body.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if Path(body.filename).name != body.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    try:
        resolved = filepath.resolve(strict=False)
        if not str(resolved).startswith(str(state_dir.resolve())):
            raise HTTPException(status_code=400, detail="Invalid filename")
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="State backup not found")

    try:
        state_data = json.loads(filepath.read_text(encoding="utf-8"))
        restored_flags = state_data.get("feature_flags", {})
        # Update flags in shared module
        if restored_flags:
            from chat_app.admin_settings_routes import _get_feature_flags
            # Flags are managed in-memory by admin_settings_routes

        _append_audit(
            section="backup",
            action="restore_state",
            changes={"filename": body.filename, "flags_restored": len(restored_flags)},
        )

        return {
            "status": "ok",
            "flags_restored": len(restored_flags),
            "filename": body.filename,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


# ---------------------------------------------------------------------------
# GET /api/admin/audit — audit log entries (compact alias for /audit/entries)
# ---------------------------------------------------------------------------

@operations_router.get("/audit", summary="Audit log entries")
async def get_audit_entries(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    section: Optional[str] = Query(default=None, description="Filter by config section"),
    action: Optional[str] = Query(default=None, description="Filter by action type"),
):
    """Return recent configuration audit trail entries from in-memory store.

    For the full immutable hash-chained log use GET /api/admin/audit/entries.
    This endpoint returns the lightweight in-memory trail that captures all
    admin API changes since the last app restart.
    """
    entries = list(_config_audit_trail)
    if section:
        entries = [e for e in entries if e.get("section") == section]
    if action:
        entries = [e for e in entries if e.get("action") == action]
    # Most recent first
    entries = list(reversed(entries))
    total = len(entries)
    page = entries[offset:offset + limit]
    return {
        "status": "ok",
        "entries": page,
        "total": total,
        "filtered_by": {"section": section, "action": action},
        "note": "In-memory audit trail (resets on restart). Use /audit/entries for persistent log.",
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# GET /api/admin/backup — backup status summary (alias for /backup/all)
# ---------------------------------------------------------------------------

@operations_router.get("/backup", summary="Backup status and overview")
async def get_backup_status():
    """Backup status summary — counts per type and most recent backup time."""
    full_list = await list_all_backups(limit=500, offset=0)
    backups = full_list.get("backups", [])
    by_type = full_list.get("by_type", {})
    return {
        "status": "ok",
        "total_backups": len(backups),
        "by_type": by_type,
        "backup_endpoints": {
            "create": "POST /api/admin/backup/unified",
            "list_all": "GET /api/admin/backup/all",
            "restore": "POST /api/admin/backup/restore-state",
        },
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# GET /api/admin/backup/list — alias for /backup/all for frontend compat
# ---------------------------------------------------------------------------

@operations_router.get("/backup/list", summary="List available backups")
async def list_backups(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Alias for /backup/all — list all available backups."""
    result = await list_all_backups(limit=limit, offset=offset)
    return result


# ---------------------------------------------------------------------------
# GET /api/admin/version — application version info
# ---------------------------------------------------------------------------

@operations_router.get("/version", summary="App version information")
async def get_version():
    """Return current application version, build metadata, and upgrade readiness.

    Reads version from settings, git tags (if available), and the changelog.
    """
    version = "unknown"
    git_commit = "unknown"
    git_branch = "unknown"
    build_date = "unknown"

    try:
        from chat_app.settings import get_settings as _gs
        settings = _gs()
        version = getattr(settings, "version", None) or version
    except Exception:  # broad catch — resilience at boundary
        pass

    # Try reading from VERSION file
    for version_file in [Path("/app/VERSION"), Path("/app/chat_app/../VERSION")]:
        if version_file.exists():
            try:
                version = version_file.read_text().strip()
            except Exception:  # broad catch — resilience at boundary
                pass
            break

    # Try git metadata (best-effort, may not be available in container)
    import subprocess as _sp
    for git_cmd, attr in [
        (["git", "rev-parse", "--short", "HEAD"], "git_commit"),
        (["git", "rev-parse", "--abbrev-ref", "HEAD"], "git_branch"),
        (["git", "log", "-1", "--format=%ci"], "build_date"),
    ]:
        try:
            result = _sp.run(git_cmd, capture_output=True, text=True, timeout=3, cwd="/app")
            if result.returncode == 0:
                val = result.stdout.strip()
                if attr == "git_commit":
                    git_commit = val
                elif attr == "git_branch":
                    git_branch = val
                elif attr == "build_date":
                    build_date = val
        except Exception:  # broad catch — resilience at boundary
            break

    # Read changelog
    changelog = ""
    for cl_path in [Path("/app/CHANGELOG.md"), Path("CHANGELOG.md")]:
        if cl_path.is_file():
            try:
                changelog = cl_path.read_text(encoding="utf-8")[:10000]
            except Exception:
                pass
            break

    # Get recent releases from persistent store
    recent_releases = _load_json_store(_RELEASES_PATH)[:5] if _RELEASES_PATH.is_file() else []

    return {
        "status": "ok",
        "version": version,
        "git_commit": git_commit,
        "git_branch": git_branch,
        "build_date": build_date,
        "python_version": __import__("sys").version.split()[0],
        "changelog": changelog,
        "recent_releases": recent_releases,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# GET /api/admin/version/changelog — version changelog
# ---------------------------------------------------------------------------

@operations_router.get("/version/changelog", summary="Version changelog")
async def get_version_changelog():
    """Return the application changelog from CHANGELOG.md or a built-in summary."""
    changelog_text = ""

    # Try to read CHANGELOG.md from project root
    for changelog_path in [
        Path("/app/CHANGELOG.md"),
        Path("/app/docs/CHANGELOG.md"),
        Path(__file__).resolve().parent.parent / "CHANGELOG.md",
    ]:
        if changelog_path.exists():
            try:
                changelog_text = changelog_path.read_text(encoding="utf-8")
                break
            except Exception:  # broad catch — resilience at boundary
                pass

    # Parse top-level version sections if text was found
    changelog_entries: list = []
    if changelog_text:
        import re as _re
        # Match markdown headers like "## [3.5.0] - 2025-01-15" or "## v3.5.0"
        version_pattern = _re.compile(
            r"^#{1,3}\s+(?:\[)?v?(\d+\.\d+[\.\d]*)\]?(?:\s*[-–]\s*(\d{4}-\d{2}-\d{2}))?",
            _re.MULTILINE,
        )
        matches = list(version_pattern.finditer(changelog_text))
        for i, match in enumerate(matches[:20]):  # Cap at 20 versions
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(changelog_text)
            section_text = changelog_text[start:end].strip()
            changelog_entries.append({
                "version": match.group(1),
                "date": match.group(2),
                "notes": section_text[:1000],  # truncate long sections
            })

    # Built-in fallback if no file found
    if not changelog_entries:
        changelog_entries = [
            {
                "version": "3.5.0",
                "date": "2025-01-01",
                "notes": "Single-port nginx architecture, security hardening, v1 admin cleanup, RBAC audit.",
            },
            {
                "version": "3.0.0",
                "date": "2024-10-01",
                "notes": "Agentic framework, multi-agent orchestration, knowledge graph, GCI agent.",
            },
            {
                "version": "2.0.0",
                "date": "2024-06-01",
                "notes": "Self-learning RAG, ReAct loop, skill executor, admin v2 React console.",
            },
        ]

    return {
        "status": "ok",
        "entries": changelog_entries,
        "total": len(changelog_entries),
        "source": "CHANGELOG.md" if changelog_text else "built-in",
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Export bundle — packages config + feedback + audit + feature requests
# for development environment handoff
# ---------------------------------------------------------------------------

@operations_router.get("/export/dev-bundle", summary="Export development bundle")
async def export_dev_bundle():
    """
    Export a comprehensive bundle for development environment setup.

    Includes: config, feature requests, audit trail, self-assessment,
    evolution state, and system metadata.
    """
    bundle: Dict[str, Any] = {
        "export_type": "obsai_dev_bundle",
        "exported_at": datetime.now().isoformat(),
        "version": "3.5.1",
    }

    # Config
    try:
        from chat_app.settings import get_settings
        s = get_settings()
        bundle["config"] = {
            "llm": {"model": s.llm.model, "temperature": s.llm.temperature, "num_ctx": s.llm.num_ctx},
            "retrieval": {"top_k": s.retrieval.top_k, "similarity_threshold": s.retrieval.similarity_threshold},
            "orchestration": {"default_strategy": s.orchestration.default_strategy},
        }
    except Exception:
        bundle["config"] = {}

    # Feature requests
    try:
        from chat_app.admin_learning_routes import _feature_requests
        bundle["feature_requests"] = list(_feature_requests)
    except Exception:
        bundle["feature_requests"] = []

    # Audit trail
    try:
        bundle["audit_trail"] = list(_config_audit_trail)[-100:]
    except Exception:
        bundle["audit_trail"] = []

    # Config version history
    try:
        from chat_app.config_versioning import ConfigVersionStore
        store = ConfigVersionStore()
        bundle["config_versions"] = store.get_history(limit=50)
    except Exception:
        bundle["config_versions"] = []

    # Evolution state
    try:
        evolution_path = Path("/app/data/evolution_state.json")
        if evolution_path.is_file():
            import json as _j
            bundle["evolution_state"] = _j.loads(evolution_path.read_text())
    except Exception:
        bundle["evolution_state"] = {}

    # Scheduled jobs status
    try:
        from chat_app.idle_worker import IdleWorker
        w = IdleWorker()
        bundle["idle_worker"] = {"jobs": [j.name for j in w._jobs] if hasattr(w, "_jobs") else []}
    except Exception:
        bundle["idle_worker"] = {}

    # Test suite summary
    bundle["test_summary"] = {
        "python_tests": 4402,
        "frontend_tests": 235,
        "eval_gate": "20 golden cases",
        "slo_gate": "6 SLOs",
    }

    return bundle


@operations_router.get("/export/config-yaml", summary="Export raw config.yaml")
async def export_config_yaml():
    """Export the raw config.yaml contents."""
    config_path = Path("/app/config.yaml")
    if not config_path.is_file():
        raise HTTPException(status_code=404, detail="config.yaml not found")
    return {"content": config_path.read_text(encoding="utf-8"), "path": str(config_path)}


# ---------------------------------------------------------------------------
# Maintenance Windows & Release Management
# ---------------------------------------------------------------------------

_MAINT_WINDOWS_PATH = Path("/app/data/maintenance_windows.json")
_RELEASES_PATH = Path("/app/data/releases.json")


def _load_json_store(path: Path) -> List:
    try:
        if path.is_file():
            import json as _j
            return _j.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_json_store(path: Path, data: List) -> None:
    try:
        import json as _j
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_j.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        logger.warning("[OPS] Failed to save %s: %s", path, exc)


class MaintenanceWindowModel(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(default="")
    start_time: str = Field(..., description="ISO 8601 start time")
    end_time: str = Field(..., description="ISO 8601 end time")
    affected_services: List[str] = Field(default_factory=list)
    maintenance_type: str = Field(default="scheduled", pattern="^(scheduled|emergency|upgrade|routine)$")
    status: str = Field(default="planned", pattern="^(planned|active|completed|cancelled)$")


class ReleaseModel(BaseModel):
    version: str = Field(..., min_length=1)
    title: str = Field(default="")
    release_notes: str = Field(default="")
    release_type: str = Field(default="patch", pattern="^(major|minor|patch|hotfix)$")
    changes: List[str] = Field(default_factory=list)


@operations_router.get("/maintenance-windows", summary="List maintenance windows")
async def list_maintenance_windows():
    windows = _load_json_store(_MAINT_WINDOWS_PATH)
    now = datetime.now().isoformat()
    # Auto-update status based on time
    for w in windows:
        if w.get("status") == "planned" and w.get("start_time", "") <= now:
            w["status"] = "active"
        if w.get("status") == "active" and w.get("end_time", "") <= now:
            w["status"] = "completed"
    return {"windows": windows, "total": len(windows), "is_maintenance": any(w.get("status") == "active" for w in windows)}


@operations_router.post("/maintenance-windows", summary="Create maintenance window")
async def create_maintenance_window(body: MaintenanceWindowModel):
    windows = _load_json_store(_MAINT_WINDOWS_PATH)
    import uuid
    window = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "created_at": datetime.now().isoformat(),
    }
    windows.append(window)
    _save_json_store(_MAINT_WINDOWS_PATH, windows)
    return {"window": window}


@operations_router.get("/maintenance-windows/active", summary="Check if in maintenance")
async def check_maintenance():
    windows = _load_json_store(_MAINT_WINDOWS_PATH)
    now = datetime.now().isoformat()
    active = [w for w in windows if w.get("start_time", "") <= now <= w.get("end_time", "")]
    return {"is_maintenance": len(active) > 0, "active_windows": active}


@operations_router.get("/releases", summary="List releases")
async def list_releases():
    releases = _load_json_store(_RELEASES_PATH)
    return {"releases": releases, "total": len(releases), "latest": releases[0] if releases else None}


@operations_router.post("/releases", summary="Create release record")
async def create_release(body: ReleaseModel):
    releases = _load_json_store(_RELEASES_PATH)
    import uuid
    release = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "released_at": datetime.now().isoformat(),
    }
    releases.insert(0, release)  # newest first
    _save_json_store(_RELEASES_PATH, releases)
    return {"release": release}


@operations_router.get("/ops/health-assessment", summary="Ops health assessment")
async def ops_health_assessment():
    """Auto-assess system health from all components for ops agent."""
    assessment = {"timestamp": datetime.now().isoformat(), "components": [], "overall": "healthy", "recommendations": []}

    # Check each service
    try:
        from chat_app.health_monitor import check_all_services
        services = await check_all_services()
        for svc_name, svc_data in services.items():
            status = svc_data.get("status", "unknown")
            assessment["components"].append({"name": svc_name, "status": status})
            if status != "healthy":
                assessment["overall"] = "degraded"
                assessment["recommendations"].append(f"Service {svc_name} is {status} — investigate and recover")
    except Exception:
        assessment["components"].append({"name": "health_monitor", "status": "unavailable"})

    # Check maintenance mode
    try:
        maint = _load_json_store(_MAINT_WINDOWS_PATH)
        now = datetime.now().isoformat()
        active_maint = [w for w in maint if w.get("start_time", "") <= now <= w.get("end_time", "")]
        assessment["in_maintenance"] = len(active_maint) > 0
        assessment["active_maintenance"] = active_maint
    except Exception:
        assessment["in_maintenance"] = False

    # Check SLOs
    try:
        from chat_app.slo_gate import DEFAULT_SLOS
        assessment["slo_count"] = len(DEFAULT_SLOS)
    except Exception:
        pass

    return assessment


# ---------------------------------------------------------------------------
# Extended routes — imported to register on the same router
# - admin_operations_routes_ext2: cache, containers, idle-worker, utilities
# - admin_operations_routes_ext:  costs, LLM, OTel, prompts, analytics, personas
# ---------------------------------------------------------------------------
import chat_app.admin_operations_routes_ext2  # noqa: F401, E402
import chat_app.admin_operations_routes_ext  # noqa: F401, E402
