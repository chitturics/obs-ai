"""
Post-response telemetry and recording helpers extracted from message_handler.py.

These functions handle analytics, health metrics, episodic/archival memory,
observability traces, agent quality feedback, evolution engine, and OTel span
finalization after the main pipeline has produced a response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PipelineTelemetryContext:
    """Bundles all state needed by post-response telemetry recorders."""

    user_input: str
    plan: Any  # QueryPlan
    quality: Any  # Optional quality result
    quality_value: Optional[float]  # quality.overall or None
    username: str
    thread_id: str
    query_elapsed: float  # seconds
    memory_chunks: List[Any]
    chroma_source: str
    latency_tracker: Any  # LatencyTracker
    time_module: Any  # the `time` module reference
    query_start: float  # monotonic timestamp
    context: Any  # MessageHandlerContext
    confidence: Any  # Optional confidence result
    detected_profile: Optional[str]
    current_profile: str
    collections_used: List[str]
    final_response: str
    active_agent_name: str
    orch_result: Any  # Optional OrchestrationResult
    request_id: str
    react_context: str
    workflow_arc: str


async def record_post_response_telemetry(tc: PipelineTelemetryContext) -> None:
    """Record analytics, metrics, memory, and observability after a response.

    Each subsystem is wrapped in try/except so failures are isolated.
    """
    _time = tc.time_module

    # --- Analytics Engine: record query for BI dashboards ---
    try:
        from chat_app.analytics import get_analytics_engine
        get_analytics_engine().record(
            query=tc.user_input,
            intent=tc.plan.intent or "unknown",
            confidence=tc.quality.overall if tc.quality else 0.0,
            quality=tc.quality_value,
            user_id=tc.username or "anonymous",
            response_time_ms=tc.query_elapsed * 1000,
            chunks_found=len(tc.memory_chunks),
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # --- Idle Worker: signal that a query was processed ---
    try:
        from chat_app.idle_worker import get_idle_worker
        get_idle_worker().record_query()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # --- Human-in-the-Loop: add insights for low quality ---
    try:
        from chat_app.human_loop import get_human_loop_manager
        _hlm = get_human_loop_manager()
        if tc.quality and tc.quality.overall < 0.4:
            _hlm.add_insight(
                insight_type="warning",
                message=f"Low quality response (score={tc.quality.overall:.2f}) for query: '{tc.user_input[:80]}'",
                data={"intent": tc.plan.intent, "quality": tc.quality.overall, "chunks": len(tc.memory_chunks)},
            )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # --- Internal health metrics ---
    try:
        from chat_app.health_monitor import get_internal_metrics
        im = get_internal_metrics()
        im.increment("queries_total")
        im.record_latency(tc.query_elapsed * 1000)
        if tc.quality:
            im.record_quality(tc.quality.overall)
            if tc.quality.overall >= 0.5:
                im.increment("queries_success")
            else:
                im.increment("queries_failed")
        else:
            im.increment("queries_success")
        if tc.chroma_source == "cache":
            im.increment("cache_hits")
        else:
            im.increment("cache_misses")
        # Record component latencies
        for component, ms in tc.latency_tracker.to_dict().items():
            im.increment(f"latency_{component}_total_ms", int(ms))
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # --- Episodic Memory: store interaction episode ---
    _inferred_success = -1
    _quality_score = tc.quality.overall if tc.quality else None
    _conf_score = tc.confidence.score if tc.confidence else 0.0
    try:
        from chat_app.episodic_memory import store_episode
        _query_elapsed_ms = int((_time.monotonic() - tc.query_start) * 1000)

        # Auto-infer success from quality score + confidence
        if _quality_score is not None:
            if _quality_score >= 0.7 and _conf_score >= 0.5:
                _inferred_success = 1
            elif _quality_score < 0.4 or tc.chroma_source == "error":
                _inferred_success = 0

        await store_episode(
            engine=tc.context.engine,
            username=tc.username,
            query=tc.user_input,
            intent=tc.plan.intent or "unknown",
            profile=tc.detected_profile or tc.current_profile or "general",
            strategy_used=tc.chroma_source or "default",
            collections_searched=tc.collections_used,
            chunks_found=len(tc.memory_chunks),
            response_length=len(tc.final_response),
            confidence=_conf_score,
            success=_inferred_success,
            duration_ms=_query_elapsed_ms,
            extra_metadata={
                "quality_score": _quality_score,
                "auto_inferred": _inferred_success != -1,
            },
        )
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # --- Archival Memory: store high-quality facts for long-term retention ---
    try:
        if _inferred_success == 1 and len(tc.final_response) > 100:
            from chat_app.archival_memory import get_archival_memory
            _archival = get_archival_memory()
            _arch_tags = [tc.plan.intent or "unknown"]
            if tc.detected_profile:
                _arch_tags.append(tc.detected_profile)
            _archival.store(
                content=f"Q: {tc.user_input[:200]} | A: {tc.final_response[:300]}",
                source="learning",
                category="pattern",
                tags=_arch_tags,
                user_id=tc.username or "",
                importance=min(0.3 + (_conf_score or 0) * 0.4 + (_quality_score or 0) * 0.3, 1.0),
            )
            # Periodic save (every 10 stores)
            if _archival.get_stats()["total_notes"] % 10 == 0:
                _archival.save()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # --- Observability: record trace, SLO data, evaluate alerts ---
    try:
        from chat_app.observability import get_observability_manager
        _obs = get_observability_manager()

        # Record SLO data points
        _obs.record_slo_data("response_latency_p95", tc.query_elapsed * 1000)
        _obs.record_slo_data("availability", 0.0 if tc.chroma_source == "error" else 1.0)
        if tc.quality:
            _obs.record_slo_data("response_quality", tc.quality.overall)
            _obs.record_histogram("quality_scores", tc.quality.overall)
        _obs.record_slo_data("error_rate", 1.0 if tc.chroma_source == "error" else 0.0)

        # Record trace
        trace = _obs.start_trace(query=tc.user_input, user_id=tc.username, intent=tc.plan.intent or "unknown")
        routing_span = trace.create_span("routing", intent=tc.plan.intent)
        routing_span.finish()
        retrieval_span = trace.create_span("retrieval", chunks=len(tc.memory_chunks), source=tc.chroma_source)
        retrieval_span.finish()
        llm_span = trace.create_span("llm_inference", model=tc.context.settings.ollama.model if hasattr(tc.context, 'settings') else "unknown")
        llm_span.finish()
        if tc.quality:
            eval_span = trace.create_span("quality_eval", score=tc.quality.overall)
            eval_span.finish()
        _obs.finish_trace(trace.trace_id)

        # Evaluate alert rules
        _obs.evaluate_alerts()
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # --- Agent quality feedback loop ---
    try:
        if tc.active_agent_name and tc.quality:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            get_agent_dispatcher().record_quality(
                tc.active_agent_name, tc.plan.intent or "unknown", tc.quality.overall
            )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # --- Evolution Engine: record strategy payoff + agent reputation ---
    try:
        from chat_app.evolution_engine import get_evolution_engine
        _evo = get_evolution_engine()
        _evo_quality = tc.quality.overall if tc.quality else 0.5
        _evo_latency = tc.query_elapsed * 1000
        _evo_strategy = getattr(tc.orch_result, 'strategy_used', 'single_agent') if tc.orch_result else 'single_agent'
        _evo.record_strategy_outcome(
            strategy=_evo_strategy,
            intent=tc.plan.intent or "unknown",
            quality=_evo_quality,
            latency_ms=_evo_latency,
        )
        if tc.active_agent_name:
            _evo.record_agent_outcome(
                agent_name=tc.active_agent_name,
                quality=_evo_quality,
                success=bool(tc.quality and tc.quality.overall >= 0.5),
            )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # --- Workflow Memory: record step ---
    try:
        from chat_app.workflow_memory import get_workflow_memory
        _wm = get_workflow_memory()
        _answer_summary = (tc.final_response or "")[:200]
        _wm.record_step(
            user_id=tc.username or "anonymous",
            query=tc.user_input,
            answer_summary=_answer_summary,
            intent=tc.plan.intent if tc.plan else "unknown",
            session_id=tc.thread_id or "",
            confidence=tc.quality.overall if tc.quality else 0.0,
            workflow_arc=tc.workflow_arc,
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass
