"""
Admin API routes for Splunk Upgrade Readiness — Platform Intelligence.

Covers version intelligence, advisor, search, platform version history,
enterprise/ES/ITSI release data, security advisories, version diff, and
release path endpoints under /api/admin/upgrade/*.

Mount alongside the core upgrade router:
    from chat_app.admin_upgrade_platform_routes import upgrade_platform_router
    app.include_router(upgrade_platform_router)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends

from chat_app.admin_shared import (
    _csrf_check,
    _rate_limit,
    _track_audit_user,
)
from chat_app.auth_dependencies import require_admin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

upgrade_platform_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-upgrade-platform"],
    dependencies=[
        Depends(_rate_limit),
        Depends(require_admin),
        Depends(_track_audit_user),
        Depends(_csrf_check),
    ],
)


# ---------------------------------------------------------------------------
# Upgrade type capabilities
# ---------------------------------------------------------------------------


@upgrade_platform_router.get("/upgrade/types", summary="Get upgrade type capabilities")
async def get_upgrade_types() -> Dict[str, Any]:
    """Return detailed capability info for all upgrade types."""
    from chat_app.upgrade_readiness.upgrade_advisor import UPGRADE_TYPE_INFO

    return {
        "types": {
            k: {
                "label": v["label"],
                "description": v["description"],
                "what_we_check": v["what_we_check"],
                "what_we_need": v["what_we_need"],
                "risks": v["risks"],
            }
            for k, v in UPGRADE_TYPE_INFO.items()
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Upgrade advisor
# ---------------------------------------------------------------------------


@upgrade_platform_router.get(
    "/upgrade/advisor/{app_id}", summary="Get upgrade advice for an app"
)
async def get_upgrade_advice(
    app_id: str,
    upgrade_type: str = "ta",
    current_version: str = "",
) -> Dict[str, Any]:
    """Get comprehensive upgrade advice: version history, upgrade path,
    pre-flight checklist, and execution steps."""
    from chat_app.upgrade_readiness.upgrade_advisor import (
        get_upgrade_advice as _get_advice,
    )

    result = _get_advice(app_id, upgrade_type, current_version)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------


@upgrade_platform_router.get(
    "/upgrade/versions/{app_id}", summary="Get version history for an app"
)
async def get_app_versions(app_id: str) -> Dict[str, Any]:
    """Return all known versions for an app from the Splunkbase catalog."""
    from chat_app.upgrade_readiness.upgrade_advisor import (
        get_version_history,
        lookup_app,
    )

    app_data = lookup_app(app_id)
    if not app_data:
        return {
            "app_id": app_id,
            "found": False,
            "versions": [],
            "message": "App not found in Splunkbase catalog",
        }
    versions = get_version_history(app_data)
    return {
        "app_id": app_id,
        "found": True,
        "title": app_data.get("title", ""),
        "latest_version": app_data.get("latest_version", ""),
        "total_releases": len(versions),
        "versions": [
            {
                "version": v.version,
                "release_date": v.release_date,
                "supported_splunk": v.supported_splunk_versions[:5],
                "is_latest": v.is_latest,
            }
            for v in versions
        ],
    }


# ---------------------------------------------------------------------------
# Splunkbase catalog search
# ---------------------------------------------------------------------------


@upgrade_platform_router.get(
    "/upgrade/search", summary="Search Splunkbase catalog"
)
async def search_splunkbase(q: str = "", limit: int = 20) -> Dict[str, Any]:
    """Search the Splunkbase catalog by name or app_id."""
    try:
        from chat_app.splunkbase_catalog import get_splunkbase_catalog
        catalog = get_splunkbase_catalog()
        apps = catalog.catalog.get("apps", {})

        q_lower = q.lower()
        results = []
        for uid, a in apps.items():
            title = a.get("title", "")
            aid = a.get("app_id", "")
            if q_lower in title.lower() or q_lower in aid.lower():
                results.append(
                    {
                        "uid": uid,
                        "app_id": aid,
                        "title": title,
                        "latest_version": a.get("latest_version", ""),
                        "releases": len(a.get("releases", [])),
                    }
                )
                if len(results) >= limit:
                    break

        return {"query": q, "results": results, "total": len(results)}
    except (
        ImportError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
    ) as exc:
        return {"query": q, "results": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Platform versions
# ---------------------------------------------------------------------------


@upgrade_platform_router.get(
    "/upgrade/platform-versions", summary="Latest Splunk platform versions"
)
async def get_platform_versions() -> Dict[str, Any]:
    """Return latest known versions for Splunk Enterprise, UF, ES, ITSI."""
    es_version = "unknown"
    itsi_version = "unknown"
    try:
        from chat_app.upgrade_readiness.upgrade_advisor import lookup_app

        es = lookup_app("SplunkEnterpriseSecurityInstaller")
        if es:
            es_version = es.get("latest_version", "unknown")


        # ITSI product is app_id="itsi" (UID 1841), NOT xmatters_itsi or other add-ons
        itsi_app = lookup_app("itsi")
        if itsi_app:
            itsi_version = itsi_app.get("latest_version", itsi_version)
        else:
            # Fallback: search catalog by UID 1841
            from chat_app.splunkbase_catalog import get_splunkbase_catalog
            catalog = get_splunkbase_catalog()
            itsi_data = catalog.catalog.get("apps", {}).get("1841")
            if itsi_data:
                itsi_version = itsi_data.get("latest_version", itsi_version)
    except (
        ImportError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
    ):
        pass

    enterprise_latest = "10.2.4"
    try:
        from chat_app.upgrade_readiness.platform_versions import (
            SPLUNK_ENTERPRISE_RELEASES,
        )

        if SPLUNK_ENTERPRISE_RELEASES:
            enterprise_latest = SPLUNK_ENTERPRISE_RELEASES[0].version
    except (ImportError, IndexError):
        pass

    return {
        "enterprise": enterprise_latest,
        "uf": enterprise_latest,  # UF follows Enterprise versioning
        "es": es_version,
        "itsi": itsi_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Org repo scan
# ---------------------------------------------------------------------------


@upgrade_platform_router.get(
    "/upgrade/repo-scan", summary="Scan org repo for installed app versions"
)
async def scan_org_repo() -> Dict[str, Any]:
    """Scan the org Splunk repo for all installed apps and their versions."""
    import os

    from chat_app.upgrade_readiness.baseline_builder import scan_app_directory

    repo_base = "documents/repo/splunk"
    if not os.path.exists(repo_base):
        return {
            "status": "empty",
            "message": f"Org repo not found at {repo_base}",
            "clusters": {},
        }

    clusters: Dict[str, Any] = {}
    for root, dirs, files in os.walk(repo_base):
        for directory in dirs:
            app_dir = os.path.join(root, directory)
            default_dir = os.path.join(app_dir, "default")
            if not os.path.exists(default_dir):
                continue
            app_conf = os.path.join(default_dir, "app.conf")
            if not os.path.exists(app_conf):
                continue

            rel_path = os.path.relpath(root, repo_base)
            parts = rel_path.split(os.sep)
            cluster = parts[1] if len(parts) > 1 else parts[0]
            if cluster == "apps":
                cluster = parts[0] if parts else "unknown"

            try:
                baseline = scan_app_directory(app_dir)
                version = (
                    baseline.version.version if baseline.version else "unknown"
                )
                local_count = sum(
                    len(s) for s in baseline.local_confs.values()
                )

                if cluster not in clusters:
                    clusters[cluster] = []
                clusters[cluster].append(
                    {
                        "app_id": directory,
                        "version": version,
                        "label": baseline.version.label
                        if baseline.version
                        else directory,
                        "local_customizations": local_count,
                        "path": app_dir,
                    }
                )
            except (
                ImportError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                RuntimeError,
            ):
                pass

    return {
        "status": "ok",
        "repo_path": repo_base,
        "total_clusters": len(clusters),
        "total_apps": sum(len(v) for v in clusters.values()),
        "clusters": clusters,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Platform version intelligence
# ---------------------------------------------------------------------------


@upgrade_platform_router.get(
    "/upgrade/enterprise-versions",
    summary="Splunk Enterprise/UF version history",
)
async def get_enterprise_versions() -> Dict[str, Any]:
    """Return all known Splunk Enterprise versions with features, breaking changes, and CVEs."""
    from chat_app.upgrade_readiness.platform_versions import (
        get_enterprise_versions as _get,
    )

    return {"versions": _get(), "product": "enterprise/uf"}


@upgrade_platform_router.get(
    "/upgrade/es-versions", summary="Splunk ES version history"
)
async def get_es_versions() -> Dict[str, Any]:
    """Return all ES versions with release notes and compatibility."""
    from chat_app.upgrade_readiness.platform_versions import (
        get_es_versions as _get,
    )

    return {"versions": _get(), "product": "es"}


@upgrade_platform_router.get(
    "/upgrade/security-advisories", summary="Splunk security advisories"
)
async def get_security_advisories(
    from_version: str = "",
    to_version: str = "",
) -> Dict[str, Any]:
    """Return security advisories, optionally filtered by upgrade path."""
    from chat_app.upgrade_readiness.platform_versions import (
        get_security_advisories as _get,
    )

    advisories = _get(from_version, to_version)
    return {
        "advisories": advisories,
        "total": len(advisories),
        "filter": {"from_version": from_version, "to_version": to_version},
    }


@upgrade_platform_router.get(
    "/upgrade/version-diff", summary="Compare two platform versions"
)
async def get_version_diff(
    product: str = "enterprise",
    from_version: str = "",
    to_version: str = "",
) -> Dict[str, Any]:
    """Get comprehensive diff between two versions: features, breaking changes, CVEs."""
    from chat_app.upgrade_readiness.platform_versions import (
        get_version_diff as _get,
    )

    return _get(product, from_version, to_version)


@upgrade_platform_router.get(
    "/upgrade/itsi-versions", summary="ITSI version history"
)
async def get_itsi_versions() -> Dict[str, Any]:
    """Return all ITSI versions with release notes from Splunkbase."""
    try:
        from chat_app.upgrade_readiness.upgrade_advisor import (
            get_version_history,
            lookup_app,
        )

        app_data = lookup_app("itsi")
        if not app_data:
            from chat_app.splunkbase_catalog import get_splunkbase_catalog
            catalog = get_splunkbase_catalog()
            for uid, a in catalog.catalog.get("apps", {}).items():
                if a.get("app_id") == "itsi" or "IT Service Intelligence" in a.get(
                    "title", ""
                ):
                    app_data = a
                    break

        if not app_data:
            return {
                "versions": [],
                "product": "itsi",
                "error": "ITSI not found in catalog",
            }

        versions = []
        for r in app_data.get("releases", []):
            versions.append(
                {
                    "version": r.get("version", ""),
                    "release_date": r.get("release_date", "")[:10]
                    if r.get("release_date")
                    else "",
                    "supported_splunk": r.get("product_versions", [])[:5],
                    "key_features": [],
                    "breaking_changes": [],
                    "is_latest": r.get("version") == app_data.get("latest_version"),
                }
            )

        return {
            "versions": versions,
            "product": "itsi",
            "app_title": app_data.get("title", "ITSI"),
            "latest_version": app_data.get("latest_version", ""),
        }
    except (
        ImportError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
    ) as exc:
        return {"versions": [], "product": "itsi", "error": str(exc)}


@upgrade_platform_router.get(
    "/upgrade/release-path/{app_id}",
    summary="Show all releases between two versions",
)
async def get_release_path(
    app_id: str,
    from_version: str = "",
    to_version: str = "",
) -> Dict[str, Any]:
    """Show detailed release path between two versions of any app.

    For each intermediate release, shows: version, date, supported Splunk versions.
    Also fetches app description from Splunkbase for any available change notes.
    """
    from chat_app.upgrade_readiness.upgrade_advisor import (
        get_version_history,
        lookup_app,
    )

    app_data = lookup_app(app_id)
    if not app_data:
        return {"app_id": app_id, "found": False, "releases": []}

    all_versions = get_version_history(app_data)

    # Oldest-first for path calculation
    all_versions_asc = list(reversed(all_versions))

    path_versions = []
    include = False
    for v in all_versions_asc:
        if v.version == from_version:
            include = True
            path_versions.append(
                {
                    "version": v.version,
                    "release_date": v.release_date,
                    "supported_splunk": v.supported_splunk_versions[:5],
                    "is_current": True,
                    "is_target": False,
                    "position": "start",
                }
            )
            continue
        if include:
            is_target = (v.version == to_version) or (
                not to_version and v.is_latest
            )
            path_versions.append(
                {
                    "version": v.version,
                    "release_date": v.release_date,
                    "supported_splunk": v.supported_splunk_versions[:5],
                    "is_current": False,
                    "is_target": is_target,
                    "position": "target" if is_target else "intermediate",
                }
            )
            if is_target:
                break

    # Fallback: show all versions if from_version not found
    if not path_versions:
        for v in all_versions_asc:
            path_versions.append(
                {
                    "version": v.version,
                    "release_date": v.release_date,
                    "supported_splunk": v.supported_splunk_versions[:5],
                    "is_current": v.version == from_version,
                    "is_target": v.is_latest
                    if not to_version
                    else v.version == to_version,
                    "position": "current"
                    if v.version == from_version
                    else ("latest" if v.is_latest else ""),
                }
            )

    description = app_data.get("description", "")
    release_notes_url = (
        f"https://splunkbase.splunk.com/app/{app_data.get('uid', '')}"
    )

    return {
        "app_id": app_id,
        "app_title": app_data.get("title", app_id),
        "found": True,
        "from_version": from_version,
        "to_version": to_version or app_data.get("latest_version", ""),
        "total_releases": len(all_versions),
        "releases_in_path": len(path_versions),
        "releases": path_versions,
        "description": description[:2000] if description else "",
        "splunkbase_url": release_notes_url,
        "note": (
            "For full release notes, visit the Splunkbase page. "
            "Conf-level diff requires both versions available in the org repo."
        ),
    }
