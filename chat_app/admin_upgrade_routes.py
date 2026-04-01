"""
Admin API routes for the Splunk Upgrade Readiness Testing System.

Provides all upgrade-related endpoints under /api/admin/upgrade/* and
/api/admin/upgrade/test/*.

Mount with:
    from chat_app.admin_upgrade_routes import upgrade_router
    app.include_router(upgrade_router)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from chat_app.admin_shared import (
    _csrf_check,
    _rate_limit,
    _safe_error,
    _track_audit_user,
)
from chat_app.auth_dependencies import require_admin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

upgrade_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-upgrade"],
    dependencies=[
        Depends(_rate_limit),
        Depends(require_admin),
        Depends(_track_audit_user),
        Depends(_csrf_check),
    ],
)

# ---------------------------------------------------------------------------
# In-memory state with disk persistence
# ---------------------------------------------------------------------------

# Cached org inventory: {cluster_name: ClusterInventory}
_inventory_cache: Dict[str, Any] = {}

# Completed test suites: {suite_id: ContainerTestSuite}
_test_suites: Dict[str, Any] = {}

# Completed reports: loaded on demand from disk, listed from report_builder
_report_cache: Dict[str, Any] = {}

# Scan event log — stores last N scan events for UI display
_scan_log: List[Dict[str, str]] = []
_SCAN_LOG_MAX = 50

# Track when scans happened
_last_scanned_at: Dict[str, str] = {}  # {"deep_scan": "2025-01-01T00:00:00Z", ...}

_SCAN_CACHE_PATH = "/app/data/scan_cache.json"


def _log_scan_event(level: str, message: str) -> None:
    """Append an event to the scan log (visible in UI)."""
    from datetime import datetime, timezone
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }
    _scan_log.append(entry)
    if len(_scan_log) > _SCAN_LOG_MAX:
        _scan_log[:] = _scan_log[-_SCAN_LOG_MAX:]


def _persist_scan_metadata() -> None:
    """Save scan timestamps and summary to disk for container restart recovery."""
    import json
    try:
        data = {
            "last_scanned_at": _last_scanned_at,
            "scan_log": _scan_log[-20:],
        }
        os.makedirs(os.path.dirname(_SCAN_CACHE_PATH), exist_ok=True)
        with open(_SCAN_CACHE_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        logger.warning("[UPGRADE] Failed to persist scan metadata: %s", exc)


def _load_scan_metadata() -> None:
    """Load scan metadata from disk on startup."""
    import json
    global _last_scanned_at, _scan_log
    try:
        if os.path.isfile(_SCAN_CACHE_PATH):
            with open(_SCAN_CACHE_PATH) as f:
                data = json.load(f)
            _last_scanned_at.update(data.get("last_scanned_at", {}))
            _scan_log.extend(data.get("scan_log", []))
    except Exception as exc:
        logger.warning("[UPGRADE] Failed to load scan metadata: %s", exc)


# Load on module import
_load_scan_metadata()

# ---------------------------------------------------------------------------
# Inventory response persistence (survives container restarts)
# ---------------------------------------------------------------------------

_INVENTORY_RESPONSE_PATH = "/app/data/inventory_response.json"

# Pre-built response dict cached in memory (avoids re-serializing on every GET)
_serialized_response_cache: Dict[str, Any] = {}


def _persist_inventory_response(response_data: Dict[str, Any]) -> None:
    """Write the inventory response to disk atomically (write .tmp then rename)."""
    global _serialized_response_cache
    try:
        _serialized_response_cache = response_data
        os.makedirs(os.path.dirname(_INVENTORY_RESPONSE_PATH), exist_ok=True)
        tmp_path = _INVENTORY_RESPONSE_PATH + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(response_data, f, indent=2)
        os.replace(tmp_path, _INVENTORY_RESPONSE_PATH)
        logger.info("[UPGRADE] Persisted inventory response (%d apps) to %s",
                     response_data.get("total_apps", 0), _INVENTORY_RESPONSE_PATH)
    except Exception as exc:
        logger.warning("[UPGRADE] Failed to persist inventory response: %s", exc)


def _load_inventory_response() -> None:
    """Load inventory response from disk on startup, populating the in-memory cache."""
    global _serialized_response_cache
    try:
        if os.path.isfile(_INVENTORY_RESPONSE_PATH):
            with open(_INVENTORY_RESPONSE_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("status") == "ok":
                _serialized_response_cache = data
                logger.info("[UPGRADE] Loaded cached inventory response (%d apps) from disk",
                             data.get("total_apps", 0))
    except Exception as exc:
        logger.warning("[UPGRADE] Failed to load inventory response from disk: %s", exc)


# Load on module import (after scan metadata)
_load_inventory_response()


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    """Request body for POST /upgrade/inventory/scan."""

    cluster: Optional[str] = Field(
        None,
        description="Cluster name to scan; scans all configured clusters if omitted",
    )
    repo_path: Optional[str] = Field(
        None,
        description="Override path to the git repo root; defaults to configured path",
    )


class AnalyzeRequest(BaseModel):
    """Request body for POST /upgrade/analyze."""

    app_id: str = Field(..., description="App folder name, e.g. Splunk_TA_windows")
    cluster: str = Field(..., description="Cluster name, e.g. cluster-es")
    target_version: Optional[str] = Field(
        None, description="Target version string; defaults to latest available"
    )
    include_container_test: bool = Field(
        False, description="Run live container-based tests after static analysis"
    )
    check_cim: bool = Field(True, description="Run CIM compliance checks")
    validate_specs: bool = Field(True, description="Validate against spec files")


class ContainerTestRequest(BaseModel):
    """Request body for POST /upgrade/test."""

    app_id: str = Field(..., description="App folder name")
    cluster: str = Field(..., description="Cluster name")
    from_version: str = Field(..., description="Currently installed version")
    to_version: str = Field(..., description="Target version to test")
    splunk_version: str = Field("9.3.2", description="Splunk container image tag")


class RunbookRequest(BaseModel):
    """Request body for POST /upgrade/runbook."""

    from_version: str = Field(..., description="Currently installed Splunk version, e.g. 9.3.2")
    to_version: str = Field(..., description="Target Splunk version, e.g. 10.2.1")
    upgrade_type: str = Field(
        "splunk_core",
        description="Type of upgrade: splunk_core, es, itsi, uf, app, ta",
    )
    app_id: str = Field("", description="App directory name (for app/TA upgrades)")
    cluster: str = Field("", description="Target cluster name")
    # Optional: pre-computed analysis results to embed in the runbook
    include_config_audit: bool = Field(
        True, description="Run config audit and embed findings in runbook"
    )
    conf_files: Optional[Dict[str, Any]] = Field(
        None, description="Parsed conf files for config audit: {conf_name: {stanza: {key: value}}}"
    )


# ---------------------------------------------------------------------------
# Helper: lazy-load service objects
# ---------------------------------------------------------------------------


def _get_report_builder():
    """Return a ReportBuilder singleton (lazy import)."""
    from chat_app.upgrade_readiness.report_builder import ReportBuilder
    return ReportBuilder()


def _get_fetcher():
    """Return a SplunkbaseFetcher singleton (lazy import)."""
    from chat_app.upgrade_readiness.splunkbase_fetcher import SplunkbaseFetcher
    return SplunkbaseFetcher()


def _get_settings():
    """Return application settings (lazy import)."""
    from chat_app.settings import get_settings
    return get_settings()


def _resolve_repo_path(override: Optional[str] = None) -> str:
    """Resolve the Splunk repo path, auto-detecting from known locations.

    Priority:
    1. Explicit override parameter
    2. Settings: upgrade_readiness.repo_path or paths.org_repo_root + /splunk
    3. ORG_REPO_ROOT env var + /splunk
    4. Auto-detect from common container mount points
    """
    if override and Path(override).is_dir():
        return override

    candidates: list = []

    # From settings
    try:
        settings = _get_settings()
        # upgrade_readiness.repo_path
        ur = getattr(settings, "upgrade_readiness", None)
        if ur:
            rp = getattr(ur, "repo_path", "")
            if rp:
                candidates.append(rp)
        # paths.org_repo_root + /splunk
        org_root = getattr(settings.paths, "org_repo_root", "") or ""
        if org_root:
            candidates.append(os.path.join(org_root, "splunk"))
            candidates.append(org_root)
    except Exception:
        pass

    # From environment
    env_repo = os.environ.get("ORG_REPO_ROOT", "")
    if env_repo:
        candidates.append(os.path.join(env_repo, "splunk"))
        candidates.append(env_repo)

    # Common container mount points
    candidates.extend([
        "/app/shared/public/documents/repo/splunk",
        "/app/shared/public/documents/repo",
        "/app/public/documents/repo/splunk",
        "/app/public/documents/repo",
        "/app/documents/repo/splunk",
        "/app/project/documents/repo/splunk",
    ])

    for path in candidates:
        if not path:
            continue
        p = Path(path)
        if not p.is_dir():
            continue
        # Check if it has Splunk-like content
        try:
            has_splunk_dirs = any(
                (p / d).is_dir() for d in ["deployment-apps", "shcluster", "master-apps", "etc"]
            )
            has_conf = any(p.rglob("*.conf"))
            if has_splunk_dirs or has_conf:
                logger.info("[UPGRADE] Resolved repo path: %s", path)
                return str(p)
        except (PermissionError, OSError):
            continue

    # Last resort: return first existing directory from candidates
    for path in candidates:
        if path and Path(path).is_dir():
            return str(path)

    return override or "/app/shared/public/documents/repo/splunk"


def _get_available_repos() -> List[Dict[str, Any]]:
    """List all available repo directories for the UI dropdown."""
    repos = []
    search_dirs: list = []

    # From settings / env
    try:
        settings = _get_settings()
        org_root = getattr(settings.paths, "org_repo_root", "") or ""
        if org_root:
            search_dirs.append(org_root)
    except Exception:
        pass
    env_repo = os.environ.get("ORG_REPO_ROOT", "")
    if env_repo and env_repo not in search_dirs:
        search_dirs.append(env_repo)

    # Common container mount points
    search_dirs.extend([
        "/app/shared/public/documents/repo",
        "/app/public/documents/repo",
        "/app/documents/repo",
        "/app/project/documents/repo",
        "documents/repo",
    ])
    for base in search_dirs:
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        for child in sorted(base_path.iterdir()):
            if child.is_dir() and not child.name.startswith('.'):
                conf_count = sum(1 for _ in child.rglob("*.conf"))
                app_count = sum(1 for _ in child.rglob("app.conf"))
                if conf_count > 0:
                    repos.append({
                        "name": child.name,
                        "path": str(child),
                        "type": "splunk" if any((child / d).is_dir() for d in ["deployment-apps", "shcluster"]) else "other",
                        "conf_files": conf_count,
                        "apps": app_count,
                    })
    return repos


# ---------------------------------------------------------------------------
# Scan log endpoint
# ---------------------------------------------------------------------------


@upgrade_router.get("/upgrade/scan-log", summary="Recent scan events")
async def get_scan_log() -> Dict[str, Any]:
    """Return the recent scan event log and last-scanned timestamps."""
    return {
        "events": _scan_log[-20:],
        "last_scanned": _last_scanned_at,
        "total_events": len(_scan_log),
    }


# ---------------------------------------------------------------------------
# Inventory endpoints
# ---------------------------------------------------------------------------


@upgrade_router.get("/upgrade/inventory", summary="Full baseline inventory")
async def get_inventory() -> Dict[str, Any]:
    """
    Return the full cached org inventory.

    Returns the most-recently scanned ClusterInventory objects (serialised).
    Trigger a fresh scan via POST /upgrade/inventory/scan.
    """
    if not _inventory_cache:
        return {
            "status": "empty",
            "message": "No inventory available. Run POST /upgrade/inventory/scan first.",
            "clusters": {},
        }

    clusters_summary: Dict[str, Any] = {}
    for cluster_name, inventory in _inventory_cache.items():
        app_names = list(getattr(inventory, "apps", {}).keys())
        clusters_summary[cluster_name] = {
            "app_count": len(app_names),
            "apps": app_names,
            "scanned_at": getattr(inventory, "scanned_at", datetime.now(timezone.utc)).isoformat(),
            "errors": getattr(inventory, "errors", []),
        }

    return {
        "status": "ok",
        "cluster_count": len(clusters_summary),
        "clusters": clusters_summary,
    }


@upgrade_router.get("/upgrade/repos", summary="List available Splunk repos")
async def list_repos() -> Dict[str, Any]:
    """List available Splunk repository directories that can be scanned."""
    repos = _get_available_repos()
    default_path = _resolve_repo_path()
    return {
        "repos": repos,
        "default_path": default_path,
        "total": len(repos),
    }


@upgrade_router.post("/upgrade/inventory/deep-scan", summary="Deep recursive repo scan")
async def deep_scan_inventory(body: ScanRequest) -> Dict[str, Any]:
    """
    Recursively scan the Splunk repo to find ALL apps across all tiers.

    Understands deployment-apps, master-apps, shcluster, etc/apps structures.
    Finds apps by looking for default/ + .conf files, not just app.conf.
    """
    try:
        from datetime import datetime, timezone
        from chat_app.upgrade_readiness.baseline_builder import scan_splunk_repo, match_splunkbase_versions
        import time as _time

        repo_path = _resolve_repo_path(body.repo_path)
        scan_start = _time.time()
        logger.info("[UPGRADE] Deep scanning repo: %s", repo_path)
        _log_scan_event("info", f"Starting deep scan of {repo_path}")

        inventory = await asyncio.to_thread(scan_splunk_repo, repo_path)
        app_count_found = len(inventory.apps)
        _log_scan_event("info", f"Found {app_count_found} apps in {repo_path}")

        if inventory.errors:
            for err in inventory.errors[:5]:
                _log_scan_event("warning", err)

        # Ensure Splunkbase catalog is loaded before enrichment
        catalog_status = "skipped"
        try:
            from chat_app.splunkbase_catalog import get_splunkbase_catalog
            catalog = get_splunkbase_catalog()
            cat_data = catalog.catalog
            catalog_app_count = len(cat_data.get("apps", {}))
            if catalog_app_count < 10:
                _log_scan_event("info", f"Splunkbase catalog has only {catalog_app_count} apps, attempting full rebuild...")
                try:
                    # Full rebuild with force to bypass 12h staleness check
                    result = await catalog.update_catalog(incremental=False, force=True)
                    new_count = len(catalog.catalog.get("apps", {}))
                    if result.get("skipped"):
                        catalog_status = f"skipped: {result.get('reason', 'unknown')}"
                        _log_scan_event("warning", f"Catalog refresh skipped: {result.get('reason')}")
                    elif new_count > catalog_app_count:
                        catalog_status = f"refreshed ({new_count} apps)"
                        _log_scan_event("info", f"Splunkbase catalog rebuilt: {new_count} apps")
                    else:
                        catalog_status = f"refresh attempted but still {new_count} apps (API may be unreachable)"
                        _log_scan_event("warning", f"Catalog refresh got {new_count} apps — Splunkbase API may be unreachable from container")
                except Exception as refresh_exc:
                    catalog_status = f"refresh failed: {refresh_exc}"
                    _log_scan_event("warning", f"Catalog refresh failed: {refresh_exc} — version comparison unavailable")
            else:
                catalog_status = f"loaded ({catalog_app_count} apps)"
                _log_scan_event("info", f"Splunkbase catalog: {catalog_app_count} apps loaded")
        except Exception as exc:
            logger.warning("[UPGRADE] Splunkbase catalog load/refresh failed: %s", exc)
            catalog_status = f"failed: {exc}"
            _log_scan_event("warning", f"Splunkbase catalog unavailable: {exc} — showing apps without version comparison")

        # Enrich with Splunkbase version data
        enrichment_warnings: list = []
        try:
            match_splunkbase_versions(inventory)
            _log_scan_event("info", "Splunkbase version enrichment complete")
        except Exception as exc:
            logger.warning("[UPGRADE] Splunkbase enrichment failed: %s", exc)
            enrichment_warnings.append(f"Splunkbase version data unavailable: {exc}")
            _log_scan_event("error", f"Splunkbase enrichment failed: {exc}")

        _inventory_cache["deep_scan"] = inventory

        # Record scan timestamp
        scanned_at = datetime.now(timezone.utc).isoformat()
        _last_scanned_at["deep_scan"] = scanned_at
        scan_duration = round(_time.time() - scan_start, 1)
        _log_scan_event("info", f"Deep scan complete: {app_count_found} apps in {scan_duration}s")
        _persist_scan_metadata()

        # Build detailed response with Splunkbase classification
        apps_list = []
        splunkbase_count = 0
        upgradeable_count = 0

        # Try to use Splunkbase fetcher for version classification
        fetcher = None
        try:
            from chat_app.upgrade_readiness.splunkbase_fetcher import SplunkbaseFetcher, _parse_version_tuple
            fetcher = SplunkbaseFetcher()
        except Exception:
            pass

        for app_key, baseline in inventory.apps.items():
            version = getattr(baseline, "version", None)
            installed_version = getattr(version, "version", "0.0.0") if version else "0.0.0"

            # Splunkbase classification
            is_splunkbase = False
            latest_version = ""
            versions_behind = 0
            upgrade_available = False
            splunkbase_url = ""

            if fetcher:
                try:
                    catalog_entry = fetcher.find_app(app_key)
                    if catalog_entry:
                        is_splunkbase = True
                        splunkbase_count += 1
                        latest_version = catalog_entry.get("latest_version", "")
                        splunkbase_uid = catalog_entry.get("uid", "")
                        if splunkbase_uid:
                            splunkbase_url = f"https://splunkbase.splunk.com/app/{splunkbase_uid}"
                        if latest_version and installed_version != "0.0.0":
                            installed_tuple = _parse_version_tuple(installed_version)
                            latest_tuple = _parse_version_tuple(latest_version)
                            if installed_tuple < latest_tuple:
                                upgrade_available = True
                                upgradeable_count += 1
                                releases = catalog_entry.get("releases", [])
                                versions_behind = len([
                                    r for r in releases
                                    if _parse_version_tuple(r.get("version", "0")) > installed_tuple
                                ])
                except Exception:
                    pass

            # Conf detail: stanza counts per conf type, local override analysis
            default_confs = getattr(baseline, "default_confs", {})
            local_confs_data = getattr(baseline, "local_confs", {})

            conf_detail = {}
            for conf_name, stanzas in default_confs.items():
                local_stanzas = local_confs_data.get(conf_name, {})
                overridden = len(set(stanzas.keys()) & set(local_stanzas.keys()))
                conf_detail[conf_name] = {
                    "stanzas": len(stanzas),
                    "local_stanzas": len(local_stanzas),
                    "overridden": overridden,
                }

            # Derive a status string for filtering
            if is_splunkbase and upgrade_available:
                status = "outdated"
            elif is_splunkbase and not upgrade_available and latest_version:
                status = "up_to_date"
            elif is_splunkbase and not latest_version:
                status = "unknown"
            else:
                status = "custom"

            # Relative path from repo root
            app_path = getattr(baseline, "app_dir", "")
            rel_path = app_path
            if app_path and repo_path and app_path.startswith(repo_path):
                rel_path = app_path[len(repo_path):].lstrip("/")

            apps_list.append({
                "app_id": app_key,
                "label": getattr(version, "label", app_key) if version else app_key,
                "installed_version": installed_version,
                "build": getattr(version, "build", "") if version else "",
                "author": getattr(version, "author", "") if version else "",
                "description": getattr(version, "description", "") if version else "",
                "path": app_path,
                "rel_path": rel_path,
                "conf_files": list(default_confs.keys()),
                "local_confs": list(local_confs_data.keys()),
                "has_local_changes": len(local_confs_data) > 0,
                "conf_count": len(default_confs),
                "conf_detail": conf_detail,
                "splunkbase_managed": is_splunkbase,
                "latest_version": latest_version,
                "versions_behind": versions_behind,
                "upgrade_available": upgrade_available,
                "splunkbase_url": splunkbase_url,
                "status": status,
            })

        all_errors = inventory.errors + enrichment_warnings
        custom_count = len(apps_list) - splunkbase_count

        response = {
            "status": "ok",
            "total_apps": len(apps_list),
            "splunkbase_managed": splunkbase_count,
            "custom_apps": custom_count,
            "upgrades_available": upgradeable_count,
            "apps": sorted(apps_list, key=lambda a: (not a["upgrade_available"], a["app_id"])),
            "errors": all_errors,
            "repo_path": repo_path,
            "catalog_status": catalog_status,
            "scanned_at": scanned_at,
            "scan_duration_seconds": scan_duration,
        }

        # Persist to disk so the response survives container restarts
        _persist_inventory_response(response)

        return response
    except Exception as exc:
        _log_scan_event("error", f"Deep scan failed: {exc}")
        raise HTTPException(status_code=500, detail=_safe_error(exc, "deep scan"))


@upgrade_router.get("/upgrade/repository/app/{app_id}/confs", summary="Stanza-level conf detail for an app")
async def get_app_conf_detail(app_id: str) -> Dict[str, Any]:
    """Return all parsed stanzas for a specific app from the cached deep-scan inventory."""
    inventory = _inventory_cache.get("deep_scan")
    if not inventory:
        raise HTTPException(status_code=404, detail="No scan data. Run deep-scan first.")

    baseline = getattr(inventory, "apps", {}).get(app_id)
    if not baseline:
        raise HTTPException(status_code=404, detail=f"App '{app_id}' not found in scan cache.")

    default_confs = getattr(baseline, "default_confs", {})
    local_confs = getattr(baseline, "local_confs", {})

    confs = {}
    for conf_name, stanzas in default_confs.items():
        local_stanzas = local_confs.get(conf_name, {})
        conf_entry = {"stanzas": {}}
        for stanza_name, keys in stanzas.items():
            if stanza_name == "__lines__":
                continue
            # Clean keys: remove internal parser metadata
            clean_keys = {k: v for k, v in keys.items() if not k.startswith("__")}
            local_keys = {}
            if stanza_name in local_stanzas:
                local_keys = {k: v for k, v in local_stanzas[stanza_name].items() if not k.startswith("__")}
            # Merge: show default values + local overrides
            merged = {**clean_keys, **local_keys}
            conf_entry["stanzas"][stanza_name] = {
                "default": clean_keys,
                "local": local_keys,
                "merged": merged,
                "has_override": len(local_keys) > 0,
            }
        confs[conf_name] = conf_entry

    # Also include local-only conf files (not in default/)
    for conf_name, stanzas in local_confs.items():
        if conf_name in confs:
            continue
        conf_entry = {"stanzas": {}}
        for stanza_name, keys in stanzas.items():
            if stanza_name == "__lines__":
                continue
            clean_keys = {k: v for k, v in keys.items() if not k.startswith("__")}
            conf_entry["stanzas"][stanza_name] = {
                "default": {},
                "local": clean_keys,
                "merged": clean_keys,
                "has_override": True,
            }
        confs[conf_name] = conf_entry

    return {
        "app_id": app_id,
        "confs": confs,
        "total_conf_files": len(confs),
        "total_stanzas": sum(len(c["stanzas"]) for c in confs.values()),
    }


@upgrade_router.get("/upgrade/repository/export", summary="Export repository apps as CSV/JSON")
async def export_repository_apps(
    format: str = Query(default="csv", description="Export format: csv or json"),
    status_filter: Optional[str] = Query(default=None, description="Filter by status: up_to_date, outdated, unknown, custom"),
) -> Any:
    """Export all scanned apps with full metadata."""
    from fastapi.responses import Response
    import csv
    import io

    # Get apps from the repository-apps endpoint logic
    repo_response = await get_repository_apps()
    apps_list = repo_response.get("apps", [])

    if status_filter:
        apps_list = [a for a in apps_list if a.get("status") == status_filter]

    if format == "json":
        return {"apps": apps_list, "total": len(apps_list)}

    # CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "app_id", "label", "installed_version", "latest_version", "versions_behind",
        "status", "splunkbase_managed", "upgrade_available", "has_local_changes",
        "conf_count", "conf_files", "local_confs", "author", "path", "splunkbase_url",
    ])
    for app in apps_list:
        writer.writerow([
            app.get("app_id", ""),
            app.get("label", ""),
            app.get("installed_version", ""),
            app.get("latest_version", ""),
            app.get("versions_behind", 0),
            app.get("status", ""),
            app.get("splunkbase_managed", False),
            app.get("upgrade_available", False),
            app.get("has_local_changes", False),
            app.get("conf_count", 0),
            "; ".join(app.get("conf_files", [])),
            "; ".join(app.get("local_confs", [])),
            app.get("author", ""),
            app.get("path", ""),
            app.get("splunkbase_url", ""),
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=splunk_apps_report.csv"},
    )


@upgrade_router.post("/upgrade/catalog/upload", summary="Upload a Splunkbase catalog JSON file")
async def upload_splunkbase_catalog(request: Request) -> Dict[str, Any]:
    """
    Upload a pre-built Splunkbase catalog JSON file.

    Use this when the container has no internet access to splunkbase.splunk.com.
    Generate the catalog on a machine with internet:
        python3 scripts/fetch_splunkbase_catalog.py

    Then upload the resulting JSON file here.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body. POST the catalog JSON.")

    try:
        catalog_data = json.loads(body.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    if not isinstance(catalog_data, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object with 'apps' key")

    apps = catalog_data.get("apps", {})
    if not apps:
        raise HTTPException(status_code=400, detail="No 'apps' key found in the catalog JSON")

    # Load into the catalog singleton
    try:
        from chat_app.splunkbase_catalog import get_splunkbase_catalog
        catalog = get_splunkbase_catalog()
        catalog._catalog = catalog_data
        catalog._loaded = True
        catalog.save_catalog()

        app_count = len(apps)
        _log_scan_event("info", f"Splunkbase catalog uploaded: {app_count} apps")

        return {
            "status": "ok",
            "total_apps": app_count,
            "message": f"Catalog uploaded with {app_count} apps. Run 'Scan Repository' to classify apps.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "catalog upload"))


@upgrade_router.get("/upgrade/catalog/status", summary="Check Splunkbase catalog status")
async def get_catalog_status() -> Dict[str, Any]:
    """Return the current state of the Splunkbase catalog — loaded, count, source, age."""
    try:
        from chat_app.splunkbase_catalog import get_splunkbase_catalog
        catalog = get_splunkbase_catalog()
        cat_data = catalog.catalog
        apps = cat_data.get("apps", {})
        meta = cat_data.get("metadata", {})

        # Check if catalog file exists on disk
        from pathlib import Path as _Path
        catalog_on_disk = _Path(catalog._catalog_path).is_file()

        # Check alternate locations
        alt_locations = [
            "/app/shared/public/documents/splunkbase_catalog.json",
            "/app/public/documents/splunkbase_catalog.json",
        ]
        alt_found = None
        for alt in alt_locations:
            if _Path(alt).is_file():
                alt_found = alt
                break

        return {
            "loaded": len(apps) > 0,
            "total_apps": len(apps),
            "last_updated": meta.get("last_updated", ""),
            "source": meta.get("source", "unknown"),
            "catalog_path": str(catalog._catalog_path),
            "catalog_on_disk": catalog_on_disk,
            "alt_catalog_found": alt_found,
            "message": (
                f"{len(apps)} apps loaded" if apps
                else "Catalog is empty. Upload a catalog file or ensure internet access for API refresh."
            ),
        }
    except Exception as exc:
        return {"loaded": False, "total_apps": 0, "error": str(exc)}


async def _analyze_single_app(
    app_id: str,
    baseline: Any,
    analysis_types: List[str],
) -> Dict[str, Any]:
    """Run all requested analysis types for a single app, using threads for CPU-bound work."""
    app_result: Dict[str, Any] = {"app_id": app_id}

    # Impact analysis — conf diff findings
    if "impact" in analysis_types:
        try:
            from chat_app.upgrade_readiness.impact_scorer import build_impact_report
            from chat_app.upgrade_readiness.conf_differ import three_way_diff

            default_confs = getattr(baseline, "default_confs", {})
            local_confs = getattr(baseline, "local_confs", {})

            def _run_impact() -> Dict[str, Any]:
                all_findings = []
                for conf_name in default_confs:
                    local = local_confs.get(conf_name, {})
                    if local:
                        findings = three_way_diff(
                            old_default=default_confs[conf_name],
                            new_default=default_confs[conf_name],
                            local=local,
                            conf_type=conf_name,
                        )
                        all_findings.extend(findings)

                if all_findings:
                    report = build_impact_report(
                        app_id=app_id,
                        from_version=getattr(baseline.version, "version", "0.0.0"),
                        to_version="latest",
                        findings=all_findings,
                    )
                    return {
                        "overall_risk": report.overall_risk.name if hasattr(report.overall_risk, 'name') else str(report.overall_risk),
                        "recommendation": report.recommendation,
                        "finding_count": len(report.findings),
                        "critical": report.critical_count,
                        "high": report.high_count,
                        "medium": report.medium_count,
                        "findings": [
                            {
                                "risk": f.risk.name if hasattr(f.risk, 'name') else str(f.risk),
                                "category": f.category.name if hasattr(f.category, 'name') else str(f.category),
                                "conf_type": str(f.conf_type) if f.conf_type else "",
                                "stanza": f.stanza or "",
                                "key": f.key or "",
                                "description": f.description or "",
                                "recommendation": f.recommendation or "",
                            }
                            for f in report.findings[:50]
                        ],
                    }
                return {"overall_risk": "LOW", "finding_count": 0, "critical": 0, "high": 0, "medium": 0, "recommendation": "No local overrides — clean upgrade expected", "findings": []}

            app_result["impact"] = await asyncio.to_thread(_run_impact)
        except Exception as exc:
            app_result["impact"] = {"error": str(exc)}

    # CIM compliance check
    if "cim" in analysis_types:
        try:
            from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

            def _run_cim() -> Dict[str, Any]:
                cim_result = check_cim_compliance(baseline)
                return {
                    "compliant_models": [m for m, v in cim_result.items() if v.get("compliant")],
                    "non_compliant_models": [m for m, v in cim_result.items() if not v.get("compliant")],
                    "total_models_checked": len(cim_result),
                }

            app_result["cim"] = await asyncio.to_thread(_run_cim)
        except Exception as exc:
            app_result["cim"] = {"error": str(exc)}

    # Dependency analysis
    if "dependencies" in analysis_types:
        try:
            from chat_app.upgrade_readiness.dependency_tracer import build_dependency_graph

            def _run_dependencies() -> Dict[str, Any]:
                graph = build_dependency_graph(baseline)
                dep_result: Dict[str, Any] = {
                    "total_entities": len(getattr(graph, "nodes", [])),
                    "total_edges": len(getattr(graph, "edges", [])),
                    "entity_types": {},
                }
                for node in getattr(graph, "nodes", []):
                    ntype = getattr(node, "entity_type", "unknown")
                    dep_result["entity_types"][ntype] = dep_result["entity_types"].get(ntype, 0) + 1
                return dep_result

            app_result["dependencies"] = await asyncio.to_thread(_run_dependencies)
        except Exception as exc:
            app_result["dependencies"] = {"error": str(exc)}

    # CVE/Security advisory check (async-native — no to_thread needed)
    if "cve" in analysis_types:
        try:
            from chat_app.upgrade_readiness.advisory_scraper import get_advisory_scraper
            scraper = get_advisory_scraper()
            version = getattr(baseline.version, "version", "0.0.0")
            advisories = await scraper.get_advisories_for_version(version)
            app_result["cve"] = {
                "total_advisories": len(advisories),
                "critical": len([a for a in advisories if getattr(a, "severity", "") == "critical"]),
                "high": len([a for a in advisories if getattr(a, "severity", "") == "high"]),
                "advisories": [
                    {
                        "id": getattr(a, "svd_id", ""),
                        "severity": getattr(a, "severity", ""),
                        "title": getattr(a, "title", ""),
                        "cves": getattr(a, "cve_ids", []),
                    }
                    for a in advisories[:20]
                ],
            }
        except Exception as exc:
            app_result["cve"] = {"error": str(exc)}

    # Readiness score
    if "readiness" in analysis_types:
        try:
            from chat_app.upgrade_readiness.readiness_scorer import compute_readiness_score

            def _run_readiness() -> Dict[str, Any]:
                score_result = compute_readiness_score(baseline)
                return {
                    "overall_score": getattr(score_result, "overall_score", 0),
                    "grade": getattr(score_result, "readiness_grade", "UNKNOWN"),
                    "categories": {
                        "config": getattr(score_result, "config_score", 0),
                        "app_compat": getattr(score_result, "app_compat_score", 0),
                        "security": getattr(score_result, "security_score", 0),
                        "infra": getattr(score_result, "infra_score", 0),
                    },
                }

            app_result["readiness"] = await asyncio.to_thread(_run_readiness)
        except Exception as exc:
            app_result["readiness"] = {"error": str(exc)}

    return app_result


@upgrade_router.post("/upgrade/ai-analyze", summary="AI-powered upgrade analysis")
async def ai_analyze_upgrade(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run AI-powered analysis on selected apps using all available engines.

    Combines: conf differ, impact scorer, CIM check, dependency trace, CVE scan,
    readiness score, and generates natural-language recommendations.

    All apps are analyzed in parallel via asyncio.gather for faster throughput.

    Body: {"app_ids": ["app1", "app2"], "analysis_types": ["impact", "cim", "dependencies", "cve", "readiness"]}
    """
    inventory = _inventory_cache.get("deep_scan")
    if not inventory:
        raise HTTPException(status_code=404, detail="No scan data. Run deep-scan first.")

    app_ids = body.get("app_ids", [])
    analysis_types = body.get("analysis_types", ["impact", "cim", "dependencies", "cve", "readiness"])
    if not app_ids:
        app_ids = list(getattr(inventory, "apps", {}).keys())

    # Build tasks for parallel execution — one per app
    tasks: List[asyncio.Task] = []
    valid_app_ids: List[str] = []
    for app_id in app_ids:
        baseline = getattr(inventory, "apps", {}).get(app_id)
        if not baseline:
            continue
        valid_app_ids.append(app_id)
        tasks.append(_analyze_single_app(app_id, baseline, analysis_types))

    # Run all app analyses in parallel
    app_results_list = await asyncio.gather(*tasks, return_exceptions=True)

    results: Dict[str, Any] = {"apps": {}, "summary": {}}
    for app_id, app_result in zip(valid_app_ids, app_results_list):
        if isinstance(app_result, Exception):
            logger.warning("[UPGRADE] Analysis failed for %s: %s", app_id, app_result)
            results["apps"][app_id] = {"app_id": app_id, "error": str(app_result)}
        else:
            results["apps"][app_id] = app_result

    # Generate summary
    all_app_results = list(results["apps"].values())
    total_critical = sum(r.get("impact", {}).get("critical", 0) for r in all_app_results)
    total_high = sum(r.get("impact", {}).get("high", 0) for r in all_app_results)
    avg_readiness = 0
    readiness_values = [r.get("readiness", {}).get("overall_score", 0) for r in all_app_results if "readiness" in r and "error" not in r.get("readiness", {})]
    if readiness_values:
        avg_readiness = round(sum(readiness_values) / len(readiness_values))

    results["summary"] = {
        "apps_analyzed": len(all_app_results),
        "total_critical_findings": total_critical,
        "total_high_findings": total_high,
        "average_readiness_score": avg_readiness,
        "overall_recommendation": (
            "Do not upgrade without remediation" if total_critical > 0
            else "Review required before upgrade" if total_high > 0
            else "Safe to proceed with upgrade"
        ),
    }

    _log_scan_event("info", f"AI analysis complete: {len(all_app_results)} apps, {total_critical} critical, {total_high} high findings")

    return results


@upgrade_router.post("/upgrade/ai-ask", summary="Ask AI about an app's configuration")
async def ai_ask_about_app(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ask a natural-language question about an app's configuration.

    Uses the LLM to analyze conf data and answer questions like:
    - "What index-time settings does this app have?"
    - "Are there any risky local overrides?"
    - "What would break if I upgrade this?"

    Body: {"app_id": "Splunk_TA_windows", "question": "What index-time settings does this app change?"}
    """
    app_id = body.get("app_id", "")
    question = body.get("question", "")

    if not app_id or not question:
        raise HTTPException(status_code=400, detail="Both app_id and question are required")

    inventory = _inventory_cache.get("deep_scan")
    if not inventory:
        raise HTTPException(status_code=404, detail="No scan data. Run deep-scan first.")

    baseline = getattr(inventory, "apps", {}).get(app_id)
    if not baseline:
        raise HTTPException(status_code=404, detail=f"App '{app_id}' not found")

    # Build context from app's conf data
    default_confs = getattr(baseline, "default_confs", {})
    local_confs = getattr(baseline, "local_confs", {})
    version = getattr(baseline, "version", None)

    context_parts = [
        f"App: {app_id}",
        f"Version: {getattr(version, 'version', 'unknown')}",
        f"Author: {getattr(version, 'author', 'unknown')}",
        f"Label: {getattr(version, 'label', app_id)}",
        f"Description: {getattr(version, 'description', '')}",
        f"Default conf files: {', '.join(default_confs.keys())}",
        f"Local override files: {', '.join(local_confs.keys())}",
        "",
    ]

    # Include key conf stanzas (limit to avoid token overflow)
    INDEX_TIME_KEYS = {"LINE_BREAKER", "SHOULD_LINEMERGE", "TIME_FORMAT", "TIME_PREFIX",
                       "MAX_TIMESTAMP_LOOKAHEAD", "TZ", "TRANSFORMS", "REPORT", "SEDCMD"}
    stanza_count = 0
    for conf_name in ["props", "transforms", "inputs", "outputs", "savedsearches", "eventtypes", "tags", "macros"]:
        if conf_name in default_confs and stanza_count < 30:
            context_parts.append(f"\n=== {conf_name}.conf (default) ===")
            for stanza_name, keys in list(default_confs[conf_name].items())[:15]:
                if stanza_name.startswith("__"):
                    continue
                clean = {k: v for k, v in keys.items() if not k.startswith("__")}
                if clean:
                    context_parts.append(f"[{stanza_name}]")
                    for k, v in list(clean.items())[:10]:
                        marker = " *INDEX-TIME*" if k.upper() in INDEX_TIME_KEYS else ""
                        context_parts.append(f"  {k} = {v}{marker}")
                    stanza_count += 1

        if conf_name in local_confs and stanza_count < 40:
            context_parts.append(f"\n=== {conf_name}.conf (local overrides) ===")
            for stanza_name, keys in list(local_confs[conf_name].items())[:10]:
                if stanza_name.startswith("__"):
                    continue
                clean = {k: v for k, v in keys.items() if not k.startswith("__")}
                if clean:
                    context_parts.append(f"[{stanza_name}] (LOCAL)")
                    for k, v in list(clean.items())[:10]:
                        context_parts.append(f"  {k} = {v}")
                    stanza_count += 1

    conf_context = "\n".join(context_parts)

    # Use LLM to answer
    try:
        from chat_app.llm_utils import generate_response
        prompt = (
            f"You are a Splunk configuration expert analyzing the app '{app_id}'. "
            f"Based on the configuration data below, answer the user's question.\n\n"
            f"Configuration Data:\n{conf_context}\n\n"
            f"Question: {question}\n\n"
            f"Provide a clear, technical answer. Mention specific stanzas, keys, and values. "
            f"Flag any risks (index-time changes, deprecated settings, merge conflicts). "
            f"Be concise but thorough."
        )
        answer = await asyncio.to_thread(generate_response, prompt, max_tokens=1024)
        return {"app_id": app_id, "question": question, "answer": answer, "stanzas_analyzed": stanza_count}
    except Exception as exc:
        logger.warning("[UPGRADE] AI ask failed: %s", exc)
        # Fallback: structured summary without LLM
        summary_parts = [f"App {app_id} v{getattr(version, 'version', '?')}:"]
        summary_parts.append(f"- {len(default_confs)} default conf files, {len(local_confs)} local override files")
        total_stanzas = sum(len(s) for s in default_confs.values())
        summary_parts.append(f"- {total_stanzas} total stanzas")
        if local_confs:
            summary_parts.append(f"- Local overrides in: {', '.join(local_confs.keys())}")
        return {"app_id": app_id, "question": question, "answer": "\n".join(summary_parts), "stanzas_analyzed": stanza_count, "llm_used": False}


@upgrade_router.post("/upgrade/inventory/scan", summary="Trigger repo scan")
async def scan_inventory(body: ScanRequest) -> Dict[str, Any]:
    """
    Trigger a fresh scan of the configured git repository.

    Walks the repo to find all Splunk app directories, parses their .conf
    files, and stores a ClusterInventory in the in-memory cache.
    """
    try:
        from chat_app.upgrade_readiness.baseline_builder import scan_cluster_directory

        repo_path = _resolve_repo_path(body.repo_path)

        clusters_to_scan: List[str] = []
        if body.cluster:
            clusters_to_scan = [body.cluster]
        else:
            # Auto-discover cluster directories
            repo = Path(repo_path)
            if repo.is_dir():
                clusters_to_scan = [
                    child.name
                    for child in repo.iterdir()
                    if child.is_dir() and not child.name.startswith(".")
                ]

        if not clusters_to_scan:
            return {
                "status": "ok",
                "message": f"No cluster directories found under {repo_path}",
                "scanned": [],
            }

        scanned: List[str] = []
        errors: List[str] = []

        for cluster_name in clusters_to_scan:
            cluster_path = str(Path(repo_path) / cluster_name)
            try:
                inventory = await asyncio.to_thread(
                    scan_cluster_directory, cluster_path
                )
                _inventory_cache[cluster_name] = inventory
                scanned.append(cluster_name)
                logger.info(
                    "[UPGRADE] Scanned cluster %s: %d apps",
                    cluster_name, len(inventory.apps),
                )
            except Exception as exc:  # broad catch — resilience at boundary
                errors.append(f"{cluster_name}: {exc}")
                logger.warning("[UPGRADE] Scan error for cluster %s: %s", cluster_name, exc)

        return {
            "status": "ok",
            "scanned": scanned,
            "errors": errors,
        }

    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=500, detail=_safe_error(exc, "inventory scan"))


@upgrade_router.get("/upgrade/inventory/{cluster}", summary="Apps for a cluster")
async def get_cluster_inventory(cluster: str) -> Dict[str, Any]:
    """
    Return the inventory for a specific cluster.

    Args:
        cluster: Cluster name as it appears in the repository.
    """
    inventory = _inventory_cache.get(cluster)
    if not inventory:
        raise HTTPException(
            status_code=404,
            detail=f"No inventory for cluster '{cluster}'. Run POST /upgrade/inventory/scan first.",
        )

    apps_data: Dict[str, Any] = {}
    for app_name, baseline in getattr(inventory, "apps", {}).items():
        version = getattr(baseline, "version", None)
        apps_data[app_name] = {
            "version": getattr(version, "version", "unknown") if version else "unknown",
            "label": getattr(version, "label", app_name) if version else app_name,
            "author": getattr(version, "author", "") if version else "",
            "conf_types": list(getattr(baseline, "default_confs", {}).keys()),
        }

    return {
        "cluster": cluster,
        "app_count": len(apps_data),
        "apps": apps_data,
        "scanned_at": getattr(inventory, "scanned_at", "").isoformat()
        if hasattr(getattr(inventory, "scanned_at", ""), "isoformat") else "",
        "errors": getattr(inventory, "errors", []),
    }


@upgrade_router.get(
    "/upgrade/repository/apps",
    summary="All apps with Splunkbase classification",
)
async def get_repository_apps(cluster: Optional[str] = None) -> Dict[str, Any]:
    """
    Return every app in the inventory, classified as Splunkbase-managed or custom.

    For Splunkbase-managed apps, includes latest available version, versions behind,
    and a direct link to navigate to upgrade readiness analysis.

    Query params:
        cluster: filter to a specific cluster (optional)
    """
    if not _inventory_cache:
        # After container restart, serve the persisted response from disk
        if _serialized_response_cache:
            return _serialized_response_cache
        return {
            "status": "empty",
            "message": "No inventory available. Run POST /upgrade/inventory/scan first.",
            "apps": [],
        }

    try:
        from chat_app.upgrade_readiness.splunkbase_fetcher import SplunkbaseFetcher

        fetcher = SplunkbaseFetcher()
        apps_list: List[Dict[str, Any]] = []

        clusters_to_check = (
            {cluster: _inventory_cache[cluster]}
            if cluster and cluster in _inventory_cache
            else _inventory_cache
        )

        for cluster_name, inventory in clusters_to_check.items():
            for app_name, baseline in getattr(inventory, "apps", {}).items():
                version = getattr(baseline, "version", None)
                installed_version = getattr(version, "version", "0.0.0") if version else "0.0.0"
                label = getattr(version, "label", app_name) if version else app_name
                author = getattr(version, "author", "") if version else ""
                description = getattr(version, "description", "") if version else ""

                # Classify: look up in Splunkbase catalog
                try:
                    catalog_entry = fetcher.find_app(app_name)
                except Exception:
                    catalog_entry = None
                is_splunkbase = catalog_entry is not None
                latest_version = ""
                versions_behind = 0
                splunkbase_url = ""
                latest_release_date = ""
                upgrade_available = False

                if catalog_entry:
                    latest_version = catalog_entry.get("latest_version", "")
                    latest_release_date = catalog_entry.get("latest_release_date", "")
                    splunkbase_uid = catalog_entry.get("uid", "")
                    if splunkbase_uid:
                        splunkbase_url = f"https://splunkbase.splunk.com/app/{splunkbase_uid}"

                    if latest_version and installed_version != "0.0.0":
                        from chat_app.upgrade_readiness.splunkbase_fetcher import _parse_version_tuple
                        installed_tuple = _parse_version_tuple(installed_version)
                        latest_tuple = _parse_version_tuple(latest_version)
                        if installed_tuple < latest_tuple:
                            upgrade_available = True
                            releases = catalog_entry.get("releases", [])
                            versions_behind = len([
                                r for r in releases
                                if _parse_version_tuple(r.get("version", "0")) > installed_tuple
                            ])

                conf_types = list(getattr(baseline, "default_confs", {}).keys())

                apps_list.append({
                    "cluster": cluster_name,
                    "app_id": app_name,
                    "label": label,
                    "installed_version": installed_version,
                    "author": author,
                    "description": description,
                    "splunkbase_managed": is_splunkbase,
                    "latest_version": latest_version,
                    "versions_behind": versions_behind,
                    "upgrade_available": upgrade_available,
                    "splunkbase_url": splunkbase_url,
                    "latest_release_date": latest_release_date,
                    "conf_files": conf_types,
                    "conf_count": len(conf_types),
                })

        # Sort: upgrade available first, then by app_id
        apps_list.sort(key=lambda a: (not a["upgrade_available"], a["app_id"]))

        splunkbase_count = sum(1 for a in apps_list if a["splunkbase_managed"])
        custom_count = len(apps_list) - splunkbase_count
        upgradeable_count = sum(1 for a in apps_list if a["upgrade_available"])

        return {
            "status": "ok",
            "total_apps": len(apps_list),
            "splunkbase_managed": splunkbase_count,
            "custom_apps": custom_count,
            "upgrades_available": upgradeable_count,
            "apps": apps_list,
            "scanned_at": _last_scanned_at.get("deep_scan", ""),
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "repository apps"))


@upgrade_router.get("/upgrade/candidates", summary="Apps with upgrades available")
async def get_upgrade_candidates() -> Dict[str, Any]:
    """
    Return all apps across all clusters that have newer Splunkbase versions available.
    """
    if not _inventory_cache:
        return {"status": "empty", "message": "Run inventory scan first.", "candidates": []}

    try:
        from chat_app.upgrade_readiness.baseline_builder import match_splunkbase_versions
        from chat_app.upgrade_readiness.splunkbase_fetcher import SplunkbaseFetcher, _parse_version_tuple

        fetcher = SplunkbaseFetcher()
        candidates: List[Dict[str, Any]] = []

        for cluster_name, inventory in _inventory_cache.items():
            # Enrich the inventory with catalog data in-place
            match_splunkbase_versions(inventory)

            for app_name, baseline in getattr(inventory, "apps", {}).items():
                version = getattr(baseline, "version", None)
                installed_version = getattr(version, "version", "0.0.0") if version else "0.0.0"

                # Check the catalog for a newer version
                catalog_entry = fetcher.find_app(app_name)
                if not catalog_entry:
                    continue

                latest_version = catalog_entry.get("latest_version", "unknown")
                if latest_version == "unknown":
                    continue

                if _parse_version_tuple(installed_version) < _parse_version_tuple(latest_version):
                    releases = catalog_entry.get("releases", [])
                    newer = [
                        r for r in releases
                        if _parse_version_tuple(r.get("version", "0")) > _parse_version_tuple(installed_version)
                    ]
                    candidates.append(
                        {
                            "cluster": cluster_name,
                            "app_id": app_name,
                            "installed_version": installed_version,
                            "latest_version": latest_version,
                            "versions_behind": len(newer),
                            "release_date": catalog_entry.get("latest_release_date", ""),
                        }
                    )

        return {
            "status": "ok",
            "candidate_count": len(candidates),
            "candidates": candidates,
        }

    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=500, detail=_safe_error(exc, "upgrade candidates"))


# ---------------------------------------------------------------------------
# Analysis endpoints
# ---------------------------------------------------------------------------


@upgrade_router.post("/upgrade/analyze", summary="Run full upgrade analysis")
async def analyze_upgrade(body: AnalyzeRequest) -> Dict[str, Any]:
    """
    Run a full upgrade impact analysis for a single app.

    Performs three-way conf diff, optional CIM compliance check, and
    optionally runs container-based live tests.

    Returns the UpgradeImpactReport serialised as JSON.
    """
    try:
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.impact_scorer import build_impact_report
        from chat_app.upgrade_readiness.report_builder import ReportBuilder

        # Resolve the installed app directory from the inventory cache
        inventory = _inventory_cache.get(body.cluster)
        old_baseline = None
        if inventory:
            old_baseline = inventory.apps.get(body.app_id)

        if old_baseline is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"App '{body.app_id}' not found in cluster '{body.cluster}' inventory. "
                    "Run POST /upgrade/inventory/scan first."
                ),
            )

        # Determine target version
        fetcher = _get_fetcher()
        target_version = body.target_version
        if not target_version:
            catalog_entry = fetcher.find_app(body.app_id)
            if catalog_entry:
                target_version = catalog_entry.get("latest_version", "unknown")
            else:
                target_version = "latest"

        # Download new version
        new_app_dir = await fetcher.download_version(body.app_id, target_version)

        all_findings = []
        new_confs: Dict[str, Any] = {}

        if new_app_dir:
            new_baseline = await asyncio.to_thread(scan_app_directory, new_app_dir)
            new_confs = new_baseline.default_confs

            # Three-way diff across all conf types
            all_conf_types = set(old_baseline.default_confs.keys()) | set(new_confs.keys())
            for conf_type in all_conf_types:
                old_default = old_baseline.get_default_stanzas(conf_type)
                new_default = new_baseline.get_default_stanzas(conf_type)
                local_stanzas = old_baseline.get_local_stanzas(conf_type)
                findings = three_way_diff(
                    old_default=old_default,
                    new_default=new_default,
                    local=local_stanzas,
                    conf_type=conf_type,
                    app_id=body.app_id,
                )
                all_findings.extend(findings)
        else:
            logger.warning(
                "[UPGRADE] Could not download %s %s — analysis limited to static baseline",
                body.app_id, target_version,
            )

        from_version = old_baseline.version.version if old_baseline.version else "unknown"
        report = build_impact_report(
            findings=all_findings,
            app_id=body.app_id,
            from_version=from_version,
            to_version=target_version,
            cluster=body.cluster,
        )

        # Optional container test
        container_results = None
        if body.include_container_test and new_app_dir:
            container_results = await _run_container_test(
                body.app_id, body.cluster, old_baseline.app_dir, new_app_dir
            )

        builder = ReportBuilder()
        final_report = builder.build_report(report, container_results=container_results)
        builder.save_report(final_report)
        _report_cache[final_report.report_id] = final_report

        # Run config auditor against the installed app's merged conf files
        config_audit_result = None
        readiness_score_result = None
        try:
            from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
            from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer

            # Merge default/ and local/ confs for audit
            merged_confs: Dict[str, Any] = {}
            for conf_type, stanzas in old_baseline.default_confs.items():
                merged = dict(stanzas)
                local = old_baseline.local_confs.get(conf_type, {})
                for stanza, keys in local.items():
                    merged.setdefault(stanza, {}).update(keys)
                merged_confs[conf_type] = merged

            auditor = ConfigAuditor()
            config_audit_result = await asyncio.to_thread(
                auditor.audit,
                conf_files=merged_confs,
                from_version=from_version,
                to_version=target_version,
            )

            scorer = ReadinessScorer()
            readiness_score_result = scorer.calculate_score(
                config_audit=config_audit_result,
                conf_diff_findings=all_findings,
            )
        except Exception as audit_exc:  # broad catch — audit is non-blocking
            logger.warning("[UPGRADE] Config audit failed for %s: %s", body.app_id, audit_exc)

        response: Dict[str, Any] = {
            "status": "ok",
            "report_id": final_report.report_id,
            "overall_risk": final_report.overall_risk.value,
            "recommendation": final_report.recommendation,
            "finding_count": len(final_report.findings),
            "critical_count": final_report.critical_count,
            "high_count": final_report.high_count,
        }

        if readiness_score_result is not None:
            response["readiness_score"] = readiness_score_result.to_dict()
            response["blockers"] = readiness_score_result.blocker_count

        if config_audit_result is not None:
            response["config_audit_findings"] = [
                f.to_dict() for f in config_audit_result.findings[:20]
            ]

        return response

    except HTTPException:
        raise
    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=500, detail=_safe_error(exc, "upgrade analysis"))


