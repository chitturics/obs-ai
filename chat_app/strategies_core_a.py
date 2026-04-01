"""
Core orchestration strategies (group A): strategies 1-6.

    1. SingleAgentStrategy  (light)
    2. ParallelStrategy     (medium)
    3. HierarchicalStrategy (heavy)
    4. IterativeStrategy    (medium)
    5. CoordinatorStrategy  (heavy)
    6. VotingStrategy       (heavy)

Imported and re-exported by strategies_core.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Tuple

from chat_app.orchestration_base import (
    OrchestrationResult,
    OrchestrationStrategy,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategy 1: single_agent (light)
# ---------------------------------------------------------------------------

class SingleAgentStrategy(OrchestrationStrategy):
    """Single agent dispatch — wraps existing AgentDispatcher.

    In *fast_mode* (LLM_LITE profile / CPU-only), skill execution is skipped
    to avoid a redundant vector-search embedding call.  The agent personality
    and prompt fragment are still injected so the LLM adopts the right persona,
    but the expensive skill chain (which duplicates the main pipeline's
    retrieval step) is not run.
    """

    name = "single_agent"
    resource_weight = "light"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.settings import get_settings
            is_fast_mode = get_settings().fast_mode

            from chat_app.agent_dispatcher import (
                get_agent_dispatcher, format_agent_context_for_llm,
                AgentDispatchResult,
            )
            dispatcher = get_agent_dispatcher()

            if is_fast_mode:
                # ---- fast path: select agent persona only, skip skill execution ----
                agent = dispatcher.select_agent(intent, user_input)
                if agent:
                    prompt_fragment = agent.get_system_prompt_fragment()
                    result = AgentDispatchResult(
                        agent_name=agent.name,
                        agent_role=agent.role,
                        department=agent.department.value
                            if hasattr(agent.department, "value")
                            else str(agent.department),
                        system_prompt_fragment=prompt_fragment,
                        success=True,
                        duration_ms=(time.monotonic() - start) * 1000,
                    )
                else:
                    result = AgentDispatchResult(
                        agent_name="none", agent_role="none",
                        department="none", success=True,
                        duration_ms=(time.monotonic() - start) * 1000,
                    )
                logger.info("[ORCH:single_agent] fast_mode — agent=%s, skipped skill execution",
                            result.agent_name)
            else:
                # ---- normal path: full dispatch with skill execution ----
                result = await dispatcher.dispatch(
                    user_input, intent, user_approved=user_approved,
                )

            ctx = format_agent_context_for_llm(result)
            return OrchestrationResult(
                strategy_used=self.name,
                context=ctx or "",
                system_prompt_fragment=result.system_prompt_fragment,
                agent_trace=[result.to_dict()],
                quality_score=1.0 if result.success else 0.0,
                duration_ms=(time.monotonic() - start) * 1000,
                success=result.success,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:single_agent] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 2: parallel (medium)
# ---------------------------------------------------------------------------

class ParallelStrategy(OrchestrationStrategy):
    """Multiple agents work on the same query in parallel, outputs merged."""

    name = "parallel"
    resource_weight = "medium"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            from chat_app.agent_catalog import get_agent_catalog
            dispatcher = get_agent_dispatcher()
            catalog = get_agent_catalog()

            candidates = catalog.get_for_intent(intent)
            if not candidates:
                candidates = catalog.get_for_intent("general_qa")
            agent_limit = min(getattr(settings, "max_parallel_agents", 3), max(len(candidates), 1))
            selected_agents = candidates[:agent_limit] if candidates else []

            # Dispatch each candidate's department for diversity
            seen_departments = set()
            dispatch_tasks = []
            for agent in selected_agents:
                department = getattr(agent, "department", None)
                if department and department in seen_departments:
                    department = None  # Let dispatcher pick if duplicate department
                if department:
                    seen_departments.add(department)
                dispatch_tasks.append(
                    dispatcher.dispatch(user_input, intent,
                                        user_approved=user_approved,
                                        preferred_department=department)
                )
            if not dispatch_tasks:
                dispatch_tasks = [dispatcher.dispatch(user_input, intent,
                                             user_approved=user_approved)]
            dispatch_results = await asyncio.gather(*dispatch_tasks, return_exceptions=True)

            context_parts, agent_trace = [], []
            for result in dispatch_results:
                if isinstance(result, Exception) or not result.success:
                    continue
                if result.enriched_context:
                    context_parts.append(f"### [{result.agent_role}]\n{result.enriched_context}")
                    agent_trace.append(result.to_dict())

            prompt_fragment = next(
                (result.system_prompt_fragment for result in dispatch_results
                 if not isinstance(result, Exception) and result.system_prompt_fragment),
                "",
            )
            merged_context = "\n\n---\n\n".join(context_parts)
            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Parallel Agent Analysis\n{merged_context}" if merged_context else "",
                system_prompt_fragment=prompt_fragment,
                agent_trace=agent_trace,
                quality_score=min(1.0, len(context_parts) / max(agent_limit, 1)),
                duration_ms=(time.monotonic() - start) * 1000,
                success=bool(context_parts),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:parallel] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 3: hierarchical (heavy)
# ---------------------------------------------------------------------------

class HierarchicalStrategy(OrchestrationStrategy):
    """Coordinator decomposes query into subtasks, each dispatched to best agent."""

    name = "hierarchical"
    resource_weight = "heavy"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            dispatcher = get_agent_dispatcher()

            subtasks = await self._decompose(user_input, intent, context)
            if not subtasks:
                return await SingleAgentStrategy().execute(
                    user_input, intent, plan, context, settings, user_approved,
                )

            context_parts, agent_trace = [], []
            for subtask in subtasks:
                result = await dispatcher.dispatch(
                    subtask["input"], subtask.get("intent", intent),
                    user_approved=user_approved,
                )
                if result.success and result.enriched_context:
                    context_parts.append(
                        f"### {subtask['description']}\n{result.enriched_context}"
                    )
                    agent_trace.append({**result.to_dict(), "subtask": subtask["description"]})

            combined_context = "\n\n".join(context_parts)
            coordinator_prompt = ""
            try:
                coordinator = dispatcher.select_agent("coordination", user_input)
                if coordinator:
                    coordinator_prompt = coordinator.get_system_prompt_fragment()
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)  # was: pass

            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Hierarchical Task Decomposition\n{combined_context}" if combined_context else "",
                system_prompt_fragment=coordinator_prompt,
                agent_trace=agent_trace,
                quality_score=min(1.0, len(context_parts) / max(len(subtasks), 1)),
                duration_ms=(time.monotonic() - start) * 1000,
                success=bool(context_parts),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:hierarchical] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def _decompose(self, user_input: str, intent: str,
                         context: Any) -> List[Dict[str, Any]]:
        try:
            if hasattr(context, "chain") and context.chain:
                prompt = (
                    "Break this query into 2-4 independent subtasks for Splunk experts.\n"
                    f"Query: {user_input}\n"
                    "Return each subtask on a new line starting with '- '."
                )
                raw = await context.chain.ainvoke({"input": prompt})
                raw_str = str(raw) if not isinstance(raw, str) else raw
                lines = [
                    ln.lstrip("- ").strip()
                    for ln in raw_str.strip().splitlines()
                    if ln.strip().startswith("-")
                ]
                if lines:
                    return [
                        {"description": ln,
                         "input": f"{ln} (context: {user_input[:80]})",
                         "intent": intent}
                        for ln in lines[:4]
                    ]
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[HIERARCHICAL] LLM decomposition failed: %s", exc)

        return [
            {"description": "Analyze the query context",
             "input": user_input, "intent": "general_qa"},
            {"description": "Generate comprehensive response",
             "input": user_input, "intent": intent},
        ]


# ---------------------------------------------------------------------------
# Strategy 4: iterative (medium)
# ---------------------------------------------------------------------------

class IterativeStrategy(OrchestrationStrategy):
    """Agent refines response through multiple passes until quality threshold."""

    name = "iterative"
    resource_weight = "medium"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.agent_dispatcher import (
                get_agent_dispatcher, format_agent_context_for_llm,
            )
            from chat_app.self_evaluator import evaluate_response_quality
            dispatcher = get_agent_dispatcher()

            best_result = None
            best_score = 0.0
            trace = []
            feedback = ""
            max_iter = getattr(settings, "max_iterations", 3)
            threshold = getattr(settings, "quality_threshold", 0.7)

            for i in range(max_iter):
                enhanced_input = (
                    f"{user_input}\n\nPrevious attempt feedback: {feedback}"
                    if feedback else user_input
                )
                result = await dispatcher.dispatch(
                    enhanced_input, intent, user_approved=user_approved,
                )
                output = result.enriched_context or ""

                quality = evaluate_response_quality(
                    response=output, user_query=user_input,
                    context=user_input, chunks_found=1,
                )
                trace.append({
                    **result.to_dict(), "iteration": i + 1,
                    "quality": round(quality.overall, 3),
                })

                if quality.overall > best_score:
                    best_score = quality.overall
                    best_result = result

                if quality.overall >= threshold:
                    break
                feedback = "; ".join(quality.gaps[:2]) if quality.gaps else "improve completeness"

            if not best_result:
                return self._empty_result("All iterations failed")

            ctx = format_agent_context_for_llm(best_result)
            return OrchestrationResult(
                strategy_used=self.name,
                context=ctx or "",
                system_prompt_fragment=best_result.system_prompt_fragment,
                agent_trace=trace,
                iterations=len(trace),
                quality_score=best_score,
                duration_ms=(time.monotonic() - start) * 1000,
                success=best_result.success,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:iterative] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 5: coordinator (heavy)
# ---------------------------------------------------------------------------

class CoordinatorStrategy(OrchestrationStrategy):
    """Hierarchical decomposition + coordinator reviews aggregated result."""

    name = "coordinator"
    resource_weight = "heavy"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            hier_result = await HierarchicalStrategy().execute(
                user_input, intent, plan, context, settings, user_approved,
            )
            if not hier_result.success or not hier_result.context:
                return hier_result

            from chat_app.agent_dispatcher import get_agent_dispatcher
            from chat_app.agent_catalog import Department
            dispatcher = get_agent_dispatcher()

            review_result = await dispatcher.dispatch(
                f"Review and synthesize this analysis for: {user_input}\n\n"
                f"{hier_result.context}",
                "general_qa",
                preferred_department=Department.MANAGEMENT,
                user_approved=user_approved,
            )

            final_ctx = hier_result.context
            if review_result.success and review_result.enriched_context:
                final_ctx += f"\n\n### Coordinator Synthesis\n{review_result.enriched_context}"

            trace = hier_result.agent_trace + (
                [review_result.to_dict()] if review_result.success else []
            )
            return OrchestrationResult(
                strategy_used=self.name,
                context=final_ctx,
                system_prompt_fragment=(
                    review_result.system_prompt_fragment
                    or hier_result.system_prompt_fragment
                ),
                agent_trace=trace,
                quality_score=hier_result.quality_score,
                duration_ms=(time.monotonic() - start) * 1000,
                success=True,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:coordinator] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 6: voting (heavy)
# ---------------------------------------------------------------------------

class VotingStrategy(OrchestrationStrategy):
    """Multiple agents generate independently, best-scoring one selected."""

    name = "voting"
    resource_weight = "heavy"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.agent_dispatcher import (
                get_agent_dispatcher, format_agent_context_for_llm,
            )
            from chat_app.self_evaluator import evaluate_response_quality
            dispatcher = get_agent_dispatcher()

            voter_count = min(getattr(settings, "max_parallel_agents", 3), 3)
            # Use different agent candidates for diversity (skip_top_n ensures different agents)
            vote_tasks = [
                dispatcher.dispatch(user_input, intent, user_approved=user_approved,
                                    skip_top_n=i)
                for i in range(voter_count)
            ]
            vote_results = await asyncio.gather(*vote_tasks, return_exceptions=True)

            scored_candidates: List[Tuple[float, Any]] = []
            agent_trace = []
            for result in vote_results:
                if isinstance(result, Exception) or not result.success:
                    continue
                output = result.enriched_context or ""
                quality = evaluate_response_quality(
                    response=output, user_query=user_input,
                    context=output, chunks_found=len(result.skill_results),
                )
                scored_candidates.append((quality.overall, result))
                agent_trace.append({**result.to_dict(), "vote_score": round(quality.overall, 3)})

            if not scored_candidates:
                return self._empty_result("All voters failed")

            winning_score, winning_agent = max(scored_candidates, key=lambda x: x[0])
            winner_context = format_agent_context_for_llm(winning_agent)
            return OrchestrationResult(
                strategy_used=self.name,
                context=winner_context or "",
                system_prompt_fragment=winning_agent.system_prompt_fragment,
                agent_trace=agent_trace,
                iterations=voter_count,
                quality_score=winning_score,
                duration_ms=(time.monotonic() - start) * 1000,
                success=True,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:voting] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
