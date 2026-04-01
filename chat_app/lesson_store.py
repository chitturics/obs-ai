"""Lesson Store — structured learning from failures and corrections.

Inspired by AutoResearchClaw's evolution.py pattern. Extracts actionable
lessons from failed queries, skill executions, and user corrections.
Lessons are injected into future LLM context to prevent recurring mistakes.

Features:
- Category-based lesson classification (SPL_ERROR, RETRIEVAL_MISS, etc.)
- Time-decay weighting (recent lessons prioritized)
- JSONL persistence for durability
- Query-time retrieval of relevant lessons
- Admin API integration for lesson management

Usage:
    from chat_app.lesson_store import get_lesson_store, LessonCategory

    store = get_lesson_store()
    store.record_lesson(
        category=LessonCategory.SPL_ERROR,
        description="stats command requires BY clause for grouping",
        fix="Always include 'by <field>' after stats functions",
        query_hash="abc123",
    )
    lessons = store.query_relevant("stats count", intent="spl_generation", top_k=3)
"""

import hashlib
import json
import logging
import math
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_LESSONS_PATH = Path(os.getenv("LESSONS_FILE", "/app/data/lessons.jsonl"))
_DEFAULT_HALF_LIFE_DAYS = 30  # Splunk configs change faster than research papers
_MAX_AGE_DAYS = 180


# ---------------------------------------------------------------------------
# Lesson categories
# ---------------------------------------------------------------------------

class LessonCategory(str, Enum):
    """Categories for lesson classification."""
    SPL_ERROR = "spl_error"              # SPL syntax or semantic errors
    RETRIEVAL_MISS = "retrieval_miss"    # Failed to find relevant documents
    HALLUCINATION = "hallucination"      # LLM generated false information
    TIMEOUT = "timeout"                  # Operation timed out
    CONFIG_ERROR = "config_error"        # Configuration-related failures
    USER_CORRECTION = "user_correction"  # User explicitly corrected the response
    PERMISSION_ERROR = "permission"      # Access/authorization issues
    SERVICE_ERROR = "service_error"      # External service failures
    GENERAL = "general"                  # Uncategorized lessons


class LessonSeverity(str, Enum):
    """Severity levels for lessons."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Lesson entry
# ---------------------------------------------------------------------------

@dataclass
class LessonEntry:
    """A structured lesson extracted from a failure or correction."""
    lesson_id: str = ""
    category: str = "general"
    severity: str = "medium"
    description: str = ""          # What went wrong
    fix: str = ""                  # How to avoid it next time
    query_hash: str = ""           # Hash of the query that triggered the lesson
    intent: str = ""               # Intent context
    keywords: List[str] = field(default_factory=list)  # For relevance matching
    created_at: str = ""           # ISO timestamp
    source: str = ""               # Where the lesson came from (feedback, error, correction)
    confidence: float = 0.8        # How confident we are in this lesson
    times_applied: int = 0         # How often this lesson was injected into context

    def __post_init__(self):
        if not self.lesson_id:
            self.lesson_id = hashlib.sha256(
                f"{self.category}:{self.description}:{self.fix}".encode()
            ).hexdigest()[:16]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def time_decay_weight(self, half_life_days: float = _DEFAULT_HALF_LIFE_DAYS) -> float:
        """Compute time-decay weight using exponential decay.

        Recent lessons get higher weight; lessons older than max_age get 0.
        Formula: exp(-age_days * ln(2) / half_life_days)
        """
        try:
            created = datetime.fromisoformat(self.created_at)
            age_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400.0
            if age_days > _MAX_AGE_DAYS:
                return 0.0
            return math.exp(-age_days * math.log(2) / half_life_days)
        except (ValueError, TypeError, OverflowError):
            return 0.5  # Default weight if timestamp is invalid

    def relevance_score(self, query: str, intent: str = "") -> float:
        """Score relevance of this lesson to a query.

        Scoring:
        - Keyword overlap (normalized): 0.0 - 1.0
        - Intent match: +0.3 if matching
        - Description fallback (0.5x discount): 0.0 - 0.5
        - Time decay applied as multiplier
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        # Keyword overlap
        keyword_score = 0.0
        if self.keywords:
            keyword_set = {k.lower() for k in self.keywords}
            overlap = len(query_words & keyword_set)
            keyword_score = overlap / max(len(keyword_set), 1)

        # Description fallback (0.5x discount)
        desc_words = set(self.description.lower().split())
        desc_overlap = len(query_words & desc_words)
        desc_score = 0.5 * (desc_overlap / max(len(desc_words), 1))

        # Intent match bonus
        intent_bonus = 0.3 if intent and intent == self.intent else 0.0

        raw_score = max(keyword_score, desc_score) + intent_bonus

        # Apply time decay and confidence
        return raw_score * self.time_decay_weight() * self.confidence

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_context_string(self) -> str:
        """Format lesson for LLM context injection."""
        return f"[{self.category.upper()}] {self.description} → Fix: {self.fix}"