async def _run_container_test(
    app_id: str,
    cluster: str,
    old_app_dir: str,
    new_app_dir: str,
    splunk_version: str = "9.3.2",
) -> List[Any]:
    """
    Helper: deploy a test container, run validation tests, clean up.

    Returns a list of ContainerTestResult.
    """
    from chat_app.upgrade_readiness.container_tester import SplunkTestContainer

    tester = SplunkTestContainer()
    container_id = None
    try:
        container_id = await tester.deploy(
            cluster_name=cluster,
            apps_dirs={app_id: old_app_dir},
            splunk_version=splunk_version,
        )
        ready = await tester.wait_ready(container_id, timeout=300)
        if not ready:
            logger.warning("[UPGRADE] Container test container never became ready")
            return []

        # Capture before state
        await tester.capture_state(container_id)

        # Apply upgrade
        await tester.apply_upgrade(container_id, app_id, new_app_dir)
        ready = await tester.wait_ready(container_id, timeout=120)
        if not ready:
            logger.warning("[UPGRADE] Container not ready after upgrade")
            return []

        # Run tests
        results = await tester.run_validation_tests(container_id)
        return results

    except Exception as exc:  # broad catch — resilience at boundary
        logger.error("[UPGRADE] Container test failed: %s", exc)
        return []
    finally:
        if container_id:
            await tester.cleanup(container_id)


# ---------------------------------------------------------------------------
# Report endpoints
# ---------------------------------------------------------------------------


@upgrade_router.get("/upgrade/reports", summary="List past reports")
async def list_reports() -> Dict[str, Any]:
    """Return a summary list of all saved upgrade reports."""
    try:
        builder = _get_report_builder()
        summaries = builder.list_reports()
        return {
            "status": "ok",
            "count": len(summaries),
            "reports": summaries,
        }
    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=500, detail=_safe_error(exc, "list reports"))


@upgrade_router.get("/upgrade/reports/{report_id}", summary="Full report")
async def get_report(report_id: str) -> Dict[str, Any]:
    """
    Return the full JSON report for a given report_id.

    Args:
        report_id: UUID of the report.
    """
    # Check in-memory cache first
    report = _report_cache.get(report_id)
    if report is None:
        builder = _get_report_builder()
        report = builder.load_report(report_id)

    if report is None:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")

    try:
        builder = _get_report_builder()
        return {"status": "ok", "report": builder.to_json(report)}
    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=500, detail=_safe_error(exc, "get report"))


@upgrade_router.get("/upgrade/reports/{report_id}/markdown", summary="Report as Markdown")
async def get_report_markdown(report_id: str) -> Dict[str, Any]:
    """Return the upgrade report formatted as Markdown."""
    report = _report_cache.get(report_id)
    if report is None:
        builder = _get_report_builder()
        report = builder.load_report(report_id)

    if report is None:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")

    builder = _get_report_builder()
    return {"status": "ok", "markdown": builder.to_markdown(report)}


