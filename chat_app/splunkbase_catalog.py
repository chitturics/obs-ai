"""
Splunkbase Add-on Version Validator — Catalog & comparison engine.

Maintains a local JSON catalog of Splunkbase apps/TAs and compares them
against a user's installed Splunk apps to flag outdated versions.

Features:
    - Paginated fetch from the Splunkbase REST API
    - Per-app version history with release dates and supported Splunk versions
    - Comparison against installed apps via Splunk REST API
    - Markdown report generation for outdated / EOL apps
    - Periodic catalog refresh (scheduled via scheduler.py)
    - Feature-flagged — disabled by default

Usage::

    from chat_app.splunkbase_catalog import get_splunkbase_catalog

    catalog = get_splunkbase_catalog()
    await catalog.update_catalog()
    report = await catalog.generate_report()
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from chat_app.splunkbase_catalog_impl import SplunkbaseCatalogMixin  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPLUNKBASE_API_BASE = "https://splunkbase.splunk.com/api/v1/app/"
DEFAULT_CATALOG_PATH = "/app/data/splunkbase_catalog.json"
DEFAULT_PAGE_SIZE = 100  # max efficient page size for Splunkbase API
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # seconds


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _parse_version_tuple(version_str: str) -> Tuple[int, ...]:
    """
    Parse a version string like '4.2.1' into a comparable tuple (4, 2, 1).

    Non-numeric segments are treated as 0.
    """
    parts = []
    for part in version_str.split("."):
        try:
            parts.append(int(part))
        except (ValueError, TypeError):
            parts.append(0)
    return tuple(parts)


def _is_outdated(installed_version: str, latest_version: str) -> bool:
    """Return True if installed_version is older than latest_version."""
    return _parse_version_tuple(installed_version) < _parse_version_tuple(latest_version)


# ---------------------------------------------------------------------------
# SplunkbaseCatalog — core class
# ---------------------------------------------------------------------------

class SplunkbaseCatalog(SplunkbaseCatalogMixin):
    """
    Local catalog of Splunkbase apps with version comparison capabilities.

    Catalog structure::

        {
            "metadata": {
                "last_updated": "2026-03-04T12:00:00+00:00",
                "total_apps": 42,
                "source": "splunkbase_api"
            },
            "apps": {
                "<app_uid>": {
                    "uid": "1234",
                    "title": "Splunk Add-on for ...",
                    "app_id": "Splunk_TA_...",
                    "latest_version": "5.2.0",
                    "latest_release_date": "2025-11-15T...",
                    "supported_splunk_versions": ["9.4", "9.3"],
                    "sourcetypes": ["syslog", "WinEventLog"],
                    "releases": [
                        {
                            "version": "5.2.0",
                            "release_date": "2025-11-15T...",
                            "product_versions": ["9.4", "9.3"],
                        },
                        ...
                    ],
                    "last_fetched": "2026-03-04T12:00:00+00:00"
                }
            }
        }
    """

    def __init__(self, catalog_path: Optional[str] = None, max_apps: int = 0):
        self._catalog_path = Path(catalog_path or DEFAULT_CATALOG_PATH)
        self._max_apps = max_apps  # 0 = fetch all available apps
        self._catalog: Dict[str, Any] = {"metadata": {}, "apps": {}}
        self._loaded = False

    # ------------------------------------------------------------------
    # Catalog I/O
    # ------------------------------------------------------------------

    def load_catalog(self) -> Dict[str, Any]:
        """Load catalog from local JSON cache or mounted documents directory.

        Search order:
        1. Configured catalog_path (/app/data/splunkbase_catalog.json)
        2. Mounted documents: /app/shared/public/documents/splunkbase_catalog.json
        3. Mounted documents: /app/public/documents/splunkbase_catalog.json
        """
        # Try primary path first
        search_paths = [
            self._catalog_path,
            Path("/app/shared/public/documents/splunkbase_catalog.json"),
            Path("/app/public/documents/splunkbase_catalog.json"),
        ]

        for path in search_paths:
            if path.is_file():
                try:
                    raw = path.read_text(encoding="utf-8")
                    data = json.loads(raw)
                    app_count = len(data.get("apps", {}))
                    if app_count > 0:
                        self._catalog = data
                        self._loaded = True
                        logger.info(
                            "[SPLUNKBASE] Loaded catalog from %s (%d apps)",
                            path, app_count,
                        )
                        # If loaded from alternate location, copy to primary path
                        if path != self._catalog_path:
                            try:
                                self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
                                self._catalog_path.write_text(raw, encoding="utf-8")
                                logger.info("[SPLUNKBASE] Copied catalog to primary path: %s", self._catalog_path)
                            except OSError:
                                pass
                        return self._catalog
                except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    logger.warning("[SPLUNKBASE] Failed to load catalog from %s: %s", path, exc)

        logger.info("[SPLUNKBASE] No catalog file found — starting fresh. "
                     "Upload a catalog via POST /api/admin/upgrade/catalog/upload "
                     "or place splunkbase_catalog.json in the documents directory.")
        return self._catalog

    def save_catalog(self) -> None:
        """Persist catalog to the local JSON file."""
        try:
            self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
            self._catalog_path.write_text(
                json.dumps(self._catalog, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info(
                "[SPLUNKBASE] Saved catalog to %s (%d apps)",
                self._catalog_path, len(self._catalog.get("apps", {})),
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("[SPLUNKBASE] Failed to save catalog: %s", exc)

    @property
    def catalog(self) -> Dict[str, Any]:
        """Return the in-memory catalog, loading from disk if needed."""
        if not self._loaded:
            self.load_catalog()
        return self._catalog

    @property
    def app_count(self) -> int:
        """Return number of apps in the catalog."""
        return len(self.catalog.get("apps", {}))

    # ------------------------------------------------------------------
    # Splunkbase API fetch
    # ------------------------------------------------------------------

    async def _http_get(self, url: str, params: Optional[Dict] = None, timeout: float = 30.0) -> Optional[Dict]:
        """
        Perform an HTTP GET with retry + backoff.

        Returns parsed JSON or None on failure.
        """
        try:
            import httpx
        except ImportError:
            logger.error("[SPLUNKBASE] httpx not installed — cannot fetch from Splunkbase API")
            return None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 429:
                        # Rate limited — back off
                        wait = RETRY_BACKOFF_BASE * attempt
                        logger.warning("[SPLUNKBASE] Rate limited (429), waiting %.1fs", wait)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return resp.json()
            except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE * attempt
                    logger.warning(
                        "[SPLUNKBASE] HTTP GET %s failed (attempt %d/%d): %s — retrying in %.1fs",
                        url, attempt, MAX_RETRIES, exc, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("[SPLUNKBASE] HTTP GET %s failed after %d attempts: %s", url, MAX_RETRIES, exc)
        return None

    async def fetch_app_list(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Fetch a paginated list of apps from the Splunkbase API.

        When limit is None/0 and self._max_apps is 0, fetches ALL available apps
        using the API's ``total`` field to determine when complete.

        Returns a list of app summary dicts.
        """
        effective_limit = limit or self._max_apps  # 0 means fetch all
        all_apps: List[Dict[str, Any]] = []
        current_offset = offset
        api_total: Optional[int] = None  # populated from first response

        while True:
            # Calculate page size
            if effective_limit > 0:
                remaining = effective_limit - len(all_apps)
                if remaining <= 0:
                    break
                page_size = min(DEFAULT_PAGE_SIZE, remaining)
            else:
                page_size = DEFAULT_PAGE_SIZE

            params = {
                "limit": page_size,
                "offset": current_offset,
                "order": "latest",
            }
            data = await self._http_get(SPLUNKBASE_API_BASE, params=params)
            if not data:
                break

            # Capture total from API response (first page)
            if api_total is None:
                api_total = data.get("total", 0)
                if api_total:
                    logger.info("[SPLUNKBASE] API reports %d total apps available", api_total)

            results = data.get("results", [])
            if not results:
                break

            all_apps.extend(results)
            current_offset += len(results)

            # Log progress for large fetches
            if api_total and api_total > DEFAULT_PAGE_SIZE:
                logger.info(
                    "[SPLUNKBASE] Fetched %d / %d apps (%.0f%%)",
                    len(all_apps), api_total, len(all_apps) / api_total * 100,
                )

            # Done if we got fewer than requested (end of data)
            if len(results) < page_size:
                break

            # Done if we've reached the API total
            if api_total and len(all_apps) >= api_total:
                break

        logger.info("[SPLUNKBASE] Fetched %d apps total from Splunkbase API", len(all_apps))
        return all_apps

    async def fetch_app_details(self, app_uid: str) -> Optional[Dict[str, Any]]:
        """
        Fetch detailed info for a single app, including release history.

        Returns a dict with app metadata and releases, or None on failure.
        """
        # Fetch app info
        app_url = f"{SPLUNKBASE_API_BASE}{app_uid}/"
        app_data = await self._http_get(app_url)
        if not app_data:
            return None

        # Fetch releases
        releases_url = f"{SPLUNKBASE_API_BASE}{app_uid}/release/"
        releases_data = await self._http_get(releases_url)
        releases = []
        if releases_data:
            raw_releases = releases_data if isinstance(releases_data, list) else releases_data.get("results", [])
            for rel in raw_releases:
                releases.append({
                    "version": rel.get("name", rel.get("title", "unknown")),
                    "release_date": rel.get("published_datetime", rel.get("created_datetime", "")),
                    "product_versions": [
                        pv.get("name", str(pv)) if isinstance(pv, dict) else str(pv)
                        for pv in (rel.get("product_versions", []) or [])
                    ],
                })

        # Sort releases by version descending
        releases.sort(key=lambda r: _parse_version_tuple(r["version"]), reverse=True)

        latest = releases[0] if releases else {}
        result = {
            "uid": str(app_uid),
            "title": app_data.get("title", ""),
            "app_id": app_data.get("appid", app_data.get("name", "")),
            "latest_version": latest.get("version", "unknown"),
            "latest_release_date": latest.get("release_date", ""),
            "supported_splunk_versions": latest.get("product_versions", []),
            "sourcetypes": app_data.get("sourcetypes", []) or [],
            "releases": releases,
            "last_fetched": _now_iso(),
        }
        return result

    # ------------------------------------------------------------------
    # Catalog update
    # ------------------------------------------------------------------

    def _extract_app_from_list(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract a catalog entry from an app-list response item.

        This avoids a per-app detail API call by parsing the summary data
        returned by the paginated list endpoint.
        """
        uid = str(app_data.get("uid", app_data.get("id", "")))
        # The list endpoint includes release info inline
        releases_raw = app_data.get("releases", app_data.get("release", []))
        if isinstance(releases_raw, dict):
            releases_raw = [releases_raw]

        releases = []
        for rel in (releases_raw or []):
            releases.append({
                "version": rel.get("name", rel.get("title", rel.get("version", "unknown"))),
                "release_date": rel.get("published_datetime", rel.get("created_datetime", "")),
                "product_versions": [
                    pv.get("name", str(pv)) if isinstance(pv, dict) else str(pv)
                    for pv in (rel.get("product_versions", []) or [])
                ],
            })

        # Sort releases by version descending
        releases.sort(key=lambda r: _parse_version_tuple(r["version"]), reverse=True)
        latest = releases[0] if releases else {}

        # If no release data, try the top-level version field
        latest_version = latest.get("version") or app_data.get("version", "unknown")

        return {
            "uid": uid,
            "title": app_data.get("title", ""),
            "app_id": app_data.get("appid", app_data.get("name", "")),
            "latest_version": latest_version,
            "latest_release_date": latest.get("release_date", app_data.get("updated_time", "")),
            "supported_splunk_versions": latest.get("product_versions", []),
            "sourcetypes": app_data.get("sourcetypes", []) or [],
            "releases": releases,
            "last_fetched": _now_iso(),
        }

    # update_catalog, get_installed_apps_from_splunk, compare_installed,
    # _count_versions_behind, generate_report, _catalog_only_report,
    # _format_comparison_report, get_catalog_summary
    # are provided by SplunkbaseCatalogMixin (see splunkbase_catalog_impl.py)


# ---------------------------------------------------------------------------
# Singleton access
# ---------------------------------------------------------------------------

_instance: Optional[SplunkbaseCatalog] = None


def get_splunkbase_catalog() -> SplunkbaseCatalog:
    """Return the singleton SplunkbaseCatalog instance."""
    global _instance
    if _instance is None:
        try:
            from chat_app.settings import get_settings
            settings = get_settings()
            sb = getattr(settings, "splunkbase_catalog", None)
            if sb and sb.enabled:
                _instance = SplunkbaseCatalog(
                    catalog_path=sb.catalog_path,
                    max_apps=sb.max_apps_per_fetch,
                )
                logger.info("[SPLUNKBASE] Catalog initialized (enabled)")
            else:
                _instance = SplunkbaseCatalog()
                logger.debug("[SPLUNKBASE] Catalog initialized (disabled — using defaults)")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[SPLUNKBASE] Settings unavailable, using defaults: %s", exc)
            _instance = SplunkbaseCatalog()
    return _instance


def rebuild_splunkbase_catalog() -> SplunkbaseCatalog:
    """Force a rebuild of the singleton instance."""
    global _instance
    _instance = None
    return get_splunkbase_catalog()


# ---------------------------------------------------------------------------
# Async helpers for scheduler / admin integration
# ---------------------------------------------------------------------------

async def run_catalog_update(full_rebuild: bool = False) -> Dict[str, Any]:
    """
    Run a catalog update — intended for scheduler integration.

    Args:
        full_rebuild: If True, fetch all apps from scratch instead of
                      updating only existing entries.

    Checks the feature flag before running.
    """
    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        sb = getattr(settings, "splunkbase_catalog", None)
        if not sb or not sb.enabled:
            logger.debug("[SPLUNKBASE] Catalog update skipped — feature disabled")
            return {"skipped": True, "reason": "feature_disabled"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    catalog = get_splunkbase_catalog()
    return await catalog.update_catalog(incremental=not full_rebuild)


async def run_comparison_report() -> Dict[str, Any]:
    """
    Run a comparison report — intended for admin API integration.

    Uses Splunk connection settings from config.
    """
    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        sb = getattr(settings, "splunkbase_catalog", None)
        if not sb or not sb.enabled:
            return {"error": "Splunkbase catalog feature is disabled"}
        if not sb.splunk_url or not sb.splunk_token:
            return {"error": "Splunk connection not configured (splunk_url / splunk_token)"}

        catalog = get_splunkbase_catalog()
        installed = await catalog.get_installed_apps_from_splunk(
            sb.splunk_url, sb.splunk_token,
        )
        comparison = catalog.compare_installed(installed)
        return comparison
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[SPLUNKBASE] Comparison report failed: %s", exc)
        return {"error": str(exc)}
