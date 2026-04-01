"""Pipeline Telemetry Stage — session recording, metrics, and post-response bookkeeping.

Extracted from message_handler.py per ADR-002.
Contains: functions for logging interactions, recording session state,
          Prometheus metrics, pipeline lineage finalization, execution journal,
          and tool effectiveness tracking.

Note: The bulk of post-response telemetry (analytics, episodic memory, observability,
agent quality, evolution engine) lives in message_helpers.py (PipelineTelemetryContext).
This module handles the remaining in-line telemetry that was embedded in on_message().
"""

import logging
from typing import Any, Dict, List, Optional

import chainlit as cl

from feedback_logger import log_interaction, log_bad_spl_generation
from prometheus_metrics import record_query
from chat_app.pipeline_lineage import finalize_trace
from chat_app.schemas import QueryEvent
from chat_app.user_profiles import get_profile_manager

logger = logging.getLogger(__name__)


async def record_session_state(
    user_input: str,
    final_response: str,
    formatted_context: str,
    sent_msg: Any,
    active_agent_name: Optional[str],
    plan: Any,
    detected_profile: Optional[str],
    current_profile: str,
    memory_chunks: List[Any],
) -> None:
    """Store results in the Chainlit user session for subsequent turns."""
    cl.user_session.set("last_question", user_input)
    cl.user_session.set("last_answer", final_response)
    cl.user_session.set("last_context", formatted_context)
    cl.user_session.set("last_message_id", getattr(sent_msg, "id", None))
    cl.user_session.set("last_agent_name", active_agent_name or "")
    cl.user_session.set("last_intent", plan.intent or "unknown")

    # Store conversation turn for multi-turn context
    try:
        from chat_app.conversation_memory import store_conversation_turn
        store_conversation_turn(
            question=user_input,
            answer=final_response,
            intent=plan.intent or "",
            profile=detected_profile or current_profile or "",
        )
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)

    # Track which collections contributed to this response (for adaptive RAG learning)
    collections_used = list({c.get("collection", "") for c in memory_chunks if c.get("collection")})
    cl.user_session.set("last_collections_used", collections_used)


async def record_interaction_logs(
    engine: Any,
    username: str,
    thread_id: str,
    user_input: str,
    final_response: str,
    formatted_context: str,
) -> None:
    """Log the interaction to the database and handle bad SPL tracking."""
    try:
        await log_interaction(engine, username, thread_id, user_input, final_response, formatted_context)
    except (OSError, ValueError, RuntimeError):
        pass

    # Log bad SPL generation for fine-tuning if it occurred
    if cl.user_session.get("last_spl_gen_failed"):
        try:
            bad_spl_info = cl.user_session.get("bad_spl_info", {})
            await log_bad_spl_generation(
                engine=engine,
                username=username,
                thread_id=thread_id,
                user_question=user_input,
                generated_spl=bad_spl_info.get("spl", ""),
                validation_errors=bad_spl_info.get("errors", []),
                llm_context=formatted_context,
            )
            pass
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)
        finally:
            cl.user_session.set("last_spl_gen_failed", None)
            cl.user_session.set("bad_spl_info", None)


def record_user_profile_metrics(
    username: str,
    user_input: str,
    query_start: float,
    time_module: Any,
) -> None:
    """Detect reformulation and update average response time in user learning profile."""
    try:
        _profile_mgr = get_profile_manager()
        _prev_question = cl.user_session.get("last_question")
        if _prev_question:
            _profile_mgr.detect_reformulation(username or "anonymous", user_input, _prev_question)
        # Update response time
        _total_ms = (time_module.monotonic() - query_start) * 1000
        _up = _profile_mgr.get_profile(username or "anonymous")
        if _up.query_count > 0:
            n = _up.query_count
            _up.avg_response_time_ms = (_up.avg_response_time_ms * (n - 1) + _total_ms) / n
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)