# ---------------------------------------------------------------------------
# Runbook endpoint
# ---------------------------------------------------------------------------


@upgrade_router.post("/upgrade/runbook", summary="Generate upgrade runbook")
async def generate_runbook(body: RunbookRequest) -> Dict[str, Any]:
    """
    Generate a step-by-step upgrade runbook from assessment results.

    Synthesizes config audit findings, conf diff results, and breaking changes
    into an ordered, phase-structured runbook with real Splunk CLI commands.

    When ``include_config_audit`` is True and ``conf_files`` are provided,
    runs the config auditor inline.  Otherwise generates a generic runbook
    for the specified version transition.
    """
    try:
        from chat_app.upgrade_readiness.runbook_generator import RunbookGenerator
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer
        from chat_app.upgrade_readiness.breaking_changes_db import get_breaking_changes_db

        config_audit = None
        readiness_score = None
        breaking_changes = []

        # Run config auditor if conf_files are provided
        if body.include_config_audit and body.conf_files:
            auditor = ConfigAuditor()
            config_audit = await asyncio.to_thread(
                auditor.audit,
                conf_files=body.conf_files,
                from_version=body.from_version,
                to_version=body.to_version,
            )

        # Pull breaking changes from DB
        db = get_breaking_changes_db()
        breaking_changes = await asyncio.to_thread(
            db.get_changes_between, body.from_version, body.to_version
        )

        # Calculate readiness score
        scorer = ReadinessScorer()
        readiness_score = scorer.calculate_score(
            config_audit=config_audit,
            breaking_changes=breaking_changes,
        )

        # Generate the runbook
        generator = RunbookGenerator()
        runbook = await asyncio.to_thread(
            generator.generate,
            from_version=body.from_version,
            to_version=body.to_version,
            upgrade_type=body.upgrade_type,
            config_audit=config_audit,
            breaking_changes=breaking_changes,
            readiness_score=readiness_score,
            app_id=body.app_id,
            cluster=body.cluster,
        )

        return {
            "status": "ok",
            "runbook": runbook.to_dict(),
            "markdown": runbook.to_markdown(),
            "readiness_score": readiness_score.to_dict() if readiness_score else None,
        }

    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=500, detail=_safe_error(exc, "runbook generation"))


