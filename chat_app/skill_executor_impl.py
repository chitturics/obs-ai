"""
Skill Executor Implementation — Dispatch, ReAct, and metrics recording helpers.

Extracted from skill_executor.py to keep that file under 600 lines.
These are module-level functions that take the executor instance as their
first argument; the SkillExecutor class methods delegate to them.
"""
import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dispatch — routes execution to the correct backend
# ---------------------------------------------------------------------------

async def dispatch_skill(executor, source: str, handler_key: str, params: Dict[str, Any]):
    """Dispatch execution to the appropriate backend.

    Args:
        executor: The SkillExecutor instance (provides _tool_registry, _skills_manager).
        source: Resolution source ("tool_registry", "skills_manager", "internal", "react_loop").
        handler_key: The handler key string to execute.
        params: Execution parameters.

    Returns:
        SkillExecResult
    """
    from chat_app.skill_executor import SkillExecResult, get_internal_handler

    if source == "tool_registry":
        try:
            tool_result = await asyncio.wait_for(
                executor._tool_registry.execute(handler_key, **params),
                timeout=30.0,
            )
            return SkillExecResult(
                success=tool_result.success,
                output=tool_result.output,
                data=tool_result.data,
                error=tool_result.error,
            )
        except asyncio.TimeoutError:
            logger.error("[SKILL_EXEC] Tool '%s' timed out after 30s", handler_key)
            return SkillExecResult(
                success=False, output="",
                error=f"Tool timed out after 30s: {handler_key}",
            )

    elif source == "skills_manager":
        if executor._skills_manager:
            try:
                sm_result = await asyncio.wait_for(
                    executor._skills_manager.execute_action(
                        handler_key, params=params, user_approved=True
                    ),
                    timeout=30.0,
                )
                return SkillExecResult(
                    success=sm_result.success,
                    output=sm_result.output,
                    data=sm_result.data,
                    error=sm_result.error,
                )
            except asyncio.TimeoutError:
                logger.error("[SKILL_EXEC] SkillsManager '%s' timed out after 30s", handler_key)
                return SkillExecResult(
                    success=False, output="",
                    error=f"Skills manager timed out after 30s: {handler_key}",
                )
        return SkillExecResult(
            success=False, output="",
            error="SkillsManager not available",
        )

    elif source == "internal":
        handler = get_internal_handler(handler_key)
        if handler:
            try:
                handler_timeout = 30.0
                if asyncio.iscoroutinefunction(handler):
                    output = await asyncio.wait_for(
                        handler(**params), timeout=handler_timeout
                    )
                else:
                    output = await asyncio.wait_for(
                        asyncio.to_thread(handler, **params),
                        timeout=handler_timeout,
                    )
                return SkillExecResult(
                    success=True,
                    output=str(output) if output else "",
                    data=output,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[SKILL_EXEC] Internal handler '%s' timed out after 30s", handler_key
                )
                return SkillExecResult(
                    success=False, output="",
                    error=f"Handler timed out after 30s: {handler_key}",
                )
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.error(
                    "[SKILL_EXEC] Internal handler '%s' failed: %s: %s",
                    handler_key, type(exc).__name__, exc,
                    exc_info=True,
                )
                return SkillExecResult(
                    success=False, output="",
                    error=f"Handler error: {type(exc).__name__}: {exc}",
                )
        return SkillExecResult(
            success=False, output="",
            error=f"Internal handler not found: {handler_key}",
        )

    elif source == "react_loop":
        # Call the method on the executor so that mocks/patches on
        # SkillExecutor._execute_react are respected (e.g. in tests).
        return await executor._execute_react(params)

    return SkillExecResult(
        success=False, output="",
        error=f"Unknown source: {source}",
    )


# ---------------------------------------------------------------------------
# ReAct Loop execution
# ---------------------------------------------------------------------------

