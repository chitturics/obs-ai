"""
Pipeline lineage tracking — per-request provenance and stage metrics.

Uses contextvars for thread-safe per-request tracing. Each pipeline stage
records its metrics (duration, success, metadata) into a PipelineTrace.

Usage in message_handler.py:
    from chat_app.pipeline_lineage import init_trace, record_stage, get_trace

    trace = init_trace(user_input=msg, intent=intent, profile=profile)
    record_stage(PipelineStage.ROUTING, duration_ms=5.0, metadata={"intent": intent})
    ...
    final_trace = get_trace()
"""

from __future__ import annotations

import collections
import logging
import threading
from contextvars import ContextVar
from typing import Any, Deque, Dict, List, Optional

from chat_app.schemas import PipelineStage, PipelineStageResult, PipelineTrace

logger = logging.getLogger(__name__)

# Per-request trace (contextvars is async-safe)
_current_trace: ContextVar[Optional[PipelineTrace]] = ContextVar(
    "pipeline_trace", default=None
)

# Recent traces (global, thread-safe)
_recent_traces: Deque[PipelineTrace] = collections.deque(maxlen=200)
_traces_lock = threading.Lock()

# Stage-level aggregated stats
_stage_stats: Dict[str, Dict[str, Any]] = {}
_stats_lock = threading.Lock()


def init_trace(
    user_input: str = "",
    intent: str = "",
    profile: str = "",
    request_id: str = "",
) -> PipelineTrace:
    """Initialize a new pipeline trace for the current request."""
    kwargs: Dict[str, Any] = {
        "user_input": user_input,
        "intent": intent,
        "profile": profile,
    }
    if request_id:
        kwargs["request_id"] = request_id
    trace = PipelineTrace(**kwargs)
    _current_trace.set(trace)
    return trace


def get_trace() -> Optional[PipelineTrace]:
    """Get the current request's pipeline trace."""
    return _current_trace.get()


def record_stage(
    stage: PipelineStage,
    duration_ms: float = 0.0,
    success: bool = True,
    input_summary: str = "",
    output_summary: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Optional[PipelineStageResult]:
    """Record a pipeline stage result in the current trace."""
    trace = _current_trace.get()
    if trace is None:
        return None

    result = PipelineStageResult(
        stage=stage,
        duration_ms=duration_ms,
        success=success,
        input_summary=input_summary,
        output_summary=output_summary,
        metadata=metadata or {},
        error=error,
    )
    trace.add_stage(result)

    # Update aggregated stats
    _update_stage_stats(stage.value, duration_ms, success)

    return result


def finalize_trace(
    strategy_used: str = "",
    agent_name: str = "",
    quality_score: Optional[float] = None,
    chunk_ids: Optional[List[str]] = None,
    collections_searched: Optional[List[str]] = None,
) -> Optional[PipelineTrace]:
    """Finalize the current trace and store it in recent traces."""
    trace = _current_trace.get()
    if trace is None:
        return None

    if strategy_used:
        trace.strategy_used = strategy_used
    if agent_name:
        trace.agent_name = agent_name
    if quality_score is not None:
        trace.quality_score = max(0.0, min(1.0, quality_score))
    if chunk_ids:
        trace.chunk_ids = chunk_ids
    if collections_searched:
        trace.collections_searched = collections_searched

    # Store in recent traces
    with _traces_lock:
        _recent_traces.append(trace)

    # Persist to execution journal
    try:
        from chat_app.execution_journal import get_journal
        journal = get_journal()
        data = trace.model_dump()
        data["event_type"] = "pipeline_trace"
        journal.log(data)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    logger.debug(
        "[LINEAGE] Trace finalized: id=%s intent=%s strategy=%s quality=%s stages=%d total=%.0fms",
        trace.request_id, trace.intent, trace.strategy_used,
        trace.quality_score, len(trace.stages), trace.total_duration_ms,
    )

    return trace


def _update_stage_stats(stage_name: str, duration_ms: float, success: bool) -> None:
    """Update aggregated per-stage statistics."""
    with _stats_lock:
        if stage_name not in _stage_stats:
            _stage_stats[stage_name] = {
                "count": 0,
                "success_count": 0,
                "total_ms": 0.0,
                "min_ms": float("inf"),
                "max_ms": 0.0,
            }
        s = _stage_stats[stage_name]
        s["count"] += 1
        if success:
            s["success_count"] += 1
        s["total_ms"] += duration_ms
        s["min_ms"] = min(s["min_ms"], duration_ms)
        s["max_ms"] = max(s["max_ms"], duration_ms)


# ── Query API ──────────────────────────────────────────────────────────

def get_recent_traces(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent pipeline traces as summaries."""
    with _traces_lock:
        traces = list(_recent_traces)
    traces.reverse()  # Most recent first
    return [t.to_summary() for t in traces[:limit]]


def get_trace_by_id(request_id: str) -> Optional[Dict[str, Any]]:
    """Get a full trace by request ID."""
    with _traces_lock:
        for t in _recent_traces:
            if t.request_id == request_id:
                return t.model_dump()
    return None


def get_stage_stats() -> Dict[str, Any]:
    """Get aggregated stage-level statistics."""
    with _stats_lock:
        result = {}
        for stage, s in _stage_stats.items():
            count = s["count"]
            result[stage] = {
                "count": count,
                "success_rate": round(s["success_count"] / count, 4) if count else 0,
                "avg_ms": round(s["total_ms"] / count, 1) if count else 0,
                "min_ms": round(s["min_ms"], 1) if s["min_ms"] != float("inf") else 0,
                "max_ms": round(s["max_ms"], 1),
            }
        return result