# ---------------------------------------------------------------------------
# CIM + dependency endpoints
# ---------------------------------------------------------------------------


@upgrade_router.get("/upgrade/cim/{cluster}/{app}", summary="CIM compliance check")
async def get_cim_compliance(cluster: str, app: str) -> Dict[str, Any]:
    """
    Return CIM compliance status for an installed app.

    Args:
        cluster: Cluster name.
        app:     App folder name.
    """
    inventory = _inventory_cache.get(cluster)
    if not inventory:
        raise HTTPException(
            status_code=404,
            detail=f"No inventory for cluster '{cluster}'.",
        )

    baseline = inventory.apps.get(app)
    if not baseline:
        raise HTTPException(
            status_code=404,
            detail=f"App '{app}' not found in cluster '{cluster}'.",
        )

    try:
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance, get_cim_summary

        results = check_cim_compliance(baseline)
        summary = get_cim_summary(results)

        return {
            "status": "ok",
            "cluster": cluster,
            "app_id": app,
            "cim_summary": {
                "compliant_model_count": summary.get("compliant", 0),
                "partial_model_count": summary.get("partial", 0),
                "non_compliant_model_count": summary.get("non_compliant", 0),
            },
            "results": [
                {
                    "model": r.model_name,
                    "is_compliant": r.is_compliant,
                    "missing_fields": list(r.missing_required_fields),
                    "found_fields": list(r.found_fields),
                }
                for r in results
            ],
        }

    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=500, detail=_safe_error(exc, "CIM compliance"))