def record_prometheus_and_lineage(
    plan: Any,
    detected_profile: Optional[str],
    current_profile: str,
    query_elapsed: float,
    memory_chunks: List[Any],
    chroma_source: str,
    quality: Any,
    latency_tracker: Any,
    request_id: str,
    orch_result: Any,
    active_agent_name: Optional[str],
) -> None:
    """Record Prometheus metrics, pipeline lineage, and final logging."""
    quality_value = quality.overall if quality else None

    record_query(
        intent=plan.intent or "unknown",
        profile=detected_profile or current_profile or "general",
        latency=query_elapsed,
    )

    _latency_summary = latency_tracker.summary()
    _stage_timings = latency_tracker.to_dict() if hasattr(latency_tracker, 'to_dict') else {}
    logger.info(
        "[PIPELINE] intent=%s profile=%s total_ms=%.0f chunks=%d quality=%s rid=%s stages={%s}",
        plan.intent, detected_profile or current_profile,
        query_elapsed * 1000, len(memory_chunks),
        f"{quality_value:.2f}" if quality_value is not None else "n/a",
        request_id, _latency_summary,
        extra={"stage": "pipeline_complete", "intent": plan.intent,
               "profile": detected_profile or current_profile,
               "total_ms": round(query_elapsed * 1000),
               "chunks": len(memory_chunks),
               "quality": quality_value,
               "request_id": request_id,
               "stage_timings": _stage_timings},
    )
    try:
        from chat_app.prometheus_metrics import record_pipeline_stages as _rps
        _rps(_stage_timings)
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)

    # Finalize pipeline lineage trace
    finalize_trace(
        strategy_used=getattr(orch_result, 'strategy_used', '') if orch_result else '',
        agent_name=active_agent_name or '',
        quality_score=quality_value,
        collections_searched=[chroma_source] if chroma_source else [],
    )


def record_execution_journal(
    request_id: str,
    user_input: str,
    plan: Any,
    detected_profile: Optional[str],
    current_profile: str,
    orch_result: Any,
    active_agent_name: Optional[str],
    memory_chunks: List[Any],
    quality_value: Optional[float],
    gci_record: Any,
    query_elapsed: float,
    chroma_source: str,
) -> None:
    """Log query event to the execution journal."""
    try:
        from chat_app.execution_journal import get_journal
        get_journal().log(QueryEvent(
            request_id=request_id,
            query=user_input[:500],
            intent=plan.intent or "unknown",
            profile=detected_profile or current_profile or "",
            strategy_used=getattr(orch_result, 'strategy_used', '') if orch_result else '',
            agent_name=active_agent_name or '',
            chunks_found=len(memory_chunks),
            quality_score=min(1.0, max(0.0, quality_value)) if quality_value is not None else 0.0,
            gci_score=gci_record.overall_score if gci_record else 0.0,
            duration_ms=query_elapsed * 1000,
            success=chroma_source != "error",
        ))
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)


def record_tool_effectiveness(
    plan: Any,
    quality: Any,
    query_elapsed: float,
    react_context: Any,
) -> None:
    """Record tool effectiveness metrics for the pipeline and react loop."""
    try:
        from chat_app.tool_effectiveness import get_effectiveness_tracker
        _tracker = get_effectiveness_tracker()
        _tool_success = quality.overall >= 0.5 if quality else True
        _tracker.record_execution(
            tool_name="rag_pipeline",
            intent=plan.intent or "unknown",
            success=_tool_success,
            latency_ms=query_elapsed * 1000,
            query_pattern=plan.intent or "",
        )
        if react_context:
            _tracker.record_execution(
                tool_name="react_loop",
                intent=plan.intent or "unknown",
                success=_tool_success,
                latency_ms=query_elapsed * 1000,
                preceded_by="rag_pipeline",
            )
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)


def run_gci_review(
    user_input: str,
    final_response: str,
    active_agent_name: Optional[str],
    plan: Any,
    formatted_context: str,
    memory_chunks: List[Any],
    request_id: str,
) -> tuple:
    """Run the GCI Agent review-analyze-correct cycle.

    Returns (final_response, gci_record).
    """
    gci_record = None
    try:
        from chat_app.gci_agent import get_gci_agent
        _gci = get_gci_agent()
        gci_record = _gci.review(
            query=user_input,
            response=final_response,
            agent_id=active_agent_name or "default",
            intent=plan.intent or "",
            context=formatted_context,
            chunks_found=len(memory_chunks),
        )
        if _gci.should_intercept(gci_record):
            _correction = _gci.get_correction_note(gci_record)
            if _correction:
                final_response += _correction
                logger.info("[GCI] intercepted agent=%s score=%.1f rid=%s",
                           active_agent_name, gci_record.overall_score, request_id)
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)
    return final_response, gci_record


