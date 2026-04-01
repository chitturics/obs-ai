"""
SplunkbaseCatalogMixin — larger method implementations for SplunkbaseCatalog.

Split from splunkbase_catalog.py to keep that file under 600 lines.
Contains: update_catalog, get_installed_apps_from_splunk, compare_installed,
          _count_versions_behind, generate_report, _catalog_only_report,
          _format_comparison_report, get_catalog_summary
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SplunkbaseCatalogMixin:
    """Mixin providing update, comparison, and report methods for SplunkbaseCatalog."""

    # ------------------------------------------------------------------
    # Catalog update
    # ------------------------------------------------------------------

    async def update_catalog(self, incremental: bool = True, force: bool = False) -> Dict[str, Any]:
        """
        Refresh the catalog from the Splunkbase API.

        Args:
            incremental: If True, only update apps already in the catalog
                         and add new top apps. If False, rebuild from scratch.
            force: If False (default), skip update if catalog was updated within
                   the last 12 hours. Set True to bypass the age check.

        For full rebuilds, app metadata is extracted directly from the
        paginated list response to avoid thousands of individual detail
        API calls.  Per-app detail fetches are only used during incremental
        updates of existing catalog entries.

        Returns:
            A summary dict with counts of updated/added/failed apps.
        """
        from chat_app.splunkbase_catalog import _now_iso
        from datetime import datetime, timezone

        # Ensure catalog is loaded from disk before checking age
        if not self._loaded:
            self.load_catalog()

        # Skip if catalog was recently updated (avoid 1820×2 API calls at every startup)
        if not force:
            last_updated = self._catalog.get("metadata", {}).get("last_updated", "")
            if last_updated:
                try:
                    last_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                    age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                    if age_hours < 12:
                        logger.info(
                            "[SPLUNKBASE] Catalog is %.1f hours old (< 12h) — skipping refresh. Use force=True to override.",
                            age_hours,
                        )
                        return {"skipped": True, "reason": f"catalog_fresh ({age_hours:.1f}h old)", "age_hours": round(age_hours, 1)}
                except (ValueError, TypeError, AttributeError):
                    pass  # Can't parse timestamp — proceed with update

        summary = {
            "started_at": _now_iso(),
            "updated": 0,
            "added": 0,
            "failed": 0,
            "total": 0,
        }

        if incremental and self._catalog.get("apps"):
            # Update existing entries — fetch details per app
            uids = list(self._catalog["apps"].keys())
            logger.info("[SPLUNKBASE] Incremental update: refreshing %d existing apps", len(uids))
            for uid in uids:
                details = await self.fetch_app_details(uid)
                if details:
                    self._catalog["apps"][uid] = details
                    summary["updated"] += 1
                else:
                    summary["failed"] += 1
        else:
            # Full rebuild — fetch ALL apps from paginated list endpoint.
            # Extract data directly from the list response (no per-app calls).
            logger.info("[SPLUNKBASE] Full catalog rebuild — fetching all apps from API")
            apps = await self.fetch_app_list()
            for app_data in apps:
                uid = str(app_data.get("uid", app_data.get("id", "")))
                if not uid:
                    continue
                try:
                    entry = self._extract_app_from_list(app_data)
                    if uid in self._catalog.get("apps", {}):
                        summary["updated"] += 1
                    else:
                        summary["added"] += 1
                    self._catalog.setdefault("apps", {})[uid] = entry
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                    logger.debug("[SPLUNKBASE] Failed to parse app %s: %s", uid, exc)
                    summary["failed"] += 1

        summary["total"] = len(self._catalog.get("apps", {}))
        summary["finished_at"] = _now_iso()

        self._catalog["metadata"] = {
            "last_updated": _now_iso(),
            "total_apps": summary["total"],
            "source": "splunkbase_api",
        }

        self.save_catalog()
        logger.info(
            "[SPLUNKBASE] Catalog update complete: %d updated, %d added, %d failed, %d total",
            summary["updated"], summary["added"], summary["failed"], summary["total"],
        )
        return summary

    # ------------------------------------------------------------------
    # Installed apps (from Splunk REST API)
    # ------------------------------------------------------------------

    async def get_installed_apps_from_splunk(
        self, splunk_url: str, token: str, verify_ssl: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Fetch installed apps from a Splunk instance via REST API.

        Calls ``/services/apps/local?output_mode=json`` on the management port.

        Returns a list of dicts with keys: name, version, label, visible, disabled.
        """
        try:
            import httpx
        except ImportError:
            logger.error("[SPLUNKBASE] httpx not installed — cannot query Splunk")
            return []

        url = f"{splunk_url.rstrip('/')}/services/apps/local"
        params = {"output_mode": "json", "count": 0}
        headers = {"Authorization": f"Bearer {token}"}

        data = {}
        try:
            async with httpx.AsyncClient(
                timeout=30.0, verify=verify_ssl, follow_redirects=True,
            ) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            logger.error("[SPLUNKBASE] Failed to fetch installed apps from %s: %s", splunk_url, exc)
            return []

        installed = []
        for entry in data.get("entry", []):
            content = entry.get("content", {})
            installed.append({
                "name": entry.get("name", ""),
                "version": content.get("version", "unknown"),
                "label": content.get("label", entry.get("name", "")),
                "visible": content.get("visible", True),
                "disabled": content.get("disabled", False),
                "author": content.get("author", ""),
                "updated": entry.get("updated", ""),
            })

        logger.info("[SPLUNKBASE] Retrieved %d installed apps from %s", len(installed), splunk_url)
        return installed

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def compare_installed(self, installed_apps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare installed apps against the catalog.

        Args:
            installed_apps: List of dicts from get_installed_apps_from_splunk()

        Returns:
            A comparison result dict with categories:
            - outdated: apps with newer versions available
            - current: apps at latest version
            - unknown: installed apps not found in catalog
        """
        from chat_app.splunkbase_catalog import _now_iso, _is_outdated

        if not self._loaded:
            self.load_catalog()

        catalog_apps = self._catalog.get("apps", {})

        # Build a lookup by app_id (the Splunk folder name) for matching
        catalog_by_app_id: Dict[str, Dict] = {}
        catalog_by_title: Dict[str, Dict] = {}
        for uid, app_data in catalog_apps.items():
            aid = app_data.get("app_id", "").lower()
            if aid:
                catalog_by_app_id[aid] = app_data
            title = app_data.get("title", "").lower()
            if title:
                catalog_by_title[title] = app_data

        outdated: List[Dict[str, Any]] = []
        current: List[Dict[str, Any]] = []
        unknown: List[Dict[str, Any]] = []

        for inst in installed_apps:
            inst_name = inst.get("name", "").lower()
            inst_label = inst.get("label", "").lower()
            inst_version = inst.get("version", "unknown")

            # Try to match against catalog
            match = (
                catalog_by_app_id.get(inst_name)
                or catalog_by_title.get(inst_label)
                or catalog_by_title.get(inst_name)
            )

            if match is None:
                unknown.append({
                    "name": inst.get("name"),
                    "label": inst.get("label"),
                    "installed_version": inst_version,
                    "status": "not_in_catalog",
                })
                continue

            latest = match.get("latest_version", "unknown")
            entry = {
                "name": inst.get("name"),
                "label": inst.get("label"),
                "installed_version": inst_version,
                "latest_version": latest,
                "latest_release_date": match.get("latest_release_date", ""),
                "supported_splunk_versions": match.get("supported_splunk_versions", []),
                "uid": match.get("uid", ""),
            }

            if inst_version == "unknown" or latest == "unknown":
                unknown.append({**entry, "status": "version_unknown"})
            elif _is_outdated(inst_version, latest):
                entry["status"] = "outdated"
                entry["versions_behind"] = self._count_versions_behind(
                    inst_version, match.get("releases", [])
                )
                outdated.append(entry)
            else:
                entry["status"] = "current"
                current.append(entry)

        return {
            "outdated": outdated,
            "current": current,
            "unknown": unknown,
            "summary": {
                "total_installed": len(installed_apps),
                "outdated_count": len(outdated),
                "current_count": len(current),
                "unknown_count": len(unknown),
                "timestamp": _now_iso(),
            },
        }

    def _count_versions_behind(self, installed_version: str, releases: List[Dict]) -> int:
        """Count how many releases are newer than the installed version."""
        from chat_app.splunkbase_catalog import _parse_version_tuple

        inst_tuple = _parse_version_tuple(installed_version)
        count = 0
        for rel in releases:
            rel_tuple = _parse_version_tuple(rel.get("version", "0"))
            if rel_tuple > inst_tuple:
                count += 1
        return count

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    async def generate_report(
        self,
        splunk_url: Optional[str] = None,
        token: Optional[str] = None,
        verify_ssl: bool = True,
        installed_apps: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Generate a markdown report of app version status.

        If installed_apps is not provided, fetches from Splunk REST API.
        """
        if installed_apps is None:
            if not splunk_url or not token:
                return self._catalog_only_report()
            installed_apps = await self.get_installed_apps_from_splunk(
                splunk_url, token, verify_ssl,
            )

        if not installed_apps:
            return "No installed apps found. Check Splunk connection settings."

        comparison = self.compare_installed(installed_apps)
        return self._format_comparison_report(comparison)

    def _catalog_only_report(self) -> str:
        """Generate a report from the catalog without comparison data."""
        if not self._loaded:
            self.load_catalog()

        apps = self._catalog.get("apps", {})
        if not apps:
            return "Splunkbase catalog is empty. Run a catalog refresh first."

        meta = self._catalog.get("metadata", {})
        lines = [
            "## Splunkbase Catalog Summary",
            "",
            f"**Last Updated:** {meta.get('last_updated', 'Never')}",
            f"**Total Apps:** {meta.get('total_apps', 0)}",
            "",
            "| App | Latest Version | Release Date |",
            "|-----|---------------|-------------|",
        ]

        for uid, app_data in sorted(apps.items(), key=lambda x: x[1].get("title", "")):
            title = app_data.get("title", uid)
            version = app_data.get("latest_version", "?")
            date = app_data.get("latest_release_date", "?")
            if date and "T" in date:
                date = date.split("T")[0]
            lines.append(f"| {title} | {version} | {date} |")

        lines.append("")
        lines.append("*Configure `splunkbase_catalog.splunk_url` and `splunk_token` to compare against installed apps.*")
        return "\n".join(lines)

    def _format_comparison_report(self, comparison: Dict[str, Any]) -> str:
        """Format a full comparison report as markdown."""
        from chat_app.splunkbase_catalog import _now_iso

        summary = comparison.get("summary", {})
        outdated = comparison.get("outdated", [])
        current = comparison.get("current", [])
        unknown = comparison.get("unknown", [])

        lines = [
            "## Splunkbase Add-on Version Report",
            "",
            f"**Generated:** {summary.get('timestamp', _now_iso())}",
            f"**Total Installed:** {summary.get('total_installed', 0)}",
            f"**Outdated:** {summary.get('outdated_count', 0)}",
            f"**Current:** {summary.get('current_count', 0)}",
            f"**Not in Catalog:** {summary.get('unknown_count', 0)}",
            "",
        ]

        if outdated:
            lines.append("### Outdated Apps (Upgrade Recommended)")
            lines.append("")
            lines.append("| App | Installed | Latest | Versions Behind | Latest Release |")
            lines.append("|-----|-----------|--------|----------------|----------------|")
            for app in sorted(outdated, key=lambda a: a.get("versions_behind", 0), reverse=True):
                name = app.get("label", app.get("name", "?"))
                inst = app.get("installed_version", "?")
                latest = app.get("latest_version", "?")
                behind = app.get("versions_behind", "?")
                date = app.get("latest_release_date", "?")
                if date and "T" in date:
                    date = date.split("T")[0]
                lines.append(f"| {name} | {inst} | {latest} | {behind} | {date} |")
            lines.append("")

        if current:
            lines.append("### Current Apps")
            lines.append("")
            lines.append(f"*{len(current)} app(s) are at their latest version.*")
            lines.append("")

        if unknown:
            lines.append("### Apps Not Found in Catalog")
            lines.append("")
            lines.append("| App | Installed Version | Status |")
            lines.append("|-----|------------------|--------|")
            for app in unknown:
                name = app.get("label", app.get("name", "?"))
                inst = app.get("installed_version", "?")
                status = app.get("status", "?")
                lines.append(f"| {name} | {inst} | {status} |")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Catalog summary (for admin API)
    # ------------------------------------------------------------------

    def get_catalog_summary(self) -> Dict[str, Any]:
        """Return a lightweight summary of the catalog for the admin dashboard."""
        if not self._loaded:
            self.load_catalog()

        apps = self._catalog.get("apps", {})
        meta = self._catalog.get("metadata", {})
        return {
            "total_apps": len(apps),
            "last_updated": meta.get("last_updated"),
            "catalog_path": str(self._catalog_path),
            "loaded": self._loaded,
            "top_apps": [
                {
                    "uid": uid,
                    "title": app.get("title", ""),
                    "latest_version": app.get("latest_version", ""),
                }
                for uid, app in list(apps.items())[:20]
            ],
        }