@upgrade_router.get("/upgrade/dependencies/{cluster}", summary="Dependency graph")
async def get_dependency_graph(cluster: str) -> Dict[str, Any]:
    """
    Return the cross-app dependency graph for a cluster.

    Args:
        cluster: Cluster name.
    """
    inventory = _inventory_cache.get(cluster)
    if not inventory:
        raise HTTPException(
            status_code=404,
            detail=f"No inventory for cluster '{cluster}'.",
        )

    try:
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            get_dependency_summary,
        )

        # Build a ClusterInventory from the cached data
        graph = build_dependency_graph(inventory)
        summary = get_dependency_summary(graph)

        return {
            "status": "ok",
            "cluster": cluster,
            "node_count": summary.get("node_count", 0),
            "edge_count": summary.get("edge_count", 0),
            "isolated_apps": summary.get("isolated_apps", []),
            "most_depended_upon": summary.get("most_depended_upon", []),
        }

    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=500, detail=_safe_error(exc, "dependency graph"))


# ---------------------------------------------------------------------------
# Container test endpoints
# ---------------------------------------------------------------------------


@upgrade_router.post("/upgrade/test", summary="Run container test")
async def run_container_test(body: ContainerTestRequest) -> Dict[str, Any]:
    """
    Run a container-based upgrade test for a specific app version transition.

    Downloads both versions, deploys a Splunk test container, and runs the
    full 15-category validation suite.
    """
    try:
        from chat_app.upgrade_readiness.models import ContainerTestSuite, TestStatus

        suite = ContainerTestSuite(
            app_id=body.app_id,
            from_version=body.from_version,
            to_version=body.to_version,
            splunk_version=body.splunk_version,
        )
        suite.status = TestStatus.RUNNING
        suite.started_at = datetime.now(timezone.utc)
        _test_suites[suite.suite_id] = suite

        fetcher = _get_fetcher()

        # Download both versions
        old_dir, new_dir = await asyncio.gather(
            fetcher.download_version(body.app_id, body.from_version),
            fetcher.download_version(body.app_id, body.to_version),
            return_exceptions=True,
        )

        if isinstance(old_dir, Exception) or not old_dir:
            suite.status = TestStatus.ERROR
            raise HTTPException(
                status_code=422,
                detail=f"Could not download {body.app_id} version {body.from_version}",
            )
        if isinstance(new_dir, Exception) or not new_dir:
            suite.status = TestStatus.ERROR
            raise HTTPException(
                status_code=422,
                detail=f"Could not download {body.app_id} version {body.to_version}",
            )

        results = await _run_container_test(
            app_id=body.app_id,
            cluster=body.cluster,
            old_app_dir=str(old_dir),
            new_app_dir=str(new_dir),
            splunk_version=body.splunk_version,
        )

        suite.results = results
        suite.status = TestStatus.PASSED if all(
            r.status in (TestStatus.PASSED, TestStatus.SKIPPED)
            for r in results
        ) else TestStatus.FAILED
        suite.completed_at = datetime.now(timezone.utc)

        return {
            "status": "ok",
            "suite_id": suite.suite_id,
            "test_status": suite.status.value,
            "passed": suite.passed_count,
            "failed": suite.failed_count,
            "total": len(suite.results),
        }

    except HTTPException:
        raise
    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=500, detail=_safe_error(exc, "container test"))