def run_slo_evaluation(
    latency_tracker: Any,
    quality: Any,
) -> None:
    """Record SLO data and evaluate alert rules."""
    try:
        from chat_app.observability import get_observability_manager
        _obs = get_observability_manager()
        _total_ms = latency_tracker.total_elapsed_ms() if hasattr(latency_tracker, 'total_elapsed_ms') else sum(latency_tracker.to_dict().values())
        _obs.record_slo_data("response_latency_p95", _total_ms / 1000.0)
        if quality:
            _obs.record_slo_data("response_quality", quality.overall)
        _obs.evaluate_alerts()
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)


def finalize_otel_span(
    otel_root_span: Any,
    otel_ctx_token: Any,
    time_module: Any,
    query_start: float,
    plan: Any,
    current_profile: str,
    chroma_source: str,
    quality: Any,
    confidence: Any,
) -> None:
    """Finalize the OTel root span with final attributes."""
    if otel_root_span is None:
        return
    try:
        from chat_app.otel_compat import AIAttributes
        _total_ms = int((time_module.monotonic() - query_start) * 1000)
        otel_root_span.set_attribute(AIAttributes.PIPELINE_DURATION_MS, _total_ms)
        otel_root_span.set_attribute(AIAttributes.PIPELINE_INTENT, plan.intent if plan else "unknown")
        otel_root_span.set_attribute(AIAttributes.PIPELINE_PROFILE, current_profile or "")
        otel_root_span.set_attribute(AIAttributes.PIPELINE_SUCCESS, chroma_source != "error")
        if quality:
            otel_root_span.set_attribute(AIAttributes.QUALITY_SCORE, quality.overall)
        if confidence:
            otel_root_span.set_attribute(AIAttributes.QUALITY_CONFIDENCE, confidence.score)
        otel_root_span.end()
        from opentelemetry import trace as _otel_trace_cleanup
        _otel_trace_cleanup.context_api.detach(otel_ctx_token)
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)


def build_reasoning_trace(
    user_settings: Dict,
    plan: Any,
    detected_profile: Optional[str],
    current_profile: str,
    memory_chunks: List[Any],
    confidence: Any,
    react_context: Any,
    time_module: Any,
    query_start: float,
) -> Optional[str]:
    """Build the reasoning transparency trace HTML snippet."""
    try:
        _show_reasoning = user_settings.get("show_reasoning", True)
        if not _show_reasoning:
            return None
        from chat_app.registry import Intent
        if plan.intent in (Intent.META_QUESTION, Intent.CLARIFICATION):
            return None
        from chat_app.proactive_insights import format_reasoning_trace
        _tools_used = []
        if react_context:
            _tools_used = [t for t in getattr(plan, '_react_tools', [])] if hasattr(plan, '_react_tools') else ["agentic_analysis"]
        _collections_searched = getattr(plan, 'retrieval_collections', None) or []
        return format_reasoning_trace(
            intent=plan.intent or "unknown",
            profile=detected_profile or current_profile or "general",
            chunks_found=len(memory_chunks) if memory_chunks else 0,
            collections_searched=_collections_searched[:5],
            confidence_score=confidence.score if confidence else (plan.confidence or 0.5),
            tools_used=_tools_used,
            latency_ms=int((time_module.monotonic() - query_start) * 1000),
        )
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)
        return None


def record_admin_activity(
    user_input: str,
    plan: Any,
    username: str,
    thread_id: str,
    collections_used: List[str],
    memory_chunks: List[Any],
    quality: Any,
    query_elapsed: float,
    detected_profile: Optional[str],
    current_profile: str,
) -> None:
    """Record enriched admin activity tracking."""
    try:
        from chat_app.admin_api import record_query as _admin_record
        _admin_record(
            query=user_input,
            intent=plan.intent,
            user_id=username,
            session_id=thread_id,
            collections_searched=collections_used,
            chunks_found=len(memory_chunks),
            confidence=quality.overall if quality else 0.0,
            duration_ms=int(query_elapsed * 1000),
            profile=detected_profile or current_profile,
        )
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_telemetry.py", _exc)
