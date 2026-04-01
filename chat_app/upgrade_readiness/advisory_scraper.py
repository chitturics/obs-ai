"""
Advisory Scraper — Fetches real CVE data from advisory.splunk.com.

Scrapes the Splunk security advisory page, parses structured advisory data,
caches results locally, and exposes helpers to query by affected version.

Cache TTL: 24 hours (daily refresh via idle_worker).
Falls back to the bundled KNOWN_ADVISORIES list when the network is unreachable.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADVISORY_BASE_URL = "https://advisory.splunk.com"
ADVISORY_LIST_URL = "https://advisory.splunk.com/advisories"

# Local cache — survives container restarts
ADVISORY_CACHE_PATH = Path("/app/data/security_advisories/advisories_cache.json")

# Do not re-fetch if cache was written within this many seconds (24 hours)
CACHE_MAX_AGE_SECONDS = 86400

# HTTP timeout for advisory page requests
HTTP_TIMEOUT_SECONDS = 30

# Maximum pages to scrape per refresh cycle
DEFAULT_MAX_PAGES = 5

# Severity ordering (highest first) for sorting
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SecurityAdvisory:
    """A Splunk security advisory fetched from advisory.splunk.com."""

    svd_id: str                             # e.g. SVD-2025-0501
    cve_ids: List[str] = field(default_factory=list)  # e.g. ["CVE-2025-38432"]
    title: str = ""
    severity: str = ""                      # critical | high | medium | low
    cvss_score: float = 0.0
    affected_versions: List[str] = field(default_factory=list)
    fixed_in: List[str] = field(default_factory=list)
    description: str = ""
    published_date: str = ""
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)

    @property
    def severity_rank(self) -> int:
        """Integer rank for sorting (lower = more severe)."""
        return _SEVERITY_ORDER.get(self.severity.lower(), 4)


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


def _extract_svd_id(text: str) -> str:
    """Return the first SVD-YYYY-NNNN pattern found in text, or empty string."""
    match = re.search(r"SVD-\d{4}-\d{4}", text, re.IGNORECASE)
    return match.group(0).upper() if match else ""


def _extract_cve_ids(text: str) -> List[str]:
    """Return all CVE-YYYY-NNNNN patterns found in text."""
    return [m.upper() for m in re.findall(r"CVE-\d{4}-\d+", text, re.IGNORECASE)]


def _normalise_severity(raw: str) -> str:
    """Normalise a severity string to lowercase canonical form."""
    canonical = raw.strip().lower()
    if canonical in {"critical", "high", "medium", "low"}:
        return canonical
    # Try common variations
    if canonical in {"crit", "very high"}:
        return "critical"
    if canonical in {"med", "moderate"}:
        return "medium"
    if canonical in {"informational", "info", "none"}:
        return "low"
    return "unknown"


def _parse_versions_from_text(text: str) -> List[str]:
    """Extract Splunk version strings from a block of text."""
    # Match patterns like 9.3.2, 10.0, 9.3.x, 10.1.0-10.1.5
    found: List[str] = []
    for match in re.finditer(r"\b(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)\b", text):
        version = match.group(1)
        # Filter out noise (years, port numbers, etc.)
        parts = version.split(".")
        major = int(parts[0])
        if 7 <= major <= 12:  # Splunk major versions are in this range
            found.append(version)
    return sorted(set(found))


# ---------------------------------------------------------------------------
# AdvisoryScraper
# ---------------------------------------------------------------------------


class AdvisoryScraper:
    """
    Fetches and parses Splunk security advisories from advisory.splunk.com.

    Network access is best-effort — all public methods degrade gracefully
    to cached data or an empty list when the network is unreachable.
    """

    def __init__(
        self,
        cache_path: Path = ADVISORY_CACHE_PATH,
        max_age_seconds: int = CACHE_MAX_AGE_SECONDS,
    ) -> None:
        self._cache_path = cache_path
        self._max_age_seconds = max_age_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_advisories(self, max_pages: int = DEFAULT_MAX_PAGES) -> List[SecurityAdvisory]:
        """
        Scrape advisory.splunk.com for CVE data.

        Returns a list sorted by severity (critical first).  Falls back to
        cached data if the network is unavailable.

        Args:
            max_pages: Maximum number of paginated advisory list pages to scrape.

        Returns:
            List of SecurityAdvisory objects.
        """
        cached = self.load_cache()
        if cached and self._is_cache_fresh():
            logger.info("[ADVISORY-SCRAPER] Cache is fresh — skipping network fetch (%d advisories)", len(cached))
            return cached

        logger.info("[ADVISORY-SCRAPER] Fetching advisories from %s (max_pages=%d)", ADVISORY_LIST_URL, max_pages)
        advisories: List[SecurityAdvisory] = []

        try:
            import asyncio
            page_htmls = await asyncio.gather(
                *[self._fetch_page(page_num=page) for page in range(1, max_pages + 1)],
                return_exceptions=True,
            )

            seen_svd_ids: set = set()
            for result in page_htmls:
                if isinstance(result, Exception):
                    logger.debug("[ADVISORY-SCRAPER] Page fetch error: %s", result)
                    continue
                if not result:
                    continue
                for advisory in self.parse_advisory_page(result):
                    if advisory.svd_id and advisory.svd_id not in seen_svd_ids:
                        seen_svd_ids.add(advisory.svd_id)
                        advisories.append(advisory)

        except Exception as exc:
            logger.warning("[ADVISORY-SCRAPER] Fetch failed: %s — using cache", exc)
            return cached or self._load_bundled_advisories()

        if advisories:
            advisories.sort(key=lambda a: (a.severity_rank, a.published_date))
            self.save_cache(advisories)
            logger.info("[ADVISORY-SCRAPER] Fetched and cached %d advisories", len(advisories))
        else:
            logger.warning("[ADVISORY-SCRAPER] No advisories parsed from live pages — falling back to cache")
            advisories = cached or self._load_bundled_advisories()

        return advisories

    def parse_advisory_page(self, html: str) -> List[SecurityAdvisory]:
        """
        Parse HTML from the advisory listing or detail page.

        Extracts SVD ID, CVE IDs, title, severity, affected versions, and
        fixed-in versions.  Handles both JSON-LD structured data (preferred)
        and raw HTML pattern matching (fallback).

        Args:
            html: Raw HTML string from advisory.splunk.com.

        Returns:
            List of parsed SecurityAdvisory objects (may be empty).
        """
        advisories: List[SecurityAdvisory] = []

        # Strategy 1: JSON-LD structured data embedded in the page
        advisories.extend(self._parse_json_ld(html))
        if advisories:
            return advisories

        # Strategy 2: JSON blobs embedded as <script type="application/json">
        advisories.extend(self._parse_embedded_json(html))
        if advisories:
            return advisories

        # Strategy 3: HTML pattern matching (table rows, article cards, etc.)
        advisories.extend(self._parse_html_patterns(html))
        return advisories

    def save_cache(self, advisories: List[SecurityAdvisory]) -> None:
        """
        Persist advisories to the local cache file.

        Args:
            advisories: List of SecurityAdvisory objects to save.
        """
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "count": len(advisories),
                "advisories": [a.to_dict() for a in advisories],
            }
            self._cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            logger.debug("[ADVISORY-SCRAPER] Cache saved: %s (%d entries)", self._cache_path, len(advisories))
        except OSError as exc:
            logger.warning("[ADVISORY-SCRAPER] Could not write cache: %s", exc)

    def load_cache(self) -> List[SecurityAdvisory]:
        """
        Load advisories from the local cache file.

        Returns:
            Cached list, or empty list if the cache does not exist or is corrupt.
        """
        if not self._cache_path.is_file():
            return []
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
            advisories = []
            for entry in raw.get("advisories", []):
                advisories.append(SecurityAdvisory(
                    svd_id=entry.get("svd_id", ""),
                    cve_ids=entry.get("cve_ids", []),
                    title=entry.get("title", ""),
                    severity=entry.get("severity", ""),
                    cvss_score=float(entry.get("cvss_score", 0.0)),
                    affected_versions=entry.get("affected_versions", []),
                    fixed_in=entry.get("fixed_in", []),
                    description=entry.get("description", ""),
                    published_date=entry.get("published_date", ""),
                    url=entry.get("url", ""),
                ))
            logger.debug("[ADVISORY-SCRAPER] Loaded %d advisories from cache", len(advisories))
            return advisories
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("[ADVISORY-SCRAPER] Cache corrupt — ignoring: %s", exc)
            return []

    def get_advisories_for_version(self, version: str) -> List[SecurityAdvisory]:
        """
        Return all cached advisories that affect a specific Splunk version.

        Checks both exact version matches and range notation (e.g. "9.0-9.3.2").

        Args:
            version: Version string such as "9.3.2" or "10.0.0".

        Returns:
            Advisories affecting that version, sorted critical-first.
        """
        all_advisories = self.load_cache() or self._load_bundled_advisories()
        matching: List[SecurityAdvisory] = []

        for advisory in all_advisories:
            if self._version_is_affected(version, advisory.affected_versions):
                matching.append(advisory)

        matching.sort(key=lambda a: a.severity_rank)
        return matching

    def get_cache_metadata(self) -> Dict[str, Any]:
        """Return metadata about the cache file for the data-sources API."""
        if not self._cache_path.is_file():
            return {"last_updated": None, "record_count": 0, "cache_path": str(self._cache_path)}
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return {
                "last_updated": raw.get("cached_at"),
                "record_count": raw.get("count", len(raw.get("advisories", []))),
                "cache_path": str(self._cache_path),
            }
        except (json.JSONDecodeError, OSError):
            return {"last_updated": None, "record_count": 0, "cache_path": str(self._cache_path)}

    # ------------------------------------------------------------------
    # Internal: network
    # ------------------------------------------------------------------

    async def _fetch_page(self, page_num: int = 1) -> Optional[str]:
        """
        Fetch a single advisory listing page via HTTPX.

        Args:
            page_num: Page number for paginated results (1-based).

        Returns:
            Raw HTML string, or None on any network failure.
        """
        try:
            import httpx
            url = ADVISORY_LIST_URL
            if page_num > 1:
                url = f"{ADVISORY_LIST_URL}?page={page_num}"

            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": "ObsAI-AdvisoryScraper/1.0"},
            ) as client:
                response = await client.get(url)

            if response.status_code == 404 and page_num > 1:
                return None  # No more pages
            if response.status_code != 200:
                logger.debug("[ADVISORY-SCRAPER] HTTP %d for page %d", response.status_code, page_num)
                return None
            return response.text

        except ImportError:
            logger.warning("[ADVISORY-SCRAPER] httpx not available — cannot fetch live advisories")
            return None
        except Exception as exc:
            logger.debug("[ADVISORY-SCRAPER] Page %d fetch error: %s", page_num, exc)
            return None

    # ------------------------------------------------------------------
    # Internal: parsers
    # ------------------------------------------------------------------

    def _parse_json_ld(self, html: str) -> List[SecurityAdvisory]:
        """Extract advisories from JSON-LD <script> blocks."""
        advisories: List[SecurityAdvisory] = []
        for match in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            try:
                data = json.loads(match.group(1))
                advisory = self._json_ld_to_advisory(data)
                if advisory:
                    advisories.append(advisory)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return advisories

    def _json_ld_to_advisory(self, data: Any) -> Optional[SecurityAdvisory]:
        """Convert a JSON-LD object to a SecurityAdvisory, or None if not recognisable."""
        if not isinstance(data, dict):
            return None

        # Splunk advisory pages sometimes use schema.org/Article or custom types
        raw_text = json.dumps(data)
        svd_id = _extract_svd_id(raw_text)
        if not svd_id:
            return None

        return SecurityAdvisory(
            svd_id=svd_id,
            cve_ids=_extract_cve_ids(raw_text),
            title=data.get("headline", data.get("name", "")),
            severity=_normalise_severity(data.get("severity", "")),
            description=str(data.get("description", ""))[:500],
            published_date=data.get("datePublished", ""),
            url=data.get("url", f"{ADVISORY_BASE_URL}/advisories/{svd_id}"),
        )

    def _parse_embedded_json(self, html: str) -> List[SecurityAdvisory]:
        """Extract advisories from <script type="application/json"> blocks."""
        advisories: List[SecurityAdvisory] = []
        for match in re.finditer(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            try:
                data = json.loads(match.group(1))
                advisories.extend(self._walk_json_for_advisories(data))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return advisories

    def _walk_json_for_advisories(self, data: Any) -> List[SecurityAdvisory]:
        """Recursively search a JSON structure for advisory-shaped objects."""
        advisories: List[SecurityAdvisory] = []
        if isinstance(data, list):
            for item in data:
                advisories.extend(self._walk_json_for_advisories(item))
        elif isinstance(data, dict):
            raw_text = json.dumps(data)
            svd_id = _extract_svd_id(raw_text)
            if svd_id:
                cves = _extract_cve_ids(raw_text)
                severity = _normalise_severity(
                    data.get("severity", data.get("cvss_severity", ""))
                )
                advisories.append(SecurityAdvisory(
                    svd_id=svd_id,
                    cve_ids=cves,
                    title=data.get("title", data.get("name", "")),
                    severity=severity,
                    cvss_score=float(data.get("cvss_score", data.get("cvssScore", 0.0))),
                    description=str(data.get("description", ""))[:500],
                    published_date=data.get("published", data.get("date", "")),
                    url=data.get("url", f"{ADVISORY_BASE_URL}/advisories/{svd_id}"),
                ))
            else:
                for value in data.values():
                    if isinstance(value, (dict, list)):
                        advisories.extend(self._walk_json_for_advisories(value))
        return advisories

    def _parse_html_patterns(self, html: str) -> List[SecurityAdvisory]:
        """
        Pattern-match advisory data from raw HTML.

        Looks for SVD IDs and extracts surrounding context for title/severity/CVE.
        This is a heuristic fallback — not guaranteed to work if the advisory
        page markup changes significantly.
        """
        advisories: List[SecurityAdvisory] = []
        # Find all SVD IDs in the page as anchor points
        for svd_match in re.finditer(r"(SVD-\d{4}-\d{4})", html, re.IGNORECASE):
            svd_id = svd_match.group(1).upper()
            # Extract a 2000-char window around each SVD mention
            start = max(0, svd_match.start() - 200)
            end = min(len(html), svd_match.end() + 1800)
            context = html[start:end]

            # Strip HTML tags for clean text analysis
            clean_context = re.sub(r"<[^>]+>", " ", context)
            clean_context = re.sub(r"\s+", " ", clean_context).strip()

            cve_ids = _extract_cve_ids(clean_context)
            severity = self._detect_severity_in_text(clean_context)
            title = self._extract_title_near_svd(clean_context, svd_id)
            affected = _parse_versions_from_text(clean_context)
            pub_date = self._extract_date_from_text(clean_context)

            advisory = SecurityAdvisory(
                svd_id=svd_id,
                cve_ids=cve_ids,
                title=title,
                severity=severity,
                affected_versions=affected,
                published_date=pub_date,
                url=f"{ADVISORY_BASE_URL}/advisories/{svd_id}",
            )
            advisories.append(advisory)

        # Deduplicate by SVD ID (keep first occurrence)
        seen: set = set()
        unique: List[SecurityAdvisory] = []
        for a in advisories:
            if a.svd_id not in seen:
                seen.add(a.svd_id)
                unique.append(a)
        return unique

    def _detect_severity_in_text(self, text: str) -> str:
        """Detect severity label from surrounding text context."""
        lower = text.lower()
        for label in ("critical", "high", "medium", "low"):
            if label in lower:
                return label
        return "unknown"

    def _extract_title_near_svd(self, text: str, svd_id: str) -> str:
        """Try to extract the advisory title from the text window."""
        # Look for text between the SVD ID and the next separator
        pattern = rf"{re.escape(svd_id)}\s*[:\-–]?\s*([^\n<>{{}}]+)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            # Clean up — trim at 120 chars, remove trailing punctuation noise
            candidate = re.sub(r"[|\[\]]+.*", "", candidate).strip()
            if len(candidate) > 5:
                return candidate[:120]
        return svd_id

    def _extract_date_from_text(self, text: str) -> str:
        """Extract the first ISO-ish date from a text window."""
        match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if match:
            return match.group(1)
        # Month-name formats: "January 15, 2025"
        match = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(\d{1,2}),?\s+(\d{4})\b",
            text,
            re.IGNORECASE,
        )
        if match:
            month_names = {
                "january": "01", "february": "02", "march": "03", "april": "04",
                "may": "05", "june": "06", "july": "07", "august": "08",
                "september": "09", "october": "10", "november": "11", "december": "12",
            }
            month = month_names.get(match.group(1).lower(), "01")
            day = match.group(2).zfill(2)
            year = match.group(3)
            return f"{year}-{month}-{day}"
        return ""

    # ------------------------------------------------------------------
    # Internal: cache helpers
    # ------------------------------------------------------------------

    def _is_cache_fresh(self) -> bool:
        """Return True if the cache file exists and is younger than max_age_seconds."""
        if not self._cache_path.is_file():
            return False
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
            cached_at_str = raw.get("cached_at", "")
            if not cached_at_str:
                return False
            cached_at = datetime.fromisoformat(cached_at_str)
            age_seconds = (datetime.now(timezone.utc) - cached_at).total_seconds()
            return age_seconds < self._max_age_seconds
        except (json.JSONDecodeError, ValueError, OSError):
            return False

    def _load_bundled_advisories(self) -> List[SecurityAdvisory]:
        """
        Load bundled advisories from data/security_advisories/advisories.yaml.

        This is the last-resort fallback when both network and cache are unavailable.
        """
        yaml_path = Path("/app/data/security_advisories/advisories.yaml")
        if not yaml_path.is_file():
            # Try relative to this file (development environment)
            yaml_path = Path(__file__).parent.parent.parent / "data" / "security_advisories" / "advisories.yaml"
        if not yaml_path.is_file():
            logger.debug("[ADVISORY-SCRAPER] No bundled advisories YAML found")
            return []
        try:
            import yaml
            with open(yaml_path) as fh:
                data = yaml.safe_load(fh)
            advisories: List[SecurityAdvisory] = []
            for entry in data.get("advisories", []):
                affected: List[str] = []
                for product_block in entry.get("affected_products", []):
                    affected.extend(product_block.get("versions", []))
                advisories.append(SecurityAdvisory(
                    svd_id=entry.get("svd_id", ""),
                    cve_ids=entry.get("cve", []),
                    title=entry.get("title", ""),
                    severity=_normalise_severity(entry.get("severity", "")),
                    cvss_score=float(entry.get("cvss_score", 0.0)),
                    affected_versions=affected,
                    fixed_in=entry.get("fixed_in", []),
                    description=entry.get("description", ""),
                    published_date=entry.get("published", ""),
                    url=entry.get("url", ""),
                ))
            logger.debug("[ADVISORY-SCRAPER] Loaded %d bundled advisories from YAML", len(advisories))
            return advisories
        except Exception as exc:
            logger.warning("[ADVISORY-SCRAPER] Could not load bundled advisories: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal: version matching
    # ------------------------------------------------------------------

    def _version_is_affected(self, version: str, affected_list: List[str]) -> bool:
        """
        Return True if version falls within any entry in affected_list.

        Supports both exact matches ("9.3.2") and range notation ("9.0-9.3.2").
        """
        version_tuple = self._parse_version_tuple(version)
        if not version_tuple:
            return False

        for entry in affected_list:
            if "-" in entry:
                # Range: "9.0.0-9.3.2"
                parts = entry.split("-", 1)
                low = self._parse_version_tuple(parts[0])
                high = self._parse_version_tuple(parts[1])
                if low and high and low <= version_tuple <= high:
                    return True
            else:
                # Exact or prefix match ("9.3.x" → "9.3")
                clean = entry.rstrip(".x").rstrip(".")
                if version.startswith(clean) or version == entry:
                    return True

        return False

    @staticmethod
    def _parse_version_tuple(version_str: str) -> Optional[tuple]:
        """Parse "9.3.2" into (9, 3, 2). Returns None on parse failure."""
        parts = []
        for segment in str(version_str).strip().split("."):
            try:
                parts.append(int(segment))
            except ValueError:
                return None
        return tuple(parts) if parts else None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_scraper_instance: Optional[AdvisoryScraper] = None


def get_advisory_scraper() -> AdvisoryScraper:
    """Return the module-level AdvisoryScraper singleton."""
    global _scraper_instance
    if _scraper_instance is None:
        _scraper_instance = AdvisoryScraper()
    return _scraper_instance
