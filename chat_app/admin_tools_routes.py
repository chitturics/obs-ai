"""Admin sub-router: Tools endpoints (analyze-confs, regex, network, syslog, scripting, etc.).

Handles these endpoint groups:
- POST /api/admin/tools/analyze-confs            — Analyze Splunk confs for Cribl migration
- POST /api/admin/tools/analyze-confs/upload     — Upload btool CSV
- POST /api/admin/tools/analyze-confs/test-regex — Test regex for migration
- GET  /api/admin/tools/analyze-confs/history    — Scan history
- GET  /api/admin/tools/analyze-confs/history/{scan_id}
- POST /api/admin/tools/analyze-confs/status     — Update sourcetype status
- GET  /api/admin/tools/analyze-confs/statuses
- POST /api/admin/tools/analyze-confs/export/cribl
- POST /api/admin/tools/analyze-confs/export/checklist
- POST /api/admin/tools/network-test             — Network diagnostic
- POST /api/admin/tools/syslog-test              — Compose syslog events
- POST /api/admin/tools/regex-ai                 — AI regex assessment
- POST /api/admin/tools/regex-generate           — Generate regex from text
- POST /api/admin/tools/fs-monitor               — Filesystem monitor
- POST /api/admin/tools/ai-chat                  — AI assistant for tools
- POST /api/admin/tools/transform-ai             — AI data transform
- POST /api/admin/tools/ansible-validate         — Validate Ansible playbook
- POST /api/admin/tools/ansible-analyze          — Analyze playbook
- POST /api/admin/tools/ansible-generate         — Generate playbook
- POST /api/admin/tools/shell-analyze            — Analyze shell script
- POST /api/admin/tools/shell-generate           — Generate shell script
- POST /api/admin/tools/python-analyze           — Analyze Python script
- POST /api/admin/tools/python-generate          — Generate Python script
- POST /api/admin/tools/update-saved-search      — Update Splunk saved search
- POST /api/admin/tools/create-knowledge-object  — Create Splunk knowledge object

Mount with:
    from chat_app.admin_tools_routes import tools_router
    router.include_router(tools_router)
"""

