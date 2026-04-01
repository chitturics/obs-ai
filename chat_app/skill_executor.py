"""
Skill Executor — Bridges SkillCatalog handler_keys to actual execution.

This is the critical missing layer that makes skills REAL:
- Maps handler_key strings to executable functions
- Routes to ToolRegistry tools, SkillsManager actions, or internal modules
- Provides a unified execute() interface for any skill
- Tracks execution metrics and supports approval gates

The handler_key resolution order:
1. ToolRegistry built-in tools (analyze_spl, optimize_spl, etc.)
2. SkillsManager loaded actions (from skills/ packages)
3. Internal module functions (direct Python callables)
4. ReAct loop (for complex multi-step reasoning)

Handler registration and alias mapping live in skill_executor_dispatch.py.
"""
import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

from chat_app.skill_catalog import (
    ApprovalGate,
    SkillCatalog,
    get_skill_catalog,
)
from chat_app.tool_registry import (
    ToolRegistry,
    get_tool_registry,
)

logger = logging.getLogger(__name__)

try:
    from chat_app.logging_utils import structured_log as _structured_log
except ImportError:
    def _structured_log(lg, level, tag, msg, **kw):  # type: ignore
        lg.log(level, "[%s] %s %s", tag, msg, kw)


def _run_async(coro):
    """Run an async coroutine from sync context, safely handling running event loops."""
    import concurrent.futures
    try:
        asyncio.get_running_loop()
        # Already inside a running loop — run in a new thread with its own loop
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=30)
    except RuntimeError:
        # No running loop — safe to use asyncio.run directly
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------

@dataclass
class SkillExecResult:
    """Unified result from executing any skill."""
    success: bool
    output: str
    skill_name: str = ""
    handler_key: str = ""
    data: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    approval_required: bool = False
    approval_message: str = ""
    source: str = ""  # "tool_registry", "skills_manager", "internal", "react_loop"

    def format_for_context(self) -> str:
        """Format for LLM context injection."""
        if not self.success:
            return f"[Skill Error: {self.skill_name}] {self.error or 'Unknown error'}"
        return self.output


# ---------------------------------------------------------------------------
# Internal handler registry — maps handler_keys to Python callables
# ---------------------------------------------------------------------------

_INTERNAL_HANDLERS: Dict[str, Callable] = {}


def register_internal_handler(handler_key: str, fn: Callable):
    """Register a Python callable as an internal handler for a handler_key."""
    _INTERNAL_HANDLERS[handler_key] = fn
    logger.debug(f"[SKILL_EXEC] Registered internal handler: {handler_key}")


def get_internal_handler(handler_key: str) -> Optional[Callable]:
    """Get a registered internal handler."""
    return _INTERNAL_HANDLERS.get(handler_key)


# ---------------------------------------------------------------------------
# Built-in handler bootstrap — delegates to skill_executor_dispatch
# ---------------------------------------------------------------------------

from chat_app.skill_executor_dispatch import (  # noqa: E402
    _SKILL_FALLBACKS,
    register_builtin_internal_handlers as _register_dispatch_handlers,
)


def _register_builtin_internal_handlers():
    """Register all built-in internal handlers from handler modules."""
    _register_dispatch_handlers(register_internal_handler)


# ---------------------------------------------------------------------------
# Skill Executor
# ---------------------------------------------------------------------------

