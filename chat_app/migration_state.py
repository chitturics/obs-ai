"""Persistent migration state for Cribl Migration Analyzer."""
import json
import logging
import os
import time
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_FILE = "/app/data/migration_state.json"


@dataclass
class SourcetypeStatus:
    sourcetype: str
    status: str = "not_started"  # not_started, in_progress, needs_review, done, not_applicable
    priority: str = "medium"     # critical, high, medium, low
    notes: str = ""
    assignee: str = ""
    updated_at: str = ""


@dataclass
class ScanRecord:
    scan_id: str
    timestamp: str
    source_type: str  # "repo", "btool_csv", "upload"
    apps_scanned: int = 0
    sourcetypes_found: int = 0
    critical_settings: int = 0
    scan_path: str = ""
    report_summary: Dict[str, Any] = field(default_factory=dict)


_VALID_STATUSES = frozenset({
    "not_started", "in_progress", "needs_review", "done", "not_applicable",
})
_VALID_PRIORITIES = frozenset({"critical", "high", "medium", "low"})


class MigrationState:
    """Thread-safe persistent migration state backed by a JSON file."""

    def __init__(self, state_file: str = STATE_FILE):
        self._file = state_file
        self._lock = threading.Lock()
        self._scan_history: List[Dict] = []
        self._statuses: Dict[str, Dict] = {}
        self._reports: Dict[str, str] = {}  # scan_id -> JSON report string
        self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self):
        """Load state from disk. Silently start fresh if missing/corrupt."""
        try:
            if os.path.isfile(self._file):
                with open(self._file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self._scan_history = data.get("scan_history", [])
                self._statuses = data.get("statuses", {})
                self._reports = data.get("reports", {})
                logger.info(
                    "[MIGRATION_STATE] Loaded %d scans, %d statuses from %s",
                    len(self._scan_history), len(self._statuses), self._file,
                )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("[MIGRATION_STATE] Failed to load %s: %s", self._file, exc)
            self._scan_history = []
            self._statuses = {}
            self._reports = {}

    def _save(self):
        """Persist current state to disk. Must be called while holding _lock."""
        try:
            os.makedirs(os.path.dirname(self._file) or ".", exist_ok=True)
            tmp = self._file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "scan_history": self._scan_history,
                        "statuses": self._statuses,
                        "reports": self._reports,
                    },
                    fh,
                    indent=2,
                    default=str,
                )
            os.replace(tmp, self._file)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("[MIGRATION_STATE] Failed to save %s: %s", self._file, exc)

    # ------------------------------------------------------------------
    # Scan history
    # ------------------------------------------------------------------

    def add_scan(self, record: ScanRecord, report_json: str = ""):
        """Add a completed scan to history and optionally store its full report."""
        with self._lock:
            entry = asdict(record)
            self._scan_history.insert(0, entry)
            # Keep last 100 scans
            self._scan_history = self._scan_history[:100]
            if report_json:
                self._reports[record.scan_id] = report_json
                # Evict oldest reports if over 50
                if len(self._reports) > 50:
                    kept_ids = {s["scan_id"] for s in self._scan_history[:50]}
                    self._reports = {
                        k: v for k, v in self._reports.items() if k in kept_ids
                    }
            self._save()

    def get_history(self, limit: int = 20) -> List[Dict]:
        """Return recent scan history (newest first)."""
        with self._lock:
            return list(self._scan_history[:limit])

    def get_report(self, scan_id: str) -> Optional[str]:
        """Return the full JSON report for a past scan, or None."""
        with self._lock:
            return self._reports.get(scan_id)

    # ------------------------------------------------------------------
    # Sourcetype statuses
    # ------------------------------------------------------------------

    def set_status(
        self,
        sourcetype: str,
        status: str,
        priority: str = "",
        notes: str = "",
        assignee: str = "",
    ) -> Dict:
        """Update migration status for a sourcetype. Returns the updated record."""
        if status not in _VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {sorted(_VALID_STATUSES)}")
        if priority and priority not in _VALID_PRIORITIES:
            raise ValueError(f"Invalid priority '{priority}'. Must be one of: {sorted(_VALID_PRIORITIES)}")
        with self._lock:
            existing = self._statuses.get(sourcetype, {})
            updated = {
                "sourcetype": sourcetype,
                "status": status,
                "priority": priority or existing.get("priority", "medium"),
                "notes": notes or existing.get("notes", ""),
                "assignee": assignee or existing.get("assignee", ""),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self._statuses[sourcetype] = updated
            self._save()
            return dict(updated)

    def get_status(self, sourcetype: str) -> Dict:
        """Return the migration status for a sourcetype."""
        with self._lock:
            return dict(self._statuses.get(sourcetype, {
                "sourcetype": sourcetype,
                "status": "not_started",
                "priority": "medium",
                "notes": "",
                "assignee": "",
                "updated_at": "",
            }))

    def get_all_statuses(self) -> Dict[str, Dict]:
        """Return all tracked sourcetype statuses."""
        with self._lock:
            return {k: dict(v) for k, v in self._statuses.items()}

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Return aggregate statistics across scans and statuses."""
        with self._lock:
            status_counts: Dict[str, int] = {}
            priority_counts: Dict[str, int] = {}
            for entry in self._statuses.values():
                s = entry.get("status", "not_started")
                p = entry.get("priority", "medium")
                status_counts[s] = status_counts.get(s, 0) + 1
                priority_counts[p] = priority_counts.get(p, 0) + 1
            return {
                "total_scans": len(self._scan_history),
                "total_sourcetypes_tracked": len(self._statuses),
                "by_status": status_counts,
                "by_priority": priority_counts,
                "latest_scan": self._scan_history[0] if self._scan_history else None,
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_singleton: Optional[MigrationState] = None
_singleton_lock = threading.Lock()


def get_migration_state() -> MigrationState:
    """Return the global MigrationState singleton (lazy init)."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = MigrationState()
    return _singleton