import asyncio
import logging
import os
import uuid

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.settings import get_settings
from chat_app.admin_shared import (
    _append_audit,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _safe_error,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

tools_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-tools"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Repo paths endpoint (auto-detect configured Splunk & Cribl paths)
# ---------------------------------------------------------------------------

@tools_router.get("/tools/repo-paths", summary="Get auto-detected repo paths")
async def get_repo_paths():
    """Return configured Splunk and Cribl repo paths from settings, auto-resolved."""
    settings = get_settings()
    org_repo_root = getattr(settings.paths, 'org_repo_root', '') or ''

    # Also check ORG_REPO_ROOT env var
    env_repo = os.environ.get("ORG_REPO_ROOT", "")
    if not org_repo_root and env_repo:
        org_repo_root = env_repo

    splunk_path = ""
    cribl_path = ""

    # Build candidate list from settings + env + common paths
    repo_candidates: list = []
    if org_repo_root:
        repo_candidates.append(org_repo_root)

    repo_candidates.extend([
        "/app/shared/public/documents/repo",
        "/app/public/documents/repo",
        "/app/documents/repo",
        "/app/project/documents/repo",
    ])

    # Try upgrade_readiness repo_path
    ur_path = getattr(settings, 'upgrade_readiness', None)
    if ur_path:
        rp = getattr(ur_path, 'repo_path', '') or ''
        if rp and os.path.isdir(rp):
            splunk_path = rp

    # Find splunk and cribl subdirs from repo candidates
    for base in repo_candidates:
        if not os.path.isdir(base):
            continue
        if not splunk_path:
            s = os.path.join(base, "splunk")
            if os.path.isdir(s):
                splunk_path = s
            elif not splunk_path and os.path.isdir(base):
                # Maybe the base itself is a splunk repo
                splunk_path = base
        if not cribl_path:
            c = os.path.join(base, "cribl")
            if os.path.isdir(c):
                cribl_path = c

    return {
        "splunk_path": splunk_path,
        "cribl_path": cribl_path,
        "org_repo_root": org_repo_root,
        "splunk_exists": os.path.isdir(splunk_path) if splunk_path else False,
        "cribl_exists": os.path.isdir(cribl_path) if cribl_path else False,
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class _ConfAnalysisRequest(BaseModel):
    apps_dir: str = Field(default="", description="Path to Splunk apps directory (legacy param, use splunk_repo).")
    splunk_repo: str = Field(default="", description="Path to Splunk deployment repo (contains apps/ dir).")
    cribl_repo: str = Field(default="", description="Path to Cribl deployment repo (optional, for comparison).")
    btool_csv: str = Field(default="", description="Inline btool-output CSV content (alternative to file scan).")
    app_filter: str = Field(default="", description="Regex filter for app names.")
    category_filter: str = Field(default="", description="Filter by app category: TAs, BAs, IAs, UIs, scripts, legacy.")
    group_filter: str = Field(default="", description="Filter by deployment group: _global, manager-apps, cluster-*, soc-*.")
    output_format: str = Field(default="json", description="Output format: json, csv, yaml")


class _RegexTestRequest(BaseModel):
    pattern: str = Field(..., max_length=500)
    sample: str = Field(..., max_length=50000)
    mode: str = Field(default="line_breaker", description="line_breaker, time_prefix, or extraction")


class _StatusUpdate(BaseModel):
    sourcetype: str = Field(..., min_length=1, max_length=200)
    status: str = Field(..., description="not_started, in_progress, needs_review, done, not_applicable")
    priority: str = Field(default="", description="critical, high, medium, low")
    notes: str = Field(default="", max_length=2000)
    assignee: str = Field(default="", max_length=100)


# ---------------------------------------------------------------------------
# Conf Analysis Endpoints
# ---------------------------------------------------------------------------

@tools_router.post("/tools/analyze-confs", summary="Analyze Splunk confs for Cribl migration")
async def analyze_splunk_confs(body: _ConfAnalysisRequest):
    """Scan Splunk repo for props.conf/transforms.conf, optionally compare with Cribl repo."""
    try:
        from chat_app.conf_index_time_analyzer import run_analysis
        import time as _time
        start = _time.time()

        settings = get_settings()
        org_repo_root = getattr(settings.paths, 'org_repo_root', '') or ''

        splunk_repo = body.splunk_repo or body.apps_dir
        if not splunk_repo and org_repo_root:
            splunk_repo = os.path.join(org_repo_root, "splunk")
        if not splunk_repo:
            splunk_repo = "/opt/splunk/etc/apps"

        cribl_repo = body.cribl_repo
        if not cribl_repo and org_repo_root:
            cribl_path = os.path.join(org_repo_root, "cribl")
            if os.path.isdir(cribl_path):
                cribl_repo = cribl_path

        def _run_analysis():
            return run_analysis(
                apps_dir=splunk_repo,
                output_format=body.output_format,
                splunk_repo=splunk_repo,
                cribl_repo=cribl_repo or "",
                btool_csv=body.btool_csv or "",
                app_filter=body.app_filter or "",
                category_filter=body.category_filter or "",
                group_filter=body.group_filter or "",
            )

        result = await asyncio.to_thread(_run_analysis)
        duration = _time.time() - start

        _append_audit(section="tools", action="analyze-confs",
                      changes={
                          "apps_dir": body.apps_dir,
                          "splunk_repo": body.splunk_repo,
                          "cribl_repo": body.cribl_repo,
                          "btool_csv_len": len(body.btool_csv),
                          "app_filter": body.app_filter,
                          "category_filter": body.category_filter,
                          "group_filter": body.group_filter,
                          "duration": round(duration, 1),
                      })

        if body.output_format == "json":
            try:
                import json as _json
                report = _json.loads(result)
            except (ValueError, TypeError):
                report = result
        else:
            report = result

        scan_id = ""
        try:
            from chat_app.migration_state import get_migration_state, ScanRecord
            scan_id = uuid.uuid4().hex[:12]
            summary = report.get("scan_summary", {}) if isinstance(report, dict) else {}
            src_type = "btool_csv" if body.btool_csv else "repo"
            rec = ScanRecord(
                scan_id=scan_id,
                timestamp=_now_iso(),
                source_type=src_type,
                apps_scanned=summary.get("total_apps", 0),
                sourcetypes_found=summary.get("total_sourcetypes", 0),
                critical_settings=summary.get("critical_settings", 0),
                scan_path=body.splunk_repo or body.apps_dir or "",
                report_summary=summary,
            )
            get_migration_state().add_scan(rec, result if body.output_format == "json" else "")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as hist_exc:
            logger.debug("[TOOLS] Failed to save scan history: %s", hist_exc)

        return {
            "status": "ok",
            "scan_id": scan_id,
            "duration_seconds": round(duration, 1),
            "report": report,
            "timestamp": _now_iso(),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Directory not found: {exc}")
    except ImportError as exc:
        logger.warning("[TOOLS] conf analyzer not available: %s", exc)
        raise HTTPException(status_code=503, detail="Conf analyzer module not installed")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[TOOLS] Conf analysis failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=_safe_error(exc, "conf analysis"))


@tools_router.post("/tools/analyze-confs/upload", summary="Upload btool CSV for Cribl migration analysis")
async def analyze_confs_upload(request: Request):
    """Accept a CSV file upload (btool output) and run the migration analysis."""
    try:
        form = await request.form()
        file_field = form.get("file")
        if not file_field:
            raise HTTPException(status_code=400, detail="No file uploaded. Send a 'file' field with multipart/form-data.")
        csv_content = (await file_field.read()).decode("utf-8", errors="replace")
        if not csv_content.strip():
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        from chat_app.conf_index_time_analyzer import run_analysis
        import time as _time

        start = _time.time()

        def _run():
            return run_analysis(btool_csv=csv_content, output_format="json")

        result = await asyncio.to_thread(_run)
        duration = _time.time() - start

        import json as _json
        try:
            report = _json.loads(result)
        except (ValueError, TypeError):
            report = result

        scan_id = ""
        try:
            from chat_app.migration_state import get_migration_state, ScanRecord
            scan_id = uuid.uuid4().hex[:12]
            summary = report.get("scan_summary", {}) if isinstance(report, dict) else {}
            rec = ScanRecord(
                scan_id=scan_id,
                timestamp=_now_iso(),
                source_type="upload",
                apps_scanned=summary.get("total_apps", 0),
                sourcetypes_found=summary.get("total_sourcetypes", 0),
                critical_settings=summary.get("critical_settings", 0),
                scan_path="upload",
                report_summary=summary,
            )
            get_migration_state().add_scan(rec, result)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as hist_exc:
            logger.debug("[TOOLS] Failed to save upload scan history: %s", hist_exc)

        _append_audit(section="tools", action="analyze-confs-upload",
                      changes={"csv_length": len(csv_content), "scan_id": scan_id, "duration": round(duration, 1)})

        return {
            "status": "ok",
            "scan_id": scan_id,
            "duration_seconds": round(duration, 1),
            "report": report,
            "timestamp": _now_iso(),
        }
    except HTTPException:
        raise
    except ImportError as exc:
        logger.warning("[TOOLS] conf analyzer not available: %s", exc)
        raise HTTPException(status_code=503, detail="Conf analyzer module not installed")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[TOOLS] Upload conf analysis failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=_safe_error(exc, "upload conf analysis"))


@tools_router.post("/tools/analyze-confs/test-regex", summary="Test regex pattern for migration validation")
async def test_migration_regex(body: _RegexTestRequest):
    """Test a regex pattern against sample data."""
    try:
        from chat_app.conf_index_time_analyzer import validate_regex_pattern
        result = validate_regex_pattern(body.pattern, body.sample, body.mode)
        return {"status": "ok" if result.get("ok") else "error", **result}
    except ImportError as exc:
        logger.warning("[TOOLS] conf analyzer not available: %s", exc)
        raise HTTPException(status_code=503, detail="Conf analyzer module not installed")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[TOOLS] regex test failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=_safe_error(exc, "regex test"))


