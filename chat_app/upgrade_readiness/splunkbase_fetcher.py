"""
Auto-download module for the Splunk Upgrade Readiness Testing System.

Downloads specific app versions from Splunkbase using the existing catalog,
caches them locally, and extracts them for static analysis.

Falls back gracefully when the Splunkbase API is unreachable — uses
cached downloads only in that case.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default cache location for downloaded .tgz files
DEFAULT_CACHE_DIR = "/app/data/splunkbase_downloads"

# Timeout for HTTP download requests in seconds
DOWNLOAD_TIMEOUT_SECONDS = 120

# Max retries for a download attempt
DOWNLOAD_MAX_RETRIES = 3


def _parse_version_tuple(version_str: str) -> tuple:
    """Parse '4.2.1' into a comparable tuple (4, 2, 1). Non-numeric segments → 0."""
    parts = []
    for segment in str(version_str).split("."):
        try:
            parts.append(int(segment))
        except (ValueError, TypeError):
            parts.append(0)
    return tuple(parts)


class SplunkbaseFetcher:
    """
    Downloads Splunk app versions from Splunkbase and caches them locally.

    Uses the existing SplunkbaseCatalog singleton for app metadata so we
    never duplicate catalog logic.  All network access falls back gracefully
    — callers receive None rather than an exception when the API is down.
    """

    def __init__(self, cache_dir: str = DEFAULT_CACHE_DIR) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._catalog_instance: Optional[Any] = None

    # ------------------------------------------------------------------
    # Catalog access (lazy, avoids import-time side-effects)
    # ------------------------------------------------------------------

    @property
    def catalog(self) -> Any:
        """Return the SplunkbaseCatalog singleton, loading it once."""
        if self._catalog_instance is None:
            try:
                from chat_app.splunkbase_catalog import get_splunkbase_catalog
                self._catalog_instance = get_splunkbase_catalog()
            except Exception as exc:  # pragma: no cover
                logger.warning("[FETCHER] Could not load splunkbase catalog: %s", exc)
        return self._catalog_instance

    # ------------------------------------------------------------------
    # App lookup helpers
    # ------------------------------------------------------------------

    def find_app(self, app_id: str) -> Optional[Dict[str, Any]]:
        """
        Look up an app in the catalog by its Splunk folder name (app_id).

        Performs case-insensitive matching against both the ``app_id`` and
        ``title`` fields in the catalog.

        Args:
            app_id: The Splunk app directory name, e.g. ``Splunk_TA_windows``.

        Returns:
            The catalog entry dict, or None if not found.
        """
        if self.catalog is None:
            return None

        apps: Dict[str, Any] = self.catalog.catalog.get("apps", {})
        app_id_lower = app_id.lower()

        for _uid, entry in apps.items():
            if entry.get("app_id", "").lower() == app_id_lower:
                return entry
            if entry.get("title", "").lower() == app_id_lower:
                return entry

        logger.debug("[FETCHER] App '%s' not found in catalog", app_id)
        return None

    def get_upgrade_path(self, app_id: str, from_version: str) -> List[Dict[str, Any]]:
        """
        Return all catalog releases for app_id that are newer than from_version.

        The list is sorted oldest-first so callers can step through versions
        incrementally if desired.

        Args:
            app_id:       The Splunk app directory name.
            from_version: The currently installed version string, e.g. ``"4.1.0"``.

        Returns:
            List of release dicts (``{"version": ..., "release_date": ...}``),
            sorted oldest-first, newer than from_version.  Empty list if the
            app is not in the catalog or already at latest.
        """
        entry = self.find_app(app_id)
        if not entry:
            return []

        from_tuple = _parse_version_tuple(from_version)
        newer_releases = [
            release
            for release in entry.get("releases", [])
            if _parse_version_tuple(release.get("version", "0")) > from_tuple
        ]
        newer_releases.sort(key=lambda r: _parse_version_tuple(r.get("version", "0")))
        return newer_releases

    def get_cached_versions(self, app_id: str) -> List[str]:
        """
        List all app versions that have already been downloaded and extracted.

        Args:
            app_id: The Splunk app directory name.

        Returns:
            Sorted list of version strings for which an extracted directory
            exists under ``<cache_dir>/<app_id>/``.
        """
        app_cache = self.cache_dir / app_id
        if not app_cache.is_dir():
            return []

        versions: List[str] = []
        for child in app_cache.iterdir():
            # Extracted dirs are named like "Splunk_TA_windows-4.2.1/"
            if child.is_dir():
                # Last segment after the final hyphen is the version
                parts = child.name.rsplit("-", 1)
                if len(parts) == 2:
                    versions.append(parts[1])
                else:
                    versions.append(child.name)

        versions.sort(key=_parse_version_tuple)
        return versions

    # ------------------------------------------------------------------
    # Download + extraction
    # ------------------------------------------------------------------

    async def download_version(
        self, app_id: str, version: str
    ) -> Optional[str]:
        """
        Download a specific app version from Splunkbase.

        Uses a local cache — if the extracted directory already exists the
        download is skipped entirely.  Falls back gracefully if the Splunkbase
        API is not reachable.

        Args:
            app_id:  The Splunk app directory name.
            version: The exact version string to download, e.g. ``"4.2.1"``.

        Returns:
            Path to the extracted app root directory (the directory that
            contains ``default/``, ``local/`` etc.), or None on failure.
        """
        # Check cache first
        cached = self._find_cached_extraction(app_id, version)
        if cached:
            logger.info("[FETCHER] Cache hit: %s %s → %s", app_id, version, cached)
            return cached

        tgz_path = self.cache_dir / app_id / f"{app_id}-{version}.tgz"
        tgz_path.parent.mkdir(parents=True, exist_ok=True)

        # Attempt download
        downloaded = await self._download_tgz(app_id, version, tgz_path)
        if not downloaded:
            logger.warning(
                "[FETCHER] Could not download %s version %s — API unreachable or not in catalog",
                app_id, version,
            )
            return None

        # Extract
        extract_root = str(tgz_path.parent)
        try:
            app_root = self.extract_tgz(str(tgz_path), extract_root)
            logger.info("[FETCHER] Extracted %s %s → %s", app_id, version, app_root)
            return app_root
        except Exception as exc:
            logger.error("[FETCHER] Extraction failed for %s %s: %s", app_id, version, exc)
            return None

    async def _download_tgz(
        self,
        app_id: str,
        version: str,
        dest_path: Path,
    ) -> bool:
        """
        Perform the actual HTTP download for a .tgz file.

        Tries to derive a download URL from the catalog entry.  Returns True
        if the file was written successfully, False otherwise.
        """
        entry = self.find_app(app_id)
        if not entry:
            logger.warning("[FETCHER] App '%s' not found in catalog", app_id)
            return False

        # Find the matching release
        download_url: Optional[str] = None
        for release in entry.get("releases", []):
            if release.get("version") == version:
                download_url = release.get("download_url") or release.get("url")
                break

        if not download_url:
            # Construct a canonical Splunkbase download URL as a fallback
            uid = entry.get("uid", "")
            if uid:
                download_url = (
                    f"https://splunkbase.splunk.com/app/{uid}/release/{version}/download/"
                )
            else:
                logger.warning(
                    "[FETCHER] No download URL for %s %s — skipping", app_id, version
                )
                return False

        # Run in thread to avoid blocking the event loop
        return await asyncio.to_thread(
            self._sync_download, download_url, dest_path
        )

    def _sync_download(self, url: str, dest_path: Path) -> bool:
        """
        Download url to dest_path using curl/wget or httpx.

        Returns True on success, False on any network failure.
        """
        # Prefer curl for robustness on the target containers
        for tool in ["curl", "wget"]:
            which_result = subprocess.run(
                ["which", tool], capture_output=True, text=True
            )
            if which_result.returncode != 0:
                continue

            if tool == "curl":
                cmd = [
                    "curl", "-fsSL", "--max-time", str(DOWNLOAD_TIMEOUT_SECONDS),
                    "-o", str(dest_path), url,
                ]
            else:  # wget
                cmd = [
                    "wget", "-q", "--timeout", str(DOWNLOAD_TIMEOUT_SECONDS),
                    "-O", str(dest_path), url,
                ]

            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT_SECONDS + 10
                )
                if result.returncode == 0 and dest_path.exists() and dest_path.stat().st_size > 0:
                    return True
                logger.warning("[FETCHER] %s failed (rc=%d): %s", tool, result.returncode, result.stderr[:200])
            except (subprocess.TimeoutExpired, OSError) as exc:
                logger.warning("[FETCHER] %s error: %s", tool, exc)
            break  # only try one tool

        # Fallback to httpx
        try:
            import httpx
            with httpx.Client(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
                with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        logger.warning(
                            "[FETCHER] HTTP %d for %s", response.status_code, url
                        )
                        return False
                    with open(dest_path, "wb") as fh:
                        for chunk in response.iter_bytes(chunk_size=65536):
                            fh.write(chunk)
            if dest_path.stat().st_size > 0:
                return True
        except Exception as exc:
            logger.warning("[FETCHER] httpx download failed for %s: %s", url, exc)

        return False

    def extract_tgz(self, tgz_path: str, dest_dir: str) -> str:
        """
        Extract a Splunk app .tgz archive to dest_dir.

        Splunk app tarballs always contain a single top-level directory
        (the app folder itself).  This method returns the path to that
        inner directory.

        Args:
            tgz_path: Absolute path to the .tgz file.
            dest_dir: Directory into which the archive is extracted.

        Returns:
            Path to the extracted app root (the inner directory), which will
            contain ``default/``, ``metadata/``, etc.

        Raises:
            ValueError: If the archive is empty or its structure is unexpected.
            tarfile.TarError: If extraction fails.
        """
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)

        with tarfile.open(tgz_path, "r:gz") as tf:
            # Detect the top-level directory name from the archive members
            top_dirs: set = set()
            for member in tf.getmembers():
                parts = Path(member.name).parts
                if parts:
                    top_dirs.add(parts[0])

            if not top_dirs:
                raise ValueError(f"Archive {tgz_path} is empty")

            # Safe extraction — filter out absolute paths and traversal attempts
            safe_members = [
                m for m in tf.getmembers()
                if not os.path.isabs(m.name) and ".." not in Path(m.name).parts
            ]
            tf.extractall(path=str(dest), members=safe_members)  # noqa: S202

        top_dir = sorted(top_dirs)[0]
        extracted_path = dest / top_dir
        if not extracted_path.is_dir():
            raise ValueError(
                f"Expected extracted dir {extracted_path} not found after extraction"
            )
        return str(extracted_path)

    # ------------------------------------------------------------------
    # Internal cache helpers
    # ------------------------------------------------------------------

    def _find_cached_extraction(self, app_id: str, version: str) -> Optional[str]:
        """
        Return the path to an already-extracted app directory if it exists.

        The naming convention is ``<cache_dir>/<app_id>/<app_id>-<version>/``.
        """
        candidate = self.cache_dir / app_id / f"{app_id}-{version}"
        if candidate.is_dir():
            return str(candidate)

        # Also check if any extracted dir inside the version slot contains
        # a default/ subdirectory (handles non-canonical naming)
        parent = self.cache_dir / app_id
        if parent.is_dir():
            for child in parent.iterdir():
                if child.is_dir() and version in child.name:
                    if (child / "default").is_dir():
                        return str(child)

        return None
