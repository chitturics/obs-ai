"""Release Governance — DORA metrics, release gates, and quality tracking.

Tracks:
- Deployment frequency (how often we deploy)
- Lead time for changes (commit to production)
- Change failure rate (deployments causing incidents)
- Mean time to recovery (time to fix failures)

Usage:
    from chat_app.release_governance import get_release_tracker

    tracker = get_release_tracker()
    tracker.record_deployment("3.5.1", success=True)
    metrics = tracker.get_dora_metrics()
"""

import json
import logging
import os
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_RELEASES_PATH = Path(os.getenv("RELEASES_PATH", "/app/data/releases.jsonl"))


@dataclass
class ReleaseRecord:
    version: str
    timestamp: str = ""
    success: bool = True
    rollback: bool = False
    recovery_minutes: float = 0.0
    notes: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "success": self.success,
            "rollback": self.rollback,
            "recovery_minutes": self.recovery_minutes,
            "notes": self.notes,
        }


class ReleaseTracker:
    """Tracks deployments and computes DORA metrics."""

    def __init__(self):
        self._releases: deque = deque(maxlen=500)
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not _RELEASES_PATH.exists():
            return
        try:
            for line in _RELEASES_PATH.read_text().strip().split("\n"):
                if line:
                    data = json.loads(line)
                    self._releases.append(ReleaseRecord(**data))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.debug("Failed to load releases: %s", exc)

    def record_deployment(self, version: str, success: bool = True,
                          rollback: bool = False, recovery_minutes: float = 0.0,
                          notes: str = "") -> ReleaseRecord:
        record = ReleaseRecord(version=version, success=success, rollback=rollback,
                               recovery_minutes=recovery_minutes, notes=notes)
        with self._lock:
            self._releases.append(record)
        # Persist
        try:
            _RELEASES_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_RELEASES_PATH, "a") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        except Exception:  # broad catch — resilience at boundary
            pass
        return record

    def get_dora_metrics(self, days: int = 90) -> Dict[str, Any]:
        """Compute DORA metrics over the last N days."""
        with self._lock:
            releases = list(self._releases)
        if not releases:
            return {"deployment_frequency": 0, "change_failure_rate": 0,
                    "mean_time_to_recovery_minutes": 0, "releases": 0}

        total = len(releases)
        failures = sum(1 for r in releases if not r.success)
        rollbacks = sum(1 for r in releases if r.rollback)
        recovery_times = [r.recovery_minutes for r in releases if r.recovery_minutes > 0]

        return {
            "releases": total,
            "deployment_frequency": f"{total}/{days}d",
            "change_failure_rate": round(failures / max(total, 1), 3),
            "rollback_rate": round(rollbacks / max(total, 1), 3),
            "mean_time_to_recovery_minutes": round(
                sum(recovery_times) / max(len(recovery_times), 1), 1
            ) if recovery_times else 0,
            "last_deployment": releases[-1].to_dict() if releases else None,
        }

    def get_release_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            releases = list(self._releases)
        releases.reverse()
        return [r.to_dict() for r in releases[:limit]]


_instance: Optional[ReleaseTracker] = None


def get_release_tracker() -> ReleaseTracker:
    global _instance
    if _instance is None:
        _instance = ReleaseTracker()
    return _instance