@tools_router.get("/tools/analyze-confs/history", summary="Get migration scan history")
async def get_scan_history(limit: int = Query(20, ge=1, le=100)):
    """Return recent migration scan history (newest first)."""
    from chat_app.migration_state import get_migration_state
    history = get_migration_state().get_history(limit)
    return {"status": "ok", "scans": history, "total": len(history)}


@tools_router.get("/tools/analyze-confs/history/{scan_id}", summary="Get past scan report")
async def get_scan_report(scan_id: str):
    """Return the full report for a previously completed scan."""
    from chat_app.migration_state import get_migration_state
    import json as _json
    report_json = get_migration_state().get_report(scan_id)
    if report_json is None:
        raise HTTPException(status_code=404, detail=f"Scan '{scan_id}' not found or report not stored.")
    try:
        report = _json.loads(report_json)
    except (ValueError, TypeError):
        report = report_json
    return {"status": "ok", "scan_id": scan_id, "report": report}


@tools_router.post("/tools/analyze-confs/status", summary="Update sourcetype migration status")
async def update_migration_status(body: _StatusUpdate):
    """Set the migration status for a sourcetype."""
    from chat_app.migration_state import get_migration_state
    try:
        result = get_migration_state().set_status(
            sourcetype=body.sourcetype,
            status=body.status,
            priority=body.priority,
            notes=body.notes,
            assignee=body.assignee,
        )
        _append_audit(section="tools", action="migration-status-update",
                      changes={"sourcetype": body.sourcetype, "status": body.status})
        return {"status": "ok", "sourcetype_status": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@tools_router.get("/tools/analyze-confs/statuses", summary="Get all sourcetype migration statuses")
async def get_migration_statuses():
    """Return all tracked sourcetype migration statuses."""
    from chat_app.migration_state import get_migration_state
    state = get_migration_state()
    statuses = state.get_all_statuses()
    stats = state.get_stats()
    return {"status": "ok", "statuses": statuses, "stats": stats}


@tools_router.post("/tools/analyze-confs/export/cribl", summary="Export Cribl pipeline configs")
async def export_cribl_pipelines(scan_id: str = Query(..., description="Scan ID to export")):
    """Generate Cribl pipeline configuration snippets from a scan report."""
    from chat_app.migration_state import get_migration_state
    import json as _json

    report_json = get_migration_state().get_report(scan_id)
    if report_json is None:
        raise HTTPException(status_code=404, detail=f"Scan '{scan_id}' not found.")

    try:
        report = _json.loads(report_json)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail="Stored report is not valid JSON.")

    pipelines: List[Dict[str, Any]] = []
    by_sourcetype = report.get("by_sourcetype", {})
    for st_name, st_data in sorted(by_sourcetype.items()):
        functions = []
        for mapping in st_data.get("cribl_pipeline", []):
            functions.append({
                "id": mapping.get("cribl_function", "unknown").lower().replace(" ", "_"),
                "filter": f"sourcetype=='{st_name}'",
                "conf": mapping.get("cribl_config", {}),
                "description": f"{mapping.get('splunk_setting', '')}={mapping.get('splunk_value', '')}",
            })
        if functions:
            pipelines.append({
                "id": f"migrate_{st_name.replace(':', '_').replace('-', '_')}",
                "description": f"Migrated settings for sourcetype {st_name}",
                "functions": functions,
            })

    return {
        "status": "ok",
        "scan_id": scan_id,
        "pipelines": pipelines,
        "total_pipelines": len(pipelines),
    }


