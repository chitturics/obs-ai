"""Universal Execution Tracker — observability for every command, skill, agent, and MCP tool.

Wraps ALL execution paths with unified tracking:
- Slash commands (/search, /doc, /explain, etc.)
- Skill executions (133 skills)
- Agent dispatches (54 agents)
- MCP tool calls (36 tools)
- Workflow tasks

Every execution produces a WorkflowTrace that records:
- Who triggered it (user, agent, system)
- What was executed (command, skill, tool)
- How it was executed (handler, strategy, agent)
- What happened (success, error, latency, cost)
- Where it fits (parent workflow, dependent tasks)

All traces feed into: audit log, activity timeline, SLO tracker, latency tracker,
circuit breaker, cost tracker, and are queryable via API.

Usage:
    from chat_app.execution_tracker import track_execution, get_execution_store

    # Decorator style
    @track_execution(category="command", name="/search")
    async def search_command(args):
        ...

    # Context manager style
    async with track_execution(category="skill", name="splunk_search") as trace:
        result = await execute_handler(...)
        trace.set_result(result)

    # Query traces
    store = get_execution_store()
    traces = store.query(category="agent", last_minutes=60)
"""

import functools
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Execution categories
# ---------------------------------------------------------------------------

class ExecCategory:
    COMMAND = "command"       # Slash commands
    SKILL = "skill"          # Skill executions
    AGENT = "agent"          # Agent dispatches
    MCP_TOOL = "mcp_tool"    # MCP tool calls
    WORKFLOW = "workflow"     # Workflow tasks
    SYSTEM = "system"        # Background/system tasks


# ---------------------------------------------------------------------------
# Workflow Trace
# ---------------------------------------------------------------------------

@dataclass
class WorkflowTrace:
    """A single execution trace — the universal unit of observability."""
    trace_id: str = ""
    parent_id: str = ""  # Parent trace (for nested executions)
    category: str = ""   # command, skill, agent, mcp_tool, workflow
    name: str = ""       # /search, splunk_search, spl_expert, obsai_search
    actor: str = ""      # Username or agent name
    intent: str = ""
    strategy: str = ""
    agent: str = ""
    department: str = ""
    persona: str = ""

    # Execution
    started_at: str = ""
    finished_at: str = ""
    latency_ms: float = 0.0
    success: bool = False
    error: Optional[str] = None
    result_summary: str = ""

    # Resource usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    chunks_retrieved: int = 0
    cost_units: float = 0.0

    # Context
    input_preview: str = ""
    handler_key: str = ""
    handler_source: str = ""  # tool_registry, internal, mcp, etc.
    safety_level: str = ""
    approval_required: bool = False

    # Children
    children: List["WorkflowTrace"] = field(default_factory=list)

    # Internal timing
    _start_mono: float = 0.0

    def set_result(self, success: bool = True, output: Any = None, error: Optional[str] = None,
                   tokens: int = 0, chunks: int = 0) -> None:
        self.success = success
        self.error = error
        if output:
            self.result_summary = str(output)[:200]
        self.completion_tokens = tokens
        self.chunks_retrieved = chunks

    def finish(self) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        if self._start_mono:
            self.latency_ms = (time.monotonic() - self._start_mono) * 1000

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "trace_id": self.trace_id,
            "category": self.category,
            "name": self.name,
            "actor": self.actor,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 1),
            "started_at": self.started_at,
        }
        if self.parent_id:
            d["parent_id"] = self.parent_id
        if self.intent:
            d["intent"] = self.intent
        if self.agent:
            d["agent"] = self.agent
        if self.strategy:
            d["strategy"] = self.strategy
        if self.error:
            d["error"] = self.error
        if self.handler_key:
            d["handler_key"] = self.handler_key
        if self.handler_source:
            d["handler_source"] = self.handler_source
        if self.prompt_tokens or self.completion_tokens:
            d["tokens"] = self.prompt_tokens + self.completion_tokens
        if self.chunks_retrieved:
            d["chunks"] = self.chunks_retrieved
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        if self.persona:
            d["persona"] = self.persona
        if self.department:
            d["department"] = self.department
        return d


# ---------------------------------------------------------------------------
# Execution Store
# ---------------------------------------------------------------------------