class SkillExecutor:
    """
    Unified execution layer for all skills.

    Resolves handler_key to the appropriate execution backend:
    1. ToolRegistry (built-in tools with execute_fn)
    2. SkillsManager (loaded skill packages from skills/ directory)
    3. Internal handlers (Python callables registered at startup)
    4. ReAct loop (for multi-step reasoning skills)
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        skills_manager=None,
        skill_catalog: Optional[SkillCatalog] = None,
    ):
        self._tool_registry = tool_registry or get_tool_registry()
        self._skills_manager = skills_manager
        self._skill_catalog = skill_catalog or get_skill_catalog()
        self._capabilities: Set[str] = set()

        # Ensure builtin internal handlers are registered
        if not _INTERNAL_HANDLERS:
            _register_builtin_internal_handlers()

        # Execution metrics
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._execution_log: List[Dict[str, Any]] = []

    def set_capabilities(self, capabilities: Set[str]):
        """Set available system capabilities."""
        self._capabilities = capabilities

    def resolve_handler(self, handler_key: str) -> tuple:
        """
        Resolve a handler_key to its execution backend.

        Returns: (source, handler_or_name)
            source: "tool_registry" | "skills_manager" | "internal" | "react_loop" | None
            handler_or_name: The tool name, action name, or callable
        """
        if not handler_key:
            return (None, None)

        # 1. Check ToolRegistry (built-in tools)
        tool = self._tool_registry.get_tool(handler_key)
        if tool and tool.execute_fn:
            return ("tool_registry", handler_key)

        # 2. Check SkillsManager (loaded skill packages)
        if self._skills_manager:
            if handler_key in self._skills_manager._action_registry:
                return ("skills_manager", handler_key)

        # 3. Check internal handlers
        internal = get_internal_handler(handler_key)
        if internal:
            return ("internal", handler_key)

        # 4. Special case: ReAct loop
        if handler_key in ("react_loop", "deep_analysis", "reason"):
            return ("react_loop", handler_key)

        return (None, None)

    async def execute(
        self,
        skill_name: str = "",
        handler_key: str = "",
        params: Dict[str, Any] = None,
        user_approved: bool = False,
        max_retries: int = 1,
    ) -> SkillExecResult:
        """
        Execute a skill by name or handler_key.

        Args:
            skill_name: Skill name from the catalog (looked up to get handler_key)
            handler_key: Direct handler_key (skips catalog lookup)
            params: Execution parameters
            user_approved: Whether user has approved (for approval-gated skills)
            max_retries: Number of retry attempts before falling through to fallback (default 1).
                         On each retry, waits 0.5s with backoff.

        Returns:
            SkillExecResult with execution output
        """
        params = params or {}
        start = time.monotonic()

        _structured_log(logger, logging.DEBUG, "SKILL", "exec_start",
                        skill=skill_name or handler_key, handler_key=handler_key or skill_name)

        # Enrich params with KG context (best-effort)
        try:
            from chat_app.knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            if kg and params.get("input"):
                kg_context = kg.generate_context_for_query(
                    params["input"], params.get("intent", "")
                )
                if kg_context:
                    params["kg_context"] = kg_context
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[SKILL] Optional operation failed: %s", _exc)

        # Resolve the skill
        skill = None
        if skill_name:
            skill = self._skill_catalog.get(skill_name)
            if skill:
                handler_key = handler_key or skill.handler_key
            else:
                # skill_name might itself be a handler_key (e.g. frontend sends handler_key as skill_name)
                handler_key = handler_key or skill_name

        if not handler_key:
            result = SkillExecResult(
                success=False, output="",
                skill_name=skill_name,
                handler_key="",
                error=f"No handler_key for skill: {skill_name or '(none)'}",
                duration_ms=(time.monotonic() - start) * 1000,
            )
            self._record_execution(result)
            return result

        # Check approval gate
        if skill and skill.approval in (ApprovalGate.CONFIRM, ApprovalGate.REVIEW) and not user_approved:
            result = SkillExecResult(
                success=False, output="",
                skill_name=skill.name if skill else "",
                handler_key=handler_key,
                approval_required=True,
                approval_message=(
                    f"Skill '{skill.display_name}' requires "
                    f"{'confirmation' if skill.approval == ApprovalGate.CONFIRM else 'admin review'} "
                    f"before execution."
                ),
                duration_ms=(time.monotonic() - start) * 1000,
            )
            self._record_execution(result)
            return result

        # Check capability requirements
        if skill and skill.requires and not skill.requires.issubset(self._capabilities):
            missing = skill.requires - self._capabilities
            result = SkillExecResult(
                success=False, output="",
                skill_name=skill.name if skill else "",
                handler_key=handler_key,
                error=f"Missing capabilities: {', '.join(missing)}",
                duration_ms=(time.monotonic() - start) * 1000,
            )
            self._record_execution(result)
            return result

        # --- min_role enforcement ---
        _ROLE_HIERARCHY = {"VIEWER": 0, "USER": 1, "ANALYST": 2, "ADMIN": 3}
        if skill and skill.min_role:
            user_role = params.get("user_role", "USER")
            user_level = _ROLE_HIERARCHY.get(user_role, 1)
            required_level = _ROLE_HIERARCHY.get(skill.min_role, 1)
            if user_level < required_level:
                result = SkillExecResult(
                    success=False, output="",
                    skill_name=skill.name,
                    handler_key=handler_key,
                    error=(
                        f"Access denied: skill '{skill.display_name}' requires "
                        f"role {skill.min_role} (level {required_level}), "
                        f"but your role is {user_role} (level {user_level})"
                    ),
                    duration_ms=(time.monotonic() - start) * 1000,
                )
                self._record_execution(result)
                return result

        # --- Enterprise: Circuit breaker check ---
        try:
            from chat_app.circuit_breaker import get_circuit_breaker_registry
            if not get_circuit_breaker_registry().allow_request(handler_key):
                result = SkillExecResult(
                    success=False, output="",
                    skill_name=skill.name if skill else "",
                    handler_key=handler_key,
                    error=f"Circuit breaker OPEN for '{handler_key}' — tool temporarily disabled due to repeated failures",
                    duration_ms=(time.monotonic() - start) * 1000,
                )
                self._record_execution(result)
                return result
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[SKILL] Circuit breaker check failed (proceeding without): %s", exc)

        # --- Enterprise: Safety policy check ---
        try:
            from chat_app.safety_policies import evaluate_policy, PolicyAction
            env = os.environ.get("DEPLOYMENT_ENV", "development")
            user_role = params.get("user_role", "USER")
            decision = evaluate_policy(handler_key, user_role=user_role, environment=env,
                                       is_approved=user_approved, is_dry_run=params.get("dry_run", False))
            if decision.action == PolicyAction.DENY:
                result = SkillExecResult(
                    success=False, output="",
                    skill_name=skill.name if skill else "",
                    handler_key=handler_key,
                    error=f"Safety policy DENIED: {decision.reason}",
                    duration_ms=(time.monotonic() - start) * 1000,
                )
                self._record_execution(result)
                return result
            if decision.action == PolicyAction.REQUIRE_APPROVAL and not user_approved:
                result = SkillExecResult(
                    success=False, output="",
                    skill_name=skill.name if skill else "",
                    handler_key=handler_key,
                    approval_required=True,
                    approval_message=f"Safety policy requires approval: {decision.reason}",
                    duration_ms=(time.monotonic() - start) * 1000,
                )
                self._record_execution(result)
                return result
        except ImportError:
            logger.info("[SKILL] Safety policies module not available — proceeding without safety checks")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[SKILL] Safety policy check skipped: %s", exc)

        # --- Enterprise: Create execution trace early (before resolve) ---
        _exec_trace = None
        try:
            from chat_app.execution_tracker import _create_trace, get_execution_store, ExecCategory
            _exec_trace = _create_trace(
                ExecCategory.SKILL, skill.name if skill else (skill_name or handler_key),
                actor=params.get("username", ""),
                handler_key=handler_key,
                intent=params.get("intent", ""),
                persona=params.get("user_persona", ""),
                input_preview=str(params.get("input", ""))[:100],
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[SKILL] Execution trace creation failed: %s", exc)

        # Resolve and execute
        source, resolved = self.resolve_handler(handler_key)

        if source is None:
            result = SkillExecResult(
                success=False, output="",
                skill_name=skill.name if skill else "",
                handler_key=handler_key,
                error=f"Handler not found: {handler_key}",
                duration_ms=(time.monotonic() - start) * 1000,
            )
            self._record_execution(result)
            if _exec_trace:
                _exec_trace.success = False
                _exec_trace.error = result.error
                _exec_trace.latency_ms = result.duration_ms
                _exec_trace.finish()
                try:
                    get_execution_store().record(_exec_trace)
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                    logger.debug("[SKILL] Execution trace recording failed: %s", exc)
            return result

        # Try execution with retry before falling through to fallback
        last_result = None
        last_exc = None

        if _exec_trace:
            _exec_trace.handler_source = source

        for attempt in range(max_retries + 1):
            try:
                result = await self._dispatch(source, resolved, params)
                duration_ms = (time.monotonic() - start) * 1000
                result.skill_name = skill.name if skill else skill_name
                result.handler_key = handler_key
                result.source = source
                result.duration_ms = duration_ms
                result._intent = params.get("intent")  # type: ignore[attr-defined]

                if result.success or result.approval_required:
                    self._record_execution(result)
                    _structured_log(logger, logging.DEBUG, "SKILL", "exec_end",
                                    handler_key=handler_key, duration_ms=round(duration_ms, 1),
                                    success=result.success, source=source)
                    if _exec_trace:
                        _exec_trace.success = result.success
                        _exec_trace.latency_ms = duration_ms
                        _exec_trace.result_summary = str(result.output)[:200] if result.output else ""
                        _exec_trace.finish()
                        get_execution_store().record(_exec_trace)
                    return result

                last_result = result
                last_exc = None
                if attempt < max_retries:
                    logger.warning("[SKILL] Retry %d/%d for %s: dispatch returned failure", attempt + 1, max_retries, skill_name or handler_key)
                    await asyncio.sleep(0.5)
                    continue
                break

            except Exception as exc:  # Broad catch intentional: _dispatch() calls arbitrary plugin handlers
                last_exc = exc
                last_result = None
                if attempt < max_retries:
                    logger.warning("[SKILL] Retry %d/%d for %s: %s", attempt + 1, max_retries, skill_name or handler_key, exc)
                    await asyncio.sleep(0.5)
                    continue
                break

        # All retries exhausted — try fallback skill if defined
        fallback_key = _SKILL_FALLBACKS.get(handler_key)
        if fallback_key:
            if last_exc:
                logger.info("[SKILL] %s raised %s after %d attempt(s), trying fallback: %s", handler_key, type(last_exc).__name__, max_retries + 1, fallback_key)
            else:
                logger.info("[SKILL] %s failed after %d attempt(s), trying fallback: %s", handler_key, max_retries + 1, fallback_key)
            fb_source, fb_resolved = self.resolve_handler(fallback_key)
            if fb_source is not None:
                try:
                    fb_result = await self._dispatch(fb_source, fb_resolved, params)
                    fb_result.skill_name = skill.name if skill else skill_name
                    fb_result.handler_key = fallback_key
                    fb_result.source = fb_source
                    fb_result.duration_ms = (time.monotonic() - start) * 1000
                    self._record_execution(fb_result)
                    return fb_result
                except Exception as _exc:  # Broad catch intentional: fallback handler may raise any type
                    logger.debug("[SKILL] Optional operation failed: %s", _exc)

        # Return the last failure result or build one from the exception
        if last_result is not None:
            self._record_execution(last_result)
            if _exec_trace:
                _exec_trace.success = False
                _exec_trace.error = last_result.error
                _exec_trace.latency_ms = last_result.duration_ms
                _exec_trace.finish()
                try:
                    get_execution_store().record(_exec_trace)
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                    logger.debug("[SKILL] Execution trace recording failed: %s", exc)
            return last_result

        duration_ms = (time.monotonic() - start) * 1000
        result = SkillExecResult(
            success=False, output="",
            skill_name=skill.name if skill else skill_name,
            handler_key=handler_key,
            source=source,
            error=str(last_exc),
            duration_ms=duration_ms,
        )
        self._record_execution(result)
        if _exec_trace:
            _exec_trace.success = False
            _exec_trace.error = str(last_exc)
            _exec_trace.latency_ms = duration_ms
            _exec_trace.finish()
            try:
                get_execution_store().record(_exec_trace)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.debug("[SKILL] Execution trace recording failed: %s", exc)
        return result

    async def _dispatch(
        self, source: str, handler_key: str, params: Dict[str, Any]
    ) -> SkillExecResult:
        """Dispatch execution to the appropriate backend. Implementation in skill_executor_impl."""
        from chat_app.skill_executor_impl import dispatch_skill
        return await dispatch_skill(self, source, handler_key, params)

    async def _execute_react(self, params: Dict[str, Any]) -> SkillExecResult:
        """Execute via the ReAct reasoning loop. Implementation in skill_executor_impl."""
        from chat_app.skill_executor_impl import execute_react
        return await execute_react(self, params)

    def _record_execution(self, result: SkillExecResult):
        """Record execution metrics. Implementation in skill_executor_impl."""
        from chat_app.skill_executor_impl import record_skill_execution
        record_skill_execution(self, result)

    def execute_batch(
        self, skill_names: List[str], params_list: List[Dict[str, Any]] = None
    ):
        """Execute multiple skills concurrently. Returns list of results."""
        params_list = params_list or [{}] * len(skill_names)

        async def _run():
            tasks = [
                self.execute(skill_name=name, params=params)
                for name, params in zip(skill_names, params_list)
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)

        return _run_async(_run())

    def get_available_skills(self) -> List[Dict[str, Any]]:
        """Get all skills that can actually be executed (handler resolves)."""
        available = []
        for skill in self._skill_catalog.get_enabled():
            source, _ = self.resolve_handler(skill.handler_key)
            if source:
                available.append({
                    "name": skill.name,
                    "action": skill.action,
                    "handler_key": skill.handler_key,
                    "source": source,
                    "family": skill.family.value,
                    "approval": skill.approval.value,
                })
        return available

    def get_skills_for_intent(self, intent: str) -> List[Dict[str, Any]]:
        """Get executable skills for a specific intent."""
        skills = self._skill_catalog.get_for_intent(intent)
        available = []
        for skill in skills:
            source, _ = self.resolve_handler(skill.handler_key)
            if source:
                available.append({
                    "name": skill.name,
                    "action": skill.action,
                    "handler_key": skill.handler_key,
                    "source": source,
                })
        return available

    def get_metrics(self) -> Dict[str, Any]:
        """Get execution metrics."""
        return {
            "total_executions": self._execution_count,
            "total_errors": self._error_count,
            "error_rate": round(
                self._error_count / max(self._execution_count, 1), 4
            ),
            "avg_latency_ms": round(
                self._total_latency_ms / max(self._execution_count, 1), 2
            ),
            "available_skills": len(self.get_available_skills()),
            "total_catalog_skills": self._skill_catalog.count,
        }

    def get_execution_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent execution log."""
        return self._execution_log[-limit:]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_executor: Optional[SkillExecutor] = None


def get_skill_executor(
    skills_manager=None,
) -> SkillExecutor:
    """Get or create the singleton SkillExecutor.

    If no *skills_manager* is supplied on the first call, we auto-discover
    and load skill packages from the ``skills/`` directory via
    :class:`chat_app.skills_manager.SkillsManager`.
    """
    global _executor
    if _executor is None:
        if skills_manager is None:
            try:
                from chat_app.skills_manager import get_skills_manager
                skills_manager = get_skills_manager()
                # Discover and install skill packages so actions are registered
                manifests = skills_manager.discover_skills()
                for manifest in manifests:
                    try:
                        skills_manager.install_skill(manifest.name)
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as install_exc:
                        logger.debug(
                            "[SKILL_EXEC] Could not install skill '%s': %s",
                            manifest.name, install_exc,
                        )
                logger.info(
                    "[SKILL_EXEC] Auto-loaded SkillsManager with %d actions from %d packages",
                    len(skills_manager._action_registry),
                    len(manifests),
                )
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.warning("[SKILL_EXEC] Could not load SkillsManager: %s", exc)
        _executor = SkillExecutor(skills_manager=skills_manager)
    return _executor