# ---------------------------------------------------------------------------
# Lesson Store
# ---------------------------------------------------------------------------

class LessonStore:
    """Persistent store for lessons learned from failures and corrections."""

    def __init__(self, persist_path: Optional[str] = None):
        self._lessons: Dict[str, LessonEntry] = {}
        self._lock = threading.Lock()
        self._persist_path = Path(persist_path) if persist_path else _LESSONS_PATH
        self._load()

    def _load(self) -> None:
        """Load lessons from JSONL file."""
        if not self._persist_path.exists():
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    entry = LessonEntry(**data)
                    self._lessons[entry.lesson_id] = entry
            logger.info("[LESSONS] Loaded %d lessons from %s", len(self._lessons), self._persist_path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("[LESSONS] Failed to load lessons: %s", exc)

    def _save(self) -> None:
        """Persist all lessons to JSONL file."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as fh:
                for entry in self._lessons.values():
                    fh.write(json.dumps(entry.to_dict()) + "\n")
        except (OSError, ValueError, TypeError) as exc:
            logger.error("[LESSONS] Failed to save lessons: %s", exc)

    def record_lesson(
        self,
        category: str = "general",
        severity: str = "medium",
        description: str = "",
        fix: str = "",
        query_hash: str = "",
        intent: str = "",
        keywords: Optional[List[str]] = None,
        source: str = "auto",
        confidence: float = 0.8,
    ) -> LessonEntry:
        """Record a new lesson."""
        entry = LessonEntry(
            category=category,
            severity=severity,
            description=description,
            fix=fix,
            query_hash=query_hash,
            intent=intent,
            keywords=keywords or [],
            source=source,
            confidence=confidence,
        )
        with self._lock:
            # Deduplicate by lesson_id (content-based hash)
            existing = self._lessons.get(entry.lesson_id)
            if existing:
                existing.times_applied += 1
                existing.confidence = min(1.0, existing.confidence + 0.05)
                self._save()
                return existing
            self._lessons[entry.lesson_id] = entry
            self._save()
        logger.info("[LESSONS] Recorded lesson: [%s] %s", category, description[:80])
        return entry

    def query_relevant(
        self,
        query: str,
        intent: str = "",
        top_k: int = 3,
        min_score: float = 0.1,
    ) -> List[LessonEntry]:
        """Find lessons relevant to a query, scored by relevance + time decay."""
        scored = []
        for entry in self._lessons.values():
            score = entry.relevance_score(query, intent)
            if score >= min_score:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def format_for_context(
        self,
        query: str,
        intent: str = "",
        top_k: int = 3,
    ) -> str:
        """Format relevant lessons for LLM context injection."""
        lessons = self.query_relevant(query, intent, top_k)
        if not lessons:
            return ""
        lines = ["### Known Pitfalls (learned from past interactions):"]
        for lesson in lessons:
            lines.append(f"- {lesson.to_context_string()}")
        return "\n".join(lines)

    def get_all(self) -> List[LessonEntry]:
        """Return all lessons."""
        return list(self._lessons.values())

    def delete_lesson(self, lesson_id: str) -> bool:
        """Delete a lesson by ID."""
        with self._lock:
            if lesson_id in self._lessons:
                del self._lessons[lesson_id]
                self._save()
                return True
        return False

    def prune_expired(self) -> int:
        """Remove lessons that have decayed beyond max age."""
        pruned = 0
        with self._lock:
            to_remove = [
                lid for lid, entry in self._lessons.items()
                if entry.time_decay_weight() <= 0.01
            ]
            for lid in to_remove:
                del self._lessons[lid]
                pruned += 1
            if pruned:
                self._save()
        if pruned:
            logger.info("[LESSONS] Pruned %d expired lessons", pruned)
        return pruned

    def get_stats(self) -> Dict[str, Any]:
        """Return lesson store statistics."""
        by_category: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        for entry in self._lessons.values():
            by_category[entry.category] = by_category.get(entry.category, 0) + 1
            by_severity[entry.severity] = by_severity.get(entry.severity, 0) + 1
        return {
            "total_lessons": len(self._lessons),
            "by_category": by_category,
            "by_severity": by_severity,
            "oldest": min((e.created_at for e in self._lessons.values()), default=None),
            "newest": max((e.created_at for e in self._lessons.values()), default=None),
            "persist_path": str(self._persist_path),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[LessonStore] = None
_instance_lock = threading.Lock()


def get_lesson_store(persist_path: Optional[str] = None) -> LessonStore:
    """Get the global LessonStore singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = LessonStore(persist_path=persist_path)
    return _instance