_MAX_TRACES = 2000
_MAX_PER_CATEGORY = 500


class ExecutionStore:
    """Stores and queries execution traces for observability.

    Traces are kept in memory (bounded deque) AND persisted to a JSONL file
    so they survive container restarts.
    """

    def __init__(self, persist_path: str = ""):
        self._traces: Deque[WorkflowTrace] = deque(maxlen=_MAX_TRACES)
        self._by_category: Dict[str, Deque[WorkflowTrace]] = defaultdict(lambda: deque(maxlen=_MAX_PER_CATEGORY))
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = defaultdict(int)
        self._error_counters: Dict[str, int] = defaultdict(int)
        import os
        from pathlib import Path
        self._persist_path = Path(persist_path or os.getenv("EXECUTION_TRACES_PATH", "/app/data/execution_traces.jsonl"))
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:  # broad catch — resilience at boundary
            # Directory may not be available in test/restricted environments — persistence silently disabled
            pass

    def _persist(self, trace: WorkflowTrace) -> None:
        """Append trace to JSONL file for persistence across restarts."""
        try:
            import json
            with open(self._persist_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(trace.to_dict(), default=str) + "\n")
        except Exception as _exc:  # broad catch — resilience against all failures
            logger.debug("Failed to persist execution trace: %s", _exc)

    def record(self, trace: WorkflowTrace) -> None:
        """Record a completed trace (in-memory + file)."""
        with self._lock:
            self._traces.append(trace)
            self._by_category[trace.category].append(trace)
            key = f"{trace.category}:{trace.name}"
            self._counters[key] += 1
            if not trace.success:
                self._error_counters[key] += 1

        # Persist to file (survives restarts)
        self._persist(trace)

        # Feed to enterprise trackers (best-effort)
        self._feed_trackers(trace)

    def query(
        self,
        category: Optional[str] = None,
        name: Optional[str] = None,
        actor: Optional[str] = None,
        success: Optional[bool] = None,
        last_minutes: int = 60,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query traces with filtering."""
        datetime.now(timezone.utc).isoformat()  # Simplified — use all recent

        with self._lock:
            if category:
                source = list(self._by_category.get(category, []))
            else:
                source = list(self._traces)

        # Filter
        results = source
        if name:
            results = [t for t in results if name in t.name]
        if actor:
            results = [t for t in results if actor in t.actor]
        if success is not None:
            results = [t for t in results if t.success == success]

        # Most recent first
        results.reverse()
        return [t.to_dict() for t in results[:limit]]

    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics by category and name."""
        with self._lock:
            total = len(self._traces)
            by_cat: Dict[str, int] = {}
            for cat, traces in self._by_category.items():
                by_cat[cat] = len(traces)

        # Top executors
        top = sorted(self._counters.items(), key=lambda x: -x[1])[:20]
        # Top errors
        top_errors = sorted(self._error_counters.items(), key=lambda x: -x[1])[:10]

        return {
            "total_traces": total,
            "by_category": by_cat,
            "top_executions": [{"name": k, "count": v} for k, v in top],
            "top_errors": [{"name": k, "count": v} for k, v in top_errors],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_dashboard(self) -> Dict[str, Any]:
        """Get observability dashboard data."""
        with self._lock:
            recent = list(self._traces)

        # Last 100 traces
        recent_100 = recent[-100:]
        success_count = sum(1 for t in recent_100 if t.success)
        total = len(recent_100)

        # Per-category latency
        cat_latency: Dict[str, List[float]] = defaultdict(list)
        for t in recent_100:
            cat_latency[t.category].append(t.latency_ms)

        avg_latency = {}
        for cat, latencies in cat_latency.items():
            avg_latency[cat] = round(sum(latencies) / len(latencies), 1) if latencies else 0

        return {
            "recent_count": total,
            "success_rate": round(success_count / max(total, 1), 3),
            "avg_latency_by_category": avg_latency,
            "stats": self.get_stats(),
        }

    def _feed_trackers(self, trace: WorkflowTrace) -> None:
        """Feed trace data to enterprise tracking modules."""
        # Audit log
        try:
            from chat_app.audit_log import get_audit_log
            if trace.category in (ExecCategory.AGENT, ExecCategory.WORKFLOW) or not trace.success:
                get_audit_log().append(
                    event_type=f"exec_{trace.category}",
                    actor=trace.actor or "system",
                    action=trace.name,
                    target=trace.handler_key or trace.name,
                    details={
                        "success": trace.success,
                        "latency_ms": round(trace.latency_ms, 1),
                        "agent": trace.agent,
                        "intent": trace.intent,
                        "error": trace.error,
                    },
                    severity="low" if trace.success else "medium",
                )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        # Activity timeline
        try:
            from chat_app.activity_timeline import get_timeline
            get_timeline().record(
                event_type="tool_execution" if trace.category == ExecCategory.SKILL else trace.category,
                actor=trace.actor or "system",
                action=trace.name,
                target=trace.handler_key or trace.name,
                details={"latency_ms": round(trace.latency_ms, 1), "intent": trace.intent},
                status="ok" if trace.success else "error",
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        # SLO
        try:
            from chat_app.slo_tracker import get_slo_tracker
            slo = get_slo_tracker()
            if trace.category == ExecCategory.SKILL:
                slo.record("tool_success_rate", success=trace.success)
            elif trace.category == ExecCategory.COMMAND:
                slo.record("api_availability", success=trace.success)
            slo.record("system_availability", success=True)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        # Cost
        try:
            if trace.prompt_tokens or trace.completion_tokens:
                from chat_app.cost_tracker import get_cost_tracker
                get_cost_tracker().record(
                    model=trace.handler_key or "unknown",
                    purpose=trace.category,
                    input_tokens=trace.prompt_tokens,
                    output_tokens=trace.completion_tokens,
                    user_id=trace.actor,
                )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass


# ---------------------------------------------------------------------------
# Track execution — decorator + context manager
# ---------------------------------------------------------------------------

def _create_trace(category: str, name: str, actor: str = "", parent_id: str = "",
                  **kwargs) -> WorkflowTrace:
    return WorkflowTrace(
        trace_id=uuid.uuid4().hex[:12],
        parent_id=parent_id,
        category=category,
        name=name,
        actor=actor,
        started_at=datetime.now(timezone.utc).isoformat(),
        _start_mono=time.monotonic(),
        **kwargs,
    )


@asynccontextmanager
async def track_execution_ctx(category: str, name: str, actor: str = "",
                               parent_id: str = "", **kwargs):
    """Async context manager for tracking execution."""
    trace = _create_trace(category, name, actor, parent_id, **kwargs)
    try:
        yield trace
        if not trace.finished_at:
            trace.success = True
            trace.finish()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        trace.success = False
        trace.error = str(exc)
        trace.finish()
        raise
    finally:
        get_execution_store().record(trace)


def track_execution(category: str, name: str = "", actor_param: str = ""):
    """Decorator for tracking any async function execution.

    Usage:
        @track_execution(category="command", name="/search")
        async def search_command(args):
            ...
    """
    def decorator(fn: Callable):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            fn_name = name or fn.__name__
            fn_actor = ""
            if actor_param and actor_param in kwargs:
                fn_actor = str(kwargs[actor_param])

            trace = _create_trace(category, fn_name, fn_actor)
            try:
                result = await fn(*args, **kwargs)
                trace.success = True
                if result is not None:
                    trace.result_summary = str(result)[:200]
                return result
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                trace.success = False
                trace.error = str(exc)
                raise
            finally:
                trace.finish()
                get_execution_store().record(trace)

        return wrapper
    return decorator


def track_sync(category: str, name: str = ""):
    """Decorator for tracking synchronous function execution."""
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            fn_name = name or fn.__name__
            trace = _create_trace(category, fn_name)
            try:
                result = fn(*args, **kwargs)
                trace.success = True
                if result is not None:
                    trace.result_summary = str(result)[:200]
                return result
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                trace.success = False
                trace.error = str(exc)
                raise
            finally:
                trace.finish()
                get_execution_store().record(trace)

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store_instance: Optional[ExecutionStore] = None
_store_lock = threading.Lock()


def get_execution_store() -> ExecutionStore:
    """Get the global ExecutionStore singleton."""
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = ExecutionStore()
    return _store_instance
