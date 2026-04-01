"""Daily Evolution Engine — Autonomous self-improvement pipeline.

Inspired by AutoResearchClaw and NemoClaw patterns. Runs daily to:
1. Analyze recent query failures and feedback
2. Extract lessons from failures (→ lesson_store)
3. Reassess stale knowledge (→ self_learning)
4. Prune expired lessons and knowledge
5. Generate improvement recommendations
6. Record evolution metrics for tracking progress over time

This is the "brain" that makes the system genuinely self-improving.

Usage:
    from chat_app.daily_evolution import run_daily_evolution, get_evolution_report

    # Run as scheduled job (called by idle_worker)
    await run_daily_evolution()

    # Get evolution metrics
    report = get_evolution_report()
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_EVOLUTION_LOG_PATH = Path("/app/data/evolution_log.jsonl")


@dataclass
class EvolutionCycleResult:
    """Result of a single daily evolution cycle."""
    cycle_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0

    # Lesson extraction
    lessons_extracted: int = 0
    lessons_pruned: int = 0

    # Knowledge reassessment
    stale_qa_pruned: int = 0
    knowledge_quality_score: float = 0.0

    # Recommendations
    recommendations: List[str] = field(default_factory=list)

    # Metrics
    total_queries_analyzed: int = 0
    failure_rate: float = 0.0
    improvement_score: float = 0.0  # 0-1, higher = more improvement

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "lessons_extracted": self.lessons_extracted,
            "lessons_pruned": self.lessons_pruned,
            "stale_qa_pruned": self.stale_qa_pruned,
            "knowledge_quality_score": round(self.knowledge_quality_score, 4),
            "recommendations": self.recommendations,
            "total_queries_analyzed": self.total_queries_analyzed,
            "failure_rate": round(self.failure_rate, 4),
            "improvement_score": round(self.improvement_score, 4),
        }


# ---------------------------------------------------------------------------
# Evolution steps
# ---------------------------------------------------------------------------

async def _step_extract_lessons(result: EvolutionCycleResult) -> None:
    """Step 1: Extract lessons from recent failures and negative feedback."""
    try:
        from chat_app.lesson_store import get_lesson_store, LessonCategory

        store = get_lesson_store()

        # Analyze recent negative feedback
        try:
            from chat_app.negative_feedback import get_recent_negative_feedback
            negatives = get_recent_negative_feedback(limit=50)
            for item in negatives:
                query = item.get("query", "")
                item.get("response", "")
                reason = item.get("reason", "")
                if query and reason:
                    store.record_lesson(
                        category=LessonCategory.USER_CORRECTION.value,
                        description=f"User disliked response to: {query[:100]}",
                        fix=reason[:200] if reason else "Review response quality",
                        query_hash=query[:50],
                        keywords=query.lower().split()[:5],
                        source="negative_feedback",
                        confidence=0.9,
                    )
                    result.lessons_extracted += 1
        except (ImportError, AttributeError, ValueError, KeyError, TypeError) as exc:
            logger.debug("[EVOLUTION] Negative feedback analysis skipped: %s", exc)

        # Analyze query traces for failures
        try:
            from chat_app.execution_tracker import get_execution_store
            exec_store = get_execution_store()
            recent = exec_store.get_recent(limit=100)
            failures = [t for t in recent if not getattr(t, 'success', True)]
            for trace in failures:
                error = getattr(trace, 'error', '') or ''
                handler = getattr(trace, 'handler_key', '') or ''
                if error:
                    store.record_lesson(
                        category=LessonCategory.SERVICE_ERROR.value,
                        description=f"Execution failed: {handler} — {error[:100]}",
                        fix=f"Review handler {handler} error handling",
                        keywords=[handler] if handler else [],
                        source="execution_tracker",
                        confidence=0.7,
                    )
                    result.lessons_extracted += 1
            result.total_queries_analyzed = len(recent)
            result.failure_rate = len(failures) / max(len(recent), 1)
        except (ImportError, AttributeError, ValueError, KeyError, TypeError) as exc:
            logger.debug("[EVOLUTION] Execution analysis skipped: %s", exc)

    except (ImportError, AttributeError, ValueError, KeyError, TypeError) as exc:
        logger.warning("[EVOLUTION] Lesson extraction failed: %s", exc)


async def _step_prune_stale(result: EvolutionCycleResult) -> None:
    """Step 2: Prune expired lessons and stale knowledge."""
    try:
        from chat_app.lesson_store import get_lesson_store
        store = get_lesson_store()
        result.lessons_pruned = store.prune_expired()
    except (ImportError, AttributeError, ValueError, KeyError, TypeError) as exc:
        logger.debug("[EVOLUTION] Lesson pruning skipped: %s", exc)

    try:
        from chat_app.self_learning import get_self_learning_manager
        slm = get_self_learning_manager()
        if hasattr(slm, 'prune_stale_qa'):
            result.stale_qa_pruned = slm.prune_stale_qa()
    except (ImportError, AttributeError, ValueError, KeyError, TypeError) as exc:
        logger.debug("[EVOLUTION] QA pruning skipped: %s", exc)


async def _step_assess_quality(result: EvolutionCycleResult) -> None:
    """Step 3: Assess overall knowledge quality."""
    try:
        from chat_app.eval_gate import run_eval_gate
        eval_result = run_eval_gate()
        if eval_result.get("passed"):
            result.knowledge_quality_score = eval_result.get("score", 0.8)
        else:
            result.knowledge_quality_score = 0.5
            result.recommendations.append(
                f"Eval gate failing: {eval_result.get('failures', 0)} cases below threshold"
            )
    except (ImportError, AttributeError, ValueError, KeyError, TypeError) as exc:
        logger.debug("[EVOLUTION] Quality assessment skipped: %s", exc)
        result.knowledge_quality_score = 0.5


async def _step_generate_recommendations(result: EvolutionCycleResult) -> None:
    """Step 4: Generate improvement recommendations based on analysis."""
    if result.failure_rate > 0.1:
        result.recommendations.append(
            f"High failure rate ({result.failure_rate:.0%}): Review top failing handlers"
        )

    if result.lessons_extracted > 10:
        result.recommendations.append(
            f"Many new lessons ({result.lessons_extracted}): Consider retraining local model"
        )

    if result.knowledge_quality_score < 0.7:
        result.recommendations.append(
            "Knowledge quality below 70%: Trigger knowledge reassessment cycle"
        )

    if result.stale_qa_pruned > 50:
        result.recommendations.append(
            f"Pruned {result.stale_qa_pruned} stale QA pairs: Run fresh ingestion"
        )

    # Calculate improvement score
    positive_signals = sum([
        1 if result.failure_rate < 0.05 else 0,
        1 if result.knowledge_quality_score > 0.8 else 0,
        1 if result.lessons_extracted > 0 else 0,
        1 if result.lessons_pruned > 0 else 0,
    ])
    result.improvement_score = positive_signals / 4.0


# ---------------------------------------------------------------------------
# Main evolution pipeline
# ---------------------------------------------------------------------------

async def run_daily_evolution() -> EvolutionCycleResult:
    """Run the daily evolution pipeline.

    Steps:
    1. Extract lessons from failures and feedback
    2. Prune stale knowledge and expired lessons
    3. Assess overall knowledge quality
    4. Generate improvement recommendations
    5. Log results for tracking

    Returns an EvolutionCycleResult with metrics and recommendations.
    """
    start = time.monotonic()
    result = EvolutionCycleResult(
        cycle_id=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    logger.info("[EVOLUTION] Starting daily evolution cycle %s", result.cycle_id)

    await _step_extract_lessons(result)
    await _step_prune_stale(result)
    await _step_assess_quality(result)
    await _step_generate_recommendations(result)

    result.completed_at = datetime.now(timezone.utc).isoformat()
    result.duration_seconds = time.monotonic() - start

    # Persist to log
    _persist_cycle(result)

    logger.info(
        "[EVOLUTION] Cycle %s complete: %d lessons, %.0f%% quality, %d recommendations",
        result.cycle_id, result.lessons_extracted,
        result.knowledge_quality_score * 100,
        len(result.recommendations),
    )

    return result


def _persist_cycle(result: EvolutionCycleResult) -> None:
    """Append cycle result to JSONL log."""
    try:
        _EVOLUTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_EVOLUTION_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result.to_dict()) + "\n")
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("[EVOLUTION] Failed to persist cycle: %s", exc)


def get_evolution_report(limit: int = 30) -> Dict[str, Any]:
    """Get recent evolution cycle results."""
    cycles: List[Dict[str, Any]] = []
    try:
        if _EVOLUTION_LOG_PATH.exists():
            with open(_EVOLUTION_LOG_PATH, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        cycles.append(json.loads(line))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("[EVOLUTION] Failed to read log: %s", exc)

    recent = cycles[-limit:]
    avg_quality = sum(c.get("knowledge_quality_score", 0) for c in recent) / max(len(recent), 1)
    avg_failure = sum(c.get("failure_rate", 0) for c in recent) / max(len(recent), 1)

    return {
        "total_cycles": len(cycles),
        "recent_cycles": recent,
        "avg_quality_score": round(avg_quality, 4),
        "avg_failure_rate": round(avg_failure, 4),
        "total_lessons_extracted": sum(c.get("lessons_extracted", 0) for c in cycles),
        "total_lessons_pruned": sum(c.get("lessons_pruned", 0) for c in cycles),
        "latest_recommendations": recent[-1].get("recommendations", []) if recent else [],
    }
