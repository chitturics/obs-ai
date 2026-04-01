"""Unified Activity Timeline — tracks all system activities in one place.

Provides a single chronological view of:
- Config changes (settings updated)
- Container actions (restart/stop/start)
- Tool/skill executions
- Agent dispatches
- User logins
- Document ingestion events
- Backup operations
- Approval decisions

Usage:
    from chat_app.activity_timeline import get_timeline

    timeline = get_timeline()
    timeline.record("config_change", actor="admin", action="update",
                    target="llm", details={"model": "llama3"})

    recent = timeline.get_recent(limit=50, event_type="config_change")
    summary = timeline.get_summary(hours=24)
"""

import logging
import threading
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Valid event types
EVENT_TYPES = frozenset({
    "config_change",
    "container_action",
    "tool_execution",
    "agent_dispatch",
    "user_login",
    "ingestion",
    "backup",
    "approval",
})


class ActivityTimeline:
    """Unified view of user actions, tool runs, agent decisions, and approvals."""

    def __init__(self, max_entries: int = 1000):
        self._entries: deque = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def record(
        self,
        event_type: str,
        actor: str,
        action: str,
        target: str,
        details: Optional[Dict[str, Any]] = None,
        status: str = "ok",
    ) -> Dict[str, Any]:
        """Record an activity event.

        Args:
            event_type: One of EVENT_TYPES (config_change, container_action, etc.)
            actor: Who performed the action (username, agent name, "system")
            action: What was done (update, restart, execute, dispatch, etc.)
            target: What it was done to (section name, container, skill, etc.)
            details: Optional extra data specific to the event type
            status: Outcome — "ok", "error", "pending", "denied"

        Returns:
            The recorded entry dict.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "actor": actor or "system",
            "action": action,
            "target": target,
            "details": details or {},
            "status": status,
        }
        with self._lock:
            self._entries.append(entry)
        return entry

    def get_recent(
        self,
        limit: int = 50,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent activities with optional filtering.

        Args:
            limit: Max entries to return (default 50).
            event_type: Filter by event type (e.g. "config_change").
            actor: Filter by actor name.

        Returns:
            List of activity entries, most recent first.
        """
        with self._lock:
            entries = list(self._entries)

        # Apply filters
        if event_type:
            entries = [e for e in entries if e["event_type"] == event_type]
        if actor:
            actor_lower = actor.lower()
            entries = [e for e in entries if e["actor"].lower() == actor_lower]

        # Most recent first, limited
        entries.reverse()
        return entries[:limit]

    def get_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get activity summary for the last N hours.

        Returns:
            Dict with total count, per-type breakdown, top actors, and
            status distribution.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_iso = cutoff.isoformat()

        with self._lock:
            entries = list(self._entries)

        # Filter to time window
        recent = [e for e in entries if e["timestamp"] >= cutoff_iso]

        # Per-type counts
        type_counts: Dict[str, int] = {}
        actor_counts: Dict[str, int] = {}
        status_counts: Dict[str, int] = {}

        for entry in recent:
            etype = entry["event_type"]
            type_counts[etype] = type_counts.get(etype, 0) + 1

            act = entry["actor"]
            actor_counts[act] = actor_counts.get(act, 0) + 1

            st = entry["status"]
            status_counts[st] = status_counts.get(st, 0) + 1

        # Top 10 actors sorted by count
        top_actors = sorted(actor_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "hours": hours,
            "total": len(recent),
            "by_type": type_counts,
            "by_status": status_counts,
            "top_actors": [{"actor": a, "count": c} for a, c in top_actors],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def clear(self) -> int:
        """Clear all entries. Returns the number cleared."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
        return count


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_timeline_instance: Optional[ActivityTimeline] = None
_timeline_lock = threading.Lock()


def get_timeline() -> ActivityTimeline:
    """Get the global ActivityTimeline singleton."""
    global _timeline_instance
    if _timeline_instance is None:
        with _timeline_lock:
            if _timeline_instance is None:
                _timeline_instance = ActivityTimeline()
    return _timeline_instance