@upgrade_router.get("/upgrade/test/{suite_id}", summary="Test results")
async def get_test_results(suite_id: str) -> Dict[str, Any]:
    """
    Return the results of a container test suite.

    Args:
        suite_id: UUID of the test suite.
    """
    suite = _test_suites.get(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail=f"Test suite '{suite_id}' not found")

    return {
        "suite_id": suite.suite_id,
        "app_id": suite.app_id,
        "from_version": suite.from_version,
        "to_version": suite.to_version,
        "splunk_version": suite.splunk_version,
        "status": suite.status.value,
        "started_at": suite.started_at.isoformat() if suite.started_at else None,
        "completed_at": suite.completed_at.isoformat() if suite.completed_at else None,
        "passed": suite.passed_count,
        "failed": suite.failed_count,
        "results": [
            {
                "test_id": r.test_id,
                "name": r.name,
                "status": r.status.value,
                "duration_seconds": r.duration_seconds,
                "output": r.output[:500] if r.output else "",
                "error": r.error[:200] if r.error else "",
            }
            for r in suite.results
        ],
    }


# ---------------------------------------------------------------------------
# Platform intelligence routes — moved to admin_upgrade_platform_routes.py
# ---------------------------------------------------------------------------
# The following endpoints live in admin_upgrade_platform_routes.py:
#   GET /upgrade/types
#   GET /upgrade/advisor/{app_id}
#   GET /upgrade/versions/{app_id}
#   GET /upgrade/search
#   GET /upgrade/platform-versions
#   GET /upgrade/repo-scan
#   GET /upgrade/enterprise-versions
#   GET /upgrade/es-versions
#   GET /upgrade/security-advisories
#   GET /upgrade/version-diff
#   GET /upgrade/itsi-versions
#   GET /upgrade/release-path/{app_id}
#
# Backward-compatible re-export so existing imports still resolve:
from chat_app.admin_upgrade_platform_routes import upgrade_platform_router  # noqa: E402,F401