async def execute_react(executor, params: Dict[str, Any]):
    """Execute via the ReAct reasoning loop with timeout protection."""
    from chat_app.skill_executor import SkillExecResult

    try:
        from chat_app.react_loop import execute_react_loop, format_tool_context_for_llm
        user_input = params.get("user_input", params.get("query", ""))
        intent = params.get("intent", "spl_generation")

        trace = await asyncio.wait_for(
            execute_react_loop(
                user_input=user_input,
                intent=intent,
                registry=executor._tool_registry,
            ),
            timeout=60.0,
        )

        context = format_tool_context_for_llm(trace)
        return SkillExecResult(
            success=bool(context),
            output=context or "",
            data={"trace": trace, "tools_used": trace.tools_used},
        )
    except asyncio.TimeoutError:
        logger.error("[SKILL_EXEC] ReAct loop timed out after 60s")
        return SkillExecResult(
            success=False, output="",
            error="ReAct loop timed out after 60s",
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(
            "[SKILL_EXEC] ReAct loop failed: %s: %s",
            type(exc).__name__, exc,
            exc_info=True,
        )
        return SkillExecResult(
            success=False, output="",
            error=f"ReAct loop failed: {type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# Execution metrics recording
# ---------------------------------------------------------------------------

def record_skill_execution(executor, result) -> None:
    """Record execution metrics for a completed skill execution.

    Writes to the executor's in-memory log, execution journal, activity
    timeline, circuit breaker, latency budgets, SLO tracker, audit log,
    and Prometheus metrics.

    Args:
        executor: The SkillExecutor instance (has _execution_count, etc.).
        result: A SkillExecResult instance.
    """
    import logging as _logging

    executor._execution_count += 1
    executor._total_latency_ms += result.duration_ms
    if not result.success and not result.approval_required:
        executor._error_count += 1

    executor._execution_log.append({
        "skill": result.skill_name,
        "handler_key": result.handler_key,
        "source": result.source,
        "success": result.success,
        "duration_ms": round(result.duration_ms, 2),
        "timestamp": __import__("time").time(),
        "error": result.error,
        "intent": getattr(result, '_intent', None),
    })
    # Keep last 200 entries
    if len(executor._execution_log) > 200:
        executor._execution_log = executor._execution_log[-200:]

    # Persist to execution journal
    try:
        from chat_app.execution_journal import get_journal
        from chat_app.schemas import SkillExecutionEvent
        get_journal().log(SkillExecutionEvent(
            skill_name=result.skill_name,
            handler_key=result.handler_key,
            source=result.source,
            success=result.success,
            duration_ms=result.duration_ms,
            error=result.error,
        ))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[SKILL] Optional operation failed: %s", _exc)

    # Record to unified activity timeline
    try:
        from chat_app.activity_timeline import get_timeline
        get_timeline().record(
            event_type="tool_execution",
            actor=result.source or "skill_executor",
            action="execute",
            target=result.skill_name or result.handler_key,
            details={
                "handler_key": result.handler_key,
                "source": result.source,
                "duration_ms": round(result.duration_ms, 1),
                "intent": getattr(result, '_intent', None),
            },
            status="ok" if result.success else "error",
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[SKILL] Optional operation failed: %s", _exc)

    # Circuit breaker feedback
    try:
        from chat_app.circuit_breaker import get_circuit_breaker_registry
        cb = get_circuit_breaker_registry()
        if result.success:
            cb.record_success(result.handler_key)
        elif not result.approval_required:
            cb.record_failure(result.handler_key)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[SKILL] Optional operation failed: %s", _exc)

    # Latency budget tracking
    try:
        from chat_app.latency_budgets import get_latency_tracker
        get_latency_tracker().record(result.handler_key, result.duration_ms)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[SKILL] Optional operation failed: %s", _exc)

    # SLO tracking
    try:
        from chat_app.slo_tracker import get_slo_tracker
        slo = get_slo_tracker()
        slo.record("tool_success_rate", success=result.success)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[SKILL] Optional operation failed: %s", _exc)

    # Audit log for failed executions
    if not result.success and not result.approval_required:
        try:
            from chat_app.audit_log import get_audit_log
            get_audit_log().append(
                event_type="skill_execution",
                actor=result.source or "skill_executor",
                action="execute_failed",
                target=result.skill_name or result.handler_key,
                details={
                    "handler_key": result.handler_key,
                    "error": result.error,
                    "duration_ms": round(result.duration_ms, 1),
                },
                severity="medium",
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[SKILL] Optional operation failed: %s", _exc)

    try:
        from chat_app.logging_utils import structured_log
        structured_log(logger, _logging.INFO, "SKILL_EXEC", "Skill executed",
                       skill=result.skill_name, handler=result.handler_key,
                       source=result.source, success=result.success,
                       duration_ms=round(result.duration_ms, 1),
                       error=result.error if not result.success else None)
    except ImportError:
        logger.info(
            "[SKILL_EXEC] %s:%s via %s -> %s (%.0fms)",
            result.skill_name, result.handler_key, result.source,
            "OK" if result.success else "FAIL", result.duration_ms,
        )

    # Prometheus metrics
    try:
        from prometheus_metrics import record_skill_execution, record_skill_execution_latency
        skill_label = result.skill_name or result.handler_key
        record_skill_execution(skill_name=skill_label, success=result.success)
        if result.duration_ms > 0:
            record_skill_execution_latency(skill_label, result.duration_ms / 1000.0)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[SKILL] Optional operation failed: %s", _exc)
