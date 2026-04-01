"""
Idle Worker — Smart background job queue with prioritized scheduling.

When the system is idle (no user queries), the worker runs a prioritized
queue of background jobs:

1. Reviews recent feedback and identifies improvement areas
2. Analyzes tool effectiveness and updates rankings
3. Detects knowledge gaps from recent queries
4. Generates better follow-up questions from past interactions
5. Runs proactive quality checks on recent responses
6. Evaluates SLOs and fires alerts proactively
7. Runs evolution assessment (staleness, targets, diagnosis)
8. Executes highest-priority improvement from evolution queue
9. Checks config drift between in-memory settings and config.yaml on disk
10. Checks collection freshness / staleness
11. Monitors pipeline query quality trends

Jobs that frequently find issues are automatically promoted to run more
often (episodic prioritization).  All job results are persisted in a
results store that the admin UI can query via GET /api/admin/idle-worker/results.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Job method implementations are in idle_worker_jobs.py (mixin).
# Import here to avoid circular dependency issues (mixin uses _job_results).
from chat_app.idle_worker_jobs import IdleWorkerJobsMixin  # noqa: E402


# ---------------------------------------------------------------------------
# Job result store
# ---------------------------------------------------------------------------

_job_results: Dict[str, Dict[str, Any]] = {}
"""job_name -> {result, timestamp, status, duration_ms, findings_count}"""


def get_job_results() -> Dict[str, Dict[str, Any]]:
    """Return a copy of the job results store."""
    return dict(_job_results)


# ---------------------------------------------------------------------------
# Job descriptor
# ---------------------------------------------------------------------------

class _JobDescriptor:
    """Metadata for a schedulable background job."""

    __slots__ = (
        "name", "fn", "base_interval", "effective_interval",
        "last_run", "run_count", "finding_count", "consecutive_empty",
    )

    def __init__(self, name: str, fn, base_interval: int):
        self.name = name
        self.fn = fn
        self.base_interval = base_interval  # seconds
        self.effective_interval = base_interval
        self.last_run: float = 0
        self.run_count: int = 0
        self.finding_count: int = 0
        self.consecutive_empty: int = 0

    @property
    def due(self) -> bool:
        return (time.time() - self.last_run) >= self.effective_interval

    def record_run(self, findings: int):
        self.last_run = time.time()
        self.run_count += 1
        self.finding_count += findings
        if findings > 0:
            self.consecutive_empty = 0
            # Episodic boost: halve interval (min 60s) when findings appear
            self.effective_interval = max(60, self.base_interval // 2)
        else:
            self.consecutive_empty += 1
            # Slow down if 3+ consecutive empty runs (up to 2x base)
            if self.consecutive_empty >= 3:
                self.effective_interval = min(
                    self.base_interval * 2, self.effective_interval + 60
                )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "base_interval": self.base_interval,
            "effective_interval": self.effective_interval,
            "last_run": self.last_run,
            "run_count": self.run_count,
            "finding_count": self.finding_count,
            "consecutive_empty": self.consecutive_empty,
            "due": self.due,
        }


# ---------------------------------------------------------------------------
# IdleWorker
# ---------------------------------------------------------------------------

class IdleWorker(IdleWorkerJobsMixin):
    """Background worker that runs a smart job queue during idle periods."""

    def __init__(
        self,
        idle_threshold_seconds: int = 60,
        min_cycle_interval: int = 300,
        max_tasks_per_cycle: int = 12,
    ):
        self._idle_threshold = idle_threshold_seconds
        self._min_cycle_interval = min_cycle_interval
        self._max_tasks_per_cycle = max_tasks_per_cycle
        self._last_query_time: float = time.time()
        self._last_cycle_time: float = 0
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._improvements_made: List[Dict[str, Any]] = []
        self._engine = None
        self._vector_store = None
        self._max_results_history = 200

        # Build the job registry — intervals overridden from settings at start()
        self._jobs: List[_JobDescriptor] = [
            _JobDescriptor("review_feedback", self._review_feedback, 300),
            _JobDescriptor("update_tool_rankings", self._update_tool_rankings, 300),
            _JobDescriptor("detect_knowledge_gaps", self._detect_knowledge_gaps, 300),
            _JobDescriptor("improve_followups", self._improve_followups, 300),
            _JobDescriptor("quality_check_recent", self._quality_check_recent, 300),
            _JobDescriptor("evaluate_observability", self._evaluate_observability, 300),
            _JobDescriptor("evolution_assessment", self._run_evolution_assessment, 300),
            _JobDescriptor("evolution_improvement", self._execute_evolution_improvement, 300),
            _JobDescriptor("config_drift", self._check_config_drift, 300),
            _JobDescriptor("collection_freshness", self._check_collection_freshness, 600),
            _JobDescriptor("pipeline_quality", self._check_pipeline_quality, 900),
            _JobDescriptor("daily_evolution", self._run_daily_evolution, 86400),  # Once per day
            _JobDescriptor("refresh_security_advisories", self._refresh_security_advisories, 86400),  # Once per day
        ]
        self._job_map: Dict[str, _JobDescriptor] = {j.name: j for j in self._jobs}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_query(self):
        """Called when a user query comes in — resets the idle timer."""
        self._last_query_time = time.time()

    def configure(self, engine=None, vector_store=None):
        """Set database engine and vector store references."""
        self._engine = engine
        self._vector_store = vector_store

    @property
    def is_idle(self) -> bool:
        return (time.time() - self._last_query_time) > self._idle_threshold

    @property
    def can_run_cycle(self) -> bool:
        return (time.time() - self._last_cycle_time) > self._min_cycle_interval

    async def start(self):
        """Start the idle worker background loop."""
        if self._running:
            return
        self._apply_settings()
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[IDLE-WORKER] Started smart job queue (%d jobs registered)", len(self._jobs))

    async def stop(self):
        """Stop the idle worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.debug("[IDLE-WORKER] Background task cancelled during shutdown — normal")
        logger.info("[IDLE-WORKER] Stopped")

    def get_status(self) -> Dict[str, Any]:
        """Get idle worker status including per-job details."""
        return {
            "running": self._running,
            "is_idle": self.is_idle,
            "idle_seconds": round(time.time() - self._last_query_time, 1),
            "cycles_completed": self._cycle_count,
            "last_cycle_time": self._last_cycle_time,
            "improvements_made": len(self._improvements_made),
            "recent_improvements": self._improvements_made[-10:],
            "jobs": [j.to_dict() for j in self._jobs],
            "results_count": len(_job_results),
        }

    def get_job_results(self) -> Dict[str, Dict[str, Any]]:
        """Return all persisted job results."""
        return dict(_job_results)

    # ------------------------------------------------------------------
    # Settings integration
    # ------------------------------------------------------------------

    def _apply_settings(self):
        """Read IdleWorkerSettings and apply intervals + thresholds."""
        try:
            from chat_app.settings import get_settings
            s = get_settings().idle_worker
            self._idle_threshold = s.idle_threshold_seconds
            self._min_cycle_interval = s.min_cycle_interval
            self._max_tasks_per_cycle = s.max_tasks_per_cycle
            self._max_results_history = s.max_results_history

            if not s.enabled:
                self._running = False
                logger.info("[IDLE-WORKER] Disabled via settings")
                return

            # Map config intervals to specific jobs
            interval_map = {
                "config_drift": s.config_drift_interval,
                "collection_freshness": s.collection_freshness_interval,
                "pipeline_quality": s.pipeline_quality_interval,
            }
            for name, interval in interval_map.items():
                if name in self._job_map:
                    self._job_map[name].base_interval = interval
                    self._job_map[name].effective_interval = interval

            # Default jobs use min_cycle_interval
            for j in self._jobs:
                if j.name not in interval_map:
                    j.base_interval = s.min_cycle_interval
                    j.effective_interval = s.min_cycle_interval

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Could not apply settings: %s", exc)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self):
        """Main loop — check if idle, run prioritized job cycle."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                if not self.is_idle or not self.can_run_cycle:
                    continue

                logger.info(
                    "[IDLE-WORKER] System idle — running job cycle #%d",
                    self._cycle_count + 1,
                )
                await self._run_improvement_cycle()
                self._cycle_count += 1
                self._last_cycle_time = time.time()

            except asyncio.CancelledError:
                break
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.warning("[IDLE-WORKER] Cycle error: %s", exc)
                await asyncio.sleep(60)

    async def _run_improvement_cycle(self):
        """Run one cycle, picking due jobs sorted by priority (most findings first)."""
        tasks_run = 0
        cycle_start = time.time()

        # Sort: due jobs first, then by finding_count descending (episodic priority)
        due_jobs = [j for j in self._jobs if j.due]
        due_jobs.sort(key=lambda j: j.finding_count, reverse=True)

        for job in due_jobs:
            if tasks_run >= self._max_tasks_per_cycle:
                break
            if not self.is_idle:
                break  # user came back — stop early

            t0 = time.time()
            findings = 0
            status = "ok"
            result_data: Any = None
            try:
                result_data = await job.fn()
                findings = result_data if isinstance(result_data, int) else 0
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                status = f"error: {exc}"
                logger.warning("[IDLE-WORKER] Job '%s' failed: %s", job.name, exc)

            duration_ms = round((time.time() - t0) * 1000)
            job.record_run(findings)
            tasks_run += 1

            # Persist result
            _job_results[job.name] = {
                "status": status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
                "findings_count": findings,
                "run_count": job.run_count,
                "effective_interval": job.effective_interval,
                "result": result_data if not isinstance(result_data, int) else None,
            }

        # Trim results history (keep most recent per job — already keyed by name)
        # The _job_results dict is keyed by job name, so it stays bounded.

        elapsed = time.time() - cycle_start
        logger.info(
            "[IDLE-WORKER] Cycle complete: %d tasks in %.1fs",
            tasks_run, elapsed,
        )


    # Job method implementations are provided by IdleWorkerJobsMixin.
    # See idle_worker_jobs.py for:
    #   _review_feedback, _update_tool_rankings, _detect_knowledge_gaps,
    #   _improve_followups, _quality_check_recent, _run_evolution_assessment,
    #   _execute_evolution_improvement, _evaluate_observability,
    #   _check_config_drift, _check_collection_freshness,
    #   _check_pipeline_quality, _run_daily_evolution


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_worker: Optional[IdleWorker] = None


def get_idle_worker() -> IdleWorker:
    """Get or create the singleton IdleWorker."""
    global _worker
    if _worker is None:
        _worker = IdleWorker()
    return _worker
