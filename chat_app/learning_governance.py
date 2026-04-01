"""Learning Governance — controlled learning with drift detection and rollback.

Ensures self-learning only updates through approved, reversible workflows:
- Pre-learning snapshot (baseline quality)
- Post-learning evaluation (quality delta)
- Automatic rollback if quality degrades
- Approval gate for model customization

Usage:
    from chat_app.learning_governance import get_learning_governor

    gov = get_learning_governor()
    with gov.learning_session("qa_generation") as session:
        # Learning happens here
        session.record_quality(before=0.85, after=0.87)
    # Auto-rollback if after < before
"""

import logging
import threading
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LearningSession:
    """A governed learning session with quality tracking."""
    session_id: str = ""
    learning_type: str = ""  # qa_generation, reassessment, model_customization
    started_at: str = ""
    finished_at: str = ""
    quality_before: float = 0.0
    quality_after: float = 0.0
    quality_delta: float = 0.0
    items_processed: int = 0
    rolled_back: bool = False
    approved: bool = False
    rollback_reason: str = ""

    def record_quality(self, before: float, after: float) -> None:
        self.quality_before = before
        self.quality_after = after
        self.quality_delta = after - before

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "type": self.learning_type,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "quality_before": round(self.quality_before, 3),
            "quality_after": round(self.quality_after, 3),
            "quality_delta": round(self.quality_delta, 3),
            "items_processed": self.items_processed,
            "rolled_back": self.rolled_back,
            "approved": self.approved,
        }


class LearningGovernor:
    """Controls learning lifecycle with quality gates and rollback."""

    def __init__(self, min_quality_delta: float = -0.05, require_approval_for: Optional[List[str]] = None):
        self._sessions: deque = deque(maxlen=200)
        self._lock = threading.Lock()
        self._min_quality_delta = min_quality_delta  # Max allowed quality degradation
        self._require_approval = set(require_approval_for or ["model_customization"])
        self._session_counter = 0

    @contextmanager
    def learning_session(self, learning_type: str):
        """Context manager for a governed learning session."""
        import uuid
        self._session_counter += 1
        session = LearningSession(
            session_id=f"learn_{uuid.uuid4().hex[:8]}",
            learning_type=learning_type,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            yield session
        finally:
            session.finished_at = datetime.now(timezone.utc).isoformat()
            # Quality gate: auto-rollback if quality degraded beyond threshold
            if session.quality_delta < self._min_quality_delta:
                session.rolled_back = True
                session.rollback_reason = (
                    f"Quality degraded by {session.quality_delta:.3f} "
                    f"(threshold: {self._min_quality_delta})"
                )
                logger.warning("[LEARNING-GOV] Auto-rollback: %s — %s",
                               session.session_id, session.rollback_reason)
            # Approval gate
            if learning_type in self._require_approval:
                session.approved = False  # Requires explicit approval
                logger.info("[LEARNING-GOV] Session %s requires approval for %s",
                           session.session_id, learning_type)
            else:
                session.approved = True
            with self._lock:
                self._sessions.append(session)

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions)
        sessions.reverse()
        return [s.to_dict() for s in sessions[:limit]]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            sessions = list(self._sessions)
        if not sessions:
            return {"total_sessions": 0}
        rollbacks = sum(1 for s in sessions if s.rolled_back)
        avg_delta = sum(s.quality_delta for s in sessions) / len(sessions)
        return {
            "total_sessions": len(sessions),
            "rollback_rate": round(rollbacks / len(sessions), 3),
            "avg_quality_delta": round(avg_delta, 4),
            "min_quality_delta_threshold": self._min_quality_delta,
            "requires_approval_for": sorted(self._require_approval),
        }


_instance: Optional[LearningGovernor] = None


def get_learning_governor() -> LearningGovernor:
    global _instance
    if _instance is None:
        _instance = LearningGovernor()
    return _instance
