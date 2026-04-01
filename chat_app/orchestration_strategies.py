"""
Configurable multi-agent orchestration strategies.

Provides pluggable orchestration patterns that wrap existing components
(AgentDispatcher, WorkflowOrchestrator, SkillExecutor, SelfEvaluator).

The entry point ``execute_orchestration()`` is called from message_handler.py
and returns an ``OrchestrationResult`` that maps directly into the existing
context injection variables (agent_context, workflow_context, react_context).

Strategies (17 total):
  Core:       single_agent, parallel, hierarchical, iterative, coordinator,
              voting, react, review_critique, workflow, swarm, human_in_loop, adaptive
  OpenMAIC:   two_stage_pipeline, action_engine, director_graph, feedback_loop
  Governance: democratic, capitalist, authoritarian, parliament, meritocratic

Implementation is split across modules for maintainability:
  strategies_core.py      — Core strategies 1-12 (SingleAgent … Adaptive)
  strategies_openmaiac.py — OpenMAIC strategies (TwoStage … FeedbackLoop)
  governance_strategies.py — Governance strategies
This file owns: base classes, registry, fallback chains, execution log,
quality tracking, and the public ``execute_orchestration()`` entry point.
All strategy classes are re-exported here for backward-compatible imports.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

# Base classes live in orchestration_base to avoid circular imports with
# strategies_core and strategies_openmaiac.  Re-exported here so that all
# existing callers using:
#   from chat_app.orchestration_strategies import OrchestrationResult
# continue to work without modification.
from chat_app.orchestration_base import (  # noqa: F401
    OrchestrationResult,
    OrchestrationStrategy,
)

logger = logging.getLogger(__name__)

try:
    from chat_app.logging_utils import structured_log as _orch_structured_log
except ImportError:
    def _orch_structured_log(lg, level, tag, msg, **kw):  # type: ignore
        lg.log(level, "[%s] %s %s", tag, msg, kw)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_STRATEGY_REGISTRY: Dict[str, OrchestrationStrategy] = {}


def register_strategy(strategy: OrchestrationStrategy) -> None:
    _STRATEGY_REGISTRY[strategy.name] = strategy


def get_strategy(name: str) -> Optional[OrchestrationStrategy]:
    _ensure_registered()
    return _STRATEGY_REGISTRY.get(name)


def list_strategies() -> List[Dict[str, Any]]:
    _ensure_registered()
    return [
        {"name": strategy.name, "resource_weight": strategy.resource_weight,
         "description": (strategy.__class__.__doc__ or "").strip().split("\n")[0]}
        for strategy in _STRATEGY_REGISTRY.values()
    ]


# ---------------------------------------------------------------------------
# Fallback chains
# ---------------------------------------------------------------------------

FALLBACK_CHAIN: Dict[str, List[str]] = {
    "adaptive":       ["hierarchical", "single_agent"],
    "hierarchical":   ["workflow", "single_agent"],
    "coordinator":    ["hierarchical", "single_agent"],
    "voting":         ["parallel", "single_agent"],
    "parallel":       ["single_agent"],
    "swarm":          ["coordinator", "single_agent"],
    "iterative":      ["single_agent"],
    "review_critique": ["single_agent"],
    "workflow":       ["single_agent"],
    "react":          ["single_agent"],
    "human_in_loop":  ["single_agent"],
    "single_agent":   [],
    # Governance models
    "democratic":     ["voting", "single_agent"],
    "capitalist":     ["meritocratic", "single_agent"],
    "authoritarian":  ["single_agent"],
    "parliament":     ["democratic", "single_agent"],
    "meritocratic":   ["capitalist", "single_agent"],
    # Supervisor
    "supervisor":     ["adaptive", "single_agent"],
    # OpenMAIC-inspired
    "two_stage_pipeline": ["hierarchical", "single_agent"],
    "action_engine":  ["two_stage_pipeline", "single_agent"],
    "director_graph": ["hierarchical", "single_agent"],
    "feedback_loop":  ["review_critique", "single_agent"],
}


# ---------------------------------------------------------------------------
# Core strategies 1-12 (imported from strategies_core.py)
# ---------------------------------------------------------------------------
# Re-exported here so that all existing imports of the form
#   from chat_app.orchestration_strategies import SingleAgentStrategy
# continue to work without modification.

from chat_app.strategies_core import (  # noqa: E402
    SingleAgentStrategy,
    ParallelStrategy,
    HierarchicalStrategy,
    IterativeStrategy,
    CoordinatorStrategy,
    VotingStrategy,
    ReactStrategy,
    ReviewCritiqueStrategy,
    WorkflowStrategy,
    SwarmStrategy,
    HumanInLoopStrategy,
    AdaptiveStrategy,
)

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# OpenMAIC-inspired strategies (imported from strategies_openmaiac.py)
# ---------------------------------------------------------------------------
# Re-exported here so that all existing imports of the form
#   from chat_app.orchestration_strategies import TwoStagePipelineStrategy
# continue to work without modification.

from chat_app.strategies_openmaiac import (  # noqa: E402
    TwoStagePipelineStrategy,
    ActionEngineStrategy,
    DirectorGraphStrategy,
    FeedbackLoopStrategy,
)

# ---------------------------------------------------------------------------
# Governance strategies (extracted to chat_app/governance_strategies.py)
# ---------------------------------------------------------------------------
# Classes: DemocraticStrategy, CapitalistStrategy, AuthoritarianStrategy,
#          ParliamentStrategy, MeritocraticStrategy
# Registered via register_governance_strategies() in _ensure_registered().


# Register all strategies
# ---------------------------------------------------------------------------

_strategies_registered = False
_registry_lock = threading.Lock()


def _ensure_registered():
    """Lazily register all strategies on first use (avoids blocking module import)."""
    global _strategies_registered
    if _strategies_registered:
        return
    with _registry_lock:
        if _strategies_registered:  # double-checked locking
            return
        _strategies_registered = True
        for cls in [
            SingleAgentStrategy, ParallelStrategy, HierarchicalStrategy,
            IterativeStrategy, CoordinatorStrategy, VotingStrategy,
            ReactStrategy, ReviewCritiqueStrategy, WorkflowStrategy,
            SwarmStrategy, HumanInLoopStrategy, AdaptiveStrategy,
            # OpenMAIC-inspired strategies
            TwoStagePipelineStrategy, ActionEngineStrategy,
            DirectorGraphStrategy, FeedbackLoopStrategy,
        ]:
            register_strategy(cls())
        # Register governance strategies (democratic, capitalist, etc.)
        from chat_app.governance_strategies import register_governance_strategies
        register_governance_strategies()
        # Register supervisor strategy (18th)
        try:
            import chat_app.supervisor_agent  # noqa: F401
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass


# ---------------------------------------------------------------------------
# Execution log (in-memory, for admin API)
# ---------------------------------------------------------------------------

_MAX_EXEC_LOG = 200
_execution_log: deque = deque(maxlen=_MAX_EXEC_LOG)
_log_lock = threading.Lock()
_log_loaded = False


def _load_persisted_log() -> None:
    """Load recent orchestration events from execution journal on first access."""
    global _log_loaded
    if _log_loaded:
        return
    _log_loaded = True
    try:
        from chat_app.execution_journal import get_journal
        journal = get_journal()
        # Load today's and yesterday's orchestration events
        import datetime
        today = datetime.date.today().isoformat()
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        events = []
        for dt in [yesterday, today]:
            events.extend(journal.query_events(event_type="orchestration", date=dt, limit=100))
        # Sort by timestamp ascending and append to execution log
        events.sort(key=lambda e: e.get("timestamp", 0))
        with _log_lock:
            for evt in events[-_MAX_EXEC_LOG:]:
                _execution_log.append(evt)
        if events:
            logger.info("[ORCH] Loaded %d persisted orchestration events", len(events))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ORCH] Could not load persisted log: %s", exc)


def get_execution_log(limit: int = 50) -> List[Dict[str, Any]]:
    _load_persisted_log()
    with _log_lock:
        snapshot = list(_execution_log)
    return snapshot[-limit:]


def get_orchestration_summary() -> Dict[str, Any]:
    _load_persisted_log()
    with _log_lock:
        snapshot = list(_execution_log)
    if not snapshot:
        return {"total": 0}
    total = len(snapshot)
    successes = sum(1 for e in snapshot if e.get("success"))
    fallbacks = sum(1 for e in snapshot if e.get("fallback_used"))
    by_strategy: Dict[str, int] = {}
    for entry in snapshot:
        strategy_name = entry.get("strategy_used", "unknown")
        by_strategy[strategy_name] = by_strategy.get(strategy_name, 0) + 1
    return {
        "total": total,
        "success_rate": round(successes / total, 4),
        "fallback_rate": round(fallbacks / total, 4),
        "by_strategy": by_strategy,
        "avg_quality": round(
            sum(e.get("quality_score", 0) for e in snapshot) / total, 3,
        ),
        "avg_duration_ms": round(
            sum(e.get("duration_ms", 0) for e in snapshot) / total, 1,
        ),
    }


# ---------------------------------------------------------------------------
# Smart strategy suggestion + quality tracking
# ---------------------------------------------------------------------------

# Strategy quality tracking: {strategy_name: [scores]}
_strategy_quality: Dict[str, List[float]] = {}
_strategy_quality_lock = threading.Lock()


def _suggest_strategy(intent: str, user_input: str, default: str) -> str:
    """Suggest a better strategy based on input characteristics.

    Returns the default if no better suggestion is available.
    """
    word_count = len(user_input.split())
    input_lower = user_input.lower()

    # Intent-based overrides (domain-specific defaults)
    _INTENT_STRATEGY_DEFAULTS: Dict[str, str] = {
        # Security intents benefit from a verification pass
        "security": "review_critique",
        "security_config": "review_critique",
        "security_audit": "review_critique",
        # Complex Cribl domain work benefits from hierarchical decomposition
        "cribl_pipeline": "hierarchical",
        "cribl_config": "hierarchical",
    }
    if intent in _INTENT_STRATEGY_DEFAULTS:
        return _INTENT_STRATEGY_DEFAULTS[intent]

    # Comparison queries → parallel
    compare_keywords = {"compare", "difference", "differ", "vs", "versus"}
    if any(kw in input_lower for kw in compare_keywords):
        return "parallel"

    # Long queries (>30 words) likely multi-part → hierarchical
    if word_count > 30:
        return "hierarchical"

    # Multi-part queries (and/or/also) with enough words → hierarchical
    multi_part = {"and also", "additionally", "furthermore", "as well as", "plus"}
    if word_count > 20 and any(kw in input_lower for kw in multi_part):
        return "hierarchical"

    # Complex questions (why, how does, explain the difference) → review_critique
    complex_patterns = {"why does", "how does", "explain the", "what is the difference"}
    if any(pat in input_lower for pat in complex_patterns) and word_count > 12:
        return "review_critique"

    # Quality-weighted: if default strategy has poor history, try alternatives
    with _strategy_quality_lock:
        scores = _strategy_quality.get(default, [])
        if len(scores) >= 5:
            avg = sum(scores[-10:]) / len(scores[-10:])
            if avg < 0.4:
                # Default strategy is underperforming, try alternatives
                alternatives = ["single_agent", "review_critique", "parallel"]
                for alt in alternatives:
                    alt_scores = _strategy_quality.get(alt, [])
                    if alt_scores:
                        alt_avg = sum(alt_scores[-10:]) / len(alt_scores[-10:])
                        if alt_avg > avg + 0.15:
                            return alt

    # Tool effectiveness awareness: if tools for this intent have low success
    # rates, escalate to a more cautious strategy (review_critique adds a
    # verification pass that can catch tool failures early)
    try:
        from chat_app.tool_effectiveness import get_effectiveness_tracker
        tracker = get_effectiveness_tracker()
        intent_tools = tracker._intent_stats.get(intent, {})
        if intent_tools:
            tool_rates = [
                s.success_rate for s in intent_tools.values()
                if s.total_executions >= 3
            ]
            if tool_rates:
                avg_tool_success = sum(tool_rates) / len(tool_rates)
                # If average tool success rate is below 50%, use review_critique
                # for its built-in verification pass (unless already cautious)
                if avg_tool_success < 0.5 and default in ("single_agent", "parallel"):
                    return "review_critique"
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    return default


def record_strategy_quality(strategy_name: str, score: float):
    """Record quality score for a strategy execution."""
    score = max(0.0, min(1.0, score))
    with _strategy_quality_lock:
        if strategy_name not in _strategy_quality:
            _strategy_quality[strategy_name] = []
        _strategy_quality[strategy_name].append(score)
        if len(_strategy_quality[strategy_name]) > 100:
            _strategy_quality[strategy_name] = _strategy_quality[strategy_name][-100:]


def get_strategy_quality_stats() -> Dict[str, Any]:
    """Get quality statistics for all strategies."""
    with _strategy_quality_lock:
        stats = {}
        for name, scores in _strategy_quality.items():
            if scores:
                average_quality = sum(scores) / len(scores)
                stats[name] = {
                    "executions": len(scores),
                    "avg_quality": round(average_quality, 3),
                    "recent_avg": round(sum(scores[-10:]) / len(scores[-10:]), 3),
                    "min": round(min(scores), 3),
                    "max": round(max(scores), 3),
                    "success_rate": round(sum(1 for s in scores if s >= 0.5) / len(scores), 3),
                    "avg_duration_ms": 0,
                }
        return stats


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def execute_orchestration(
    user_input: str,
    intent: str,
    plan: Any,
    context: Any,
    user_approved: bool = False,
) -> OrchestrationResult:
    """
    Main entry point called from message_handler.py.

    Selects strategy from settings, handles resource fallback, logs execution.
    """
    _ensure_registered()
    from chat_app.settings import get_settings
    from chat_app.resource_manager import can_run_heavy_task

    settings = get_settings()
    orch = getattr(settings, "orchestration", None)
    if orch is None:
        from chat_app.settings import OrchestrationSettings
        orch = OrchestrationSettings()

    start = time.monotonic()

    # Determine strategy
    strategy_name = orch.default_strategy
    if intent in (orch.strategy_overrides or {}):
        strategy_name = orch.strategy_overrides[intent]
    elif strategy_name == orch.default_strategy:
        # Smart suggestion when no explicit override exists
        strategy_name = _suggest_strategy(intent, user_input, strategy_name)
    if intent in (orch.human_approval_intents or []):
        strategy_name = "human_in_loop"

    # KG-aware strategy suggestion — complex SPL benefits from specific strategies
    try:
        from chat_app.knowledge_graph import SPLQueryAnalyzer
        analysis = SPLQueryAnalyzer.analyze(user_input)
        if analysis.get("has_summarization") or len(analysis.get("datamodels", [])) > 0:
            if strategy_name == orch.default_strategy:
                strategy_name = "hierarchical"
        elif len(analysis.get("commands", [])) > 5:
            if strategy_name == orch.default_strategy:
                strategy_name = "review_critique"
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    strategy = get_strategy(strategy_name)
    if strategy is None:
        logger.warning("[ORCH] Unknown strategy '%s', using single_agent", strategy_name)
        strategy = get_strategy("single_agent")
    if strategy is None:
        # Last resort: instantiate directly if registry failed
        strategy = SingleAgentStrategy()

    # Resource check for heavy strategies
    fallback_used = False
    fallback_from = ""

    if strategy.resource_weight == "heavy" and orch.resource_fallback:
        allowed, reason = can_run_heavy_task()
        if not allowed:
            logger.info("[ORCH] Resources constrained (%s), fallback for '%s'",
                        reason, strategy_name)
            fallback_from = strategy_name
            fallback_options = FALLBACK_CHAIN.get(strategy_name, ["single_agent"])
            for fallback_name in fallback_options:
                fallback_strategy = get_strategy(fallback_name)
                if fallback_strategy and fallback_strategy.resource_weight != "heavy":
                    strategy = fallback_strategy
                    fallback_used = True
                    break
            if not fallback_used:
                strategy = get_strategy("single_agent") or SingleAgentStrategy()
                fallback_used = True
            _orch_structured_log(logger, logging.INFO, "ORCH", "fallback",
                                 **{"from": fallback_from, "to": strategy.name,
                                    "reason": f"resources_constrained({reason})"})

    if strategy.resource_weight == "medium" and orch.resource_fallback:
        allowed, _ = can_run_heavy_task(max_cpu=90.0, max_memory=90.0)
        if not allowed:
            fallback_from = fallback_from or strategy.name
            fallback_to_name = strategy.name
            strategy = get_strategy("single_agent") or SingleAgentStrategy()
            fallback_used = True
            _orch_structured_log(logger, logging.INFO, "ORCH", "fallback",
                                 **{"from": fallback_to_name, "to": strategy.name,
                                    "reason": "cpu_or_memory_above_90pct"})

    logger.info("[ORCH] Executing strategy='%s' intent='%s'", strategy.name, intent)
    _orch_structured_log(logger, logging.INFO, "ORCH", "strategy",
                         strategy=strategy.name, intent=intent,
                         resource_weight=strategy.resource_weight)

    try:
        result = await asyncio.wait_for(
            strategy.execute(
                user_input, intent, plan, context, orch, user_approved,
            ),
            timeout=orch.max_duration_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning("[ORCH] Strategy '%s' timed out (%.0fs)",
                       strategy.name, orch.max_duration_seconds)
        result = OrchestrationResult(
            strategy_used=strategy.name, success=False,
            error=f"Timed out after {orch.max_duration_seconds}s",
            duration_ms=(time.monotonic() - start) * 1000,
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[ORCH] Strategy '%s' raised: %s", strategy.name, exc)
        result = OrchestrationResult(
            strategy_used=strategy.name, success=False, error=str(exc),
            duration_ms=(time.monotonic() - start) * 1000,
        )

    result.fallback_used = fallback_used
    result.fallback_from = fallback_from

    # Record strategy quality for feedback loop (always record, even 0.0 for failures)
    record_strategy_quality(result.strategy_used, result.quality_score)

    entry = {**result.to_dict(), "intent": intent, "timestamp": time.time()}
    with _log_lock:
        _execution_log.append(entry)

    # Persist to execution journal
    try:
        from chat_app.execution_journal import get_journal
        from chat_app.schemas import OrchestrationEvent
        get_journal().log(OrchestrationEvent(
            strategy_used=result.strategy_used,
            intent=intent,
            quality_score=min(1.0, max(0.0, result.quality_score)),
            duration_ms=result.duration_ms,
            fallback_used=result.fallback_used,
            iterations=result.iterations,
            success=result.success,
            error=result.error,
        ))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[ORCH] Journal logging failed: %s", exc)

    # Record Prometheus orchestration metrics
    try:
        from chat_app.prometheus_metrics import record_orchestration
        record_orchestration(
            strategy=result.strategy_used,
            success=result.success,
            latency=result.duration_ms / 1000.0,
            agents_used=result.iterations,
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ORCH] Prometheus metrics failed: %s", exc)

    # Export to Splunk HEC if configured
    try:
        from chat_app.observability import export_orchestration_to_splunk, _hec_enabled
        if _hec_enabled:
            task = asyncio.ensure_future(export_orchestration_to_splunk(entry))
            task.add_done_callback(
                lambda t: logger.warning("[ORCH] HEC export failed: %s", t.exception())
                if t.exception() else None
            )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[ORCH] HEC export setup failed: %s", exc)

    logger.info(
        "[ORCH] Complete: strategy=%s quality=%.2f iterations=%d "
        "duration=%.0fms fallback=%s",
        result.strategy_used, result.quality_score, result.iterations,
        result.duration_ms, result.fallback_used,
    )
    return result