@tools_router.post("/tools/analyze-confs/export/checklist", summary="Export migration checklist as markdown")
async def export_migration_checklist(scan_id: str = Query("", description="Optional scan ID for context")):
    """Generate a markdown migration checklist from sourcetype statuses and optional scan data."""
    from chat_app.migration_state import get_migration_state
    import json as _json

    state = get_migration_state()
    statuses = state.get_all_statuses()

    scan_sourcetypes: Dict[str, Any] = {}
    if scan_id:
        report_json = state.get_report(scan_id)
        if report_json:
            try:
                report = _json.loads(report_json)
                scan_sourcetypes = report.get("by_sourcetype", {})
            except (ValueError, TypeError) as _exc:
                logger.debug("Could not parse cached checklist report JSON: %s", _exc)

    lines: List[str] = [
        "# Cribl Migration Checklist",
        "",
        f"Generated: {_now_iso()}",
        "",
    ]

    if scan_id:
        lines.append(f"Based on scan: `{scan_id}`")
        lines.append("")

    groups: Dict[str, List[str]] = {
        "not_started": [], "in_progress": [], "needs_review": [],
        "done": [], "not_applicable": [],
    }

    all_sts = set(statuses.keys())
    all_sts.update(scan_sourcetypes.keys())

    for st_name in sorted(all_sts):
        st_status = statuses.get(st_name, {})
        status_val = st_status.get("status", "not_started")
        groups.setdefault(status_val, []).append(st_name)

    status_emoji = {
        "not_started": "[ ]", "in_progress": "[-]", "needs_review": "[?]",
        "done": "[x]", "not_applicable": "[~]",
    }

    for status_key, label in [
        ("not_started", "Not Started"), ("in_progress", "In Progress"),
        ("needs_review", "Needs Review"), ("done", "Done"),
        ("not_applicable", "Not Applicable"),
    ]:
        items = groups.get(status_key, [])
        if items:
            lines.append(f"## {label} ({len(items)})")
            lines.append("")
            for st_name in items:
                marker = status_emoji.get(status_key, "[ ]")
                st_info = statuses.get(st_name, {})
                priority = st_info.get("priority", "medium")
                assignee = st_info.get("assignee", "")
                notes = st_info.get("notes", "")
                detail = f" | priority: {priority}" if priority else ""
                if assignee:
                    detail += f" | assignee: {assignee}"
                if notes:
                    detail += f" | {notes}"
                scan_data = scan_sourcetypes.get(st_name, {})
                setting_count = len(scan_data.get("all_settings", []))
                if setting_count:
                    detail += f" | {setting_count} settings"
                lines.append(f"- {marker} **{st_name}**{detail}")
            lines.append("")

    if not any(groups.values()):
        lines.append("_No sourcetypes tracked yet. Run a scan first._")
        lines.append("")

    stats = state.get_stats()
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total scans: {stats.get('total_scans', 0)}")
    lines.append(f"- Sourcetypes tracked: {stats.get('total_sourcetypes_tracked', 0)}")
    for s, count in stats.get("by_status", {}).items():
        lines.append(f"- {s}: {count}")

    checklist = "\n".join(lines)

    return {
        "status": "ok",
        "checklist": checklist,
        "content_type": "text/markdown",
    }



# ---------------------------------------------------------------------------
# Re-export extended tools routers for backward compatibility
# ---------------------------------------------------------------------------
from chat_app.admin_tools_routes_ext import tools_ext_router  # noqa: E402,F401
from chat_app.admin_tools_routes_ext2 import tools_ext2_router  # noqa: E402,F401
