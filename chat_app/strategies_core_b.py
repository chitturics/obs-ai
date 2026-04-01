"""
Core orchestration strategies (group B): strategies 7-12.

    7.  ReactStrategy          (medium)
    8.  ReviewCritiqueStrategy (medium)
    9.  WorkflowStrategy       (medium)
    10. SwarmStrategy          (heavy)
    11. HumanInLoopStrategy    (light)
    12. AdaptiveStrategy       (heavy)

Imported and re-exported by strategies_core.py.
AdaptiveStrategy depends on HierarchicalStrategy and SingleAgentStrategy
(imported from strategies_core_a).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from chat_app.orchestration_base import (
    OrchestrationResult,
    OrchestrationStrategy,
)
from chat_app.strategies_core_a import (
    SingleAgentStrategy,
    HierarchicalStrategy,
)

logger = logging.getLogger(__name__)


# Strategy 7: react (medium)
# ---------------------------------------------------------------------------

class ReactStrategy(OrchestrationStrategy):
    """Reason-action loop — wraps existing execute_react_loop."""

    name = "react"
    resource_weight = "medium"

    def is_applicable(self, intent: str, user_input: str) -> bool:
        try:
            from chat_app.react_loop import should_use_react
            return should_use_react(intent, user_input)
        except Exception as _exc:  # broad catch — resilience against all failures
            return False

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.react_loop import (
                execute_react_loop, format_tool_context_for_llm,
            )
            trace_obj = await execute_react_loop(user_input, intent)
            ctx = format_tool_context_for_llm(trace_obj)
            return OrchestrationResult(
                strategy_used=self.name,
                context=ctx or "",
                agent_trace=[{
                    "tools": trace_obj.tools_used,
                    "steps": len(trace_obj.steps),
                }],
                quality_score=1.0 if ctx else 0.0,
                duration_ms=(time.monotonic() - start) * 1000,
                success=bool(ctx),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:react] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 8: review_critique (medium)
# ---------------------------------------------------------------------------

class ReviewCritiqueStrategy(OrchestrationStrategy):
    """Worker generates, critic reviews, combined output returned."""

    name = "review_critique"
    resource_weight = "medium"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            from chat_app.agent_catalog import Department
            dispatcher = get_agent_dispatcher()

            worker_result = await dispatcher.dispatch(
                user_input, intent, user_approved=user_approved,
            )
            worker_output = worker_result.enriched_context or ""
            if not worker_output:
                return self._empty_result("Worker produced no output")

            critic_input = (
                f"Review this Splunk analysis for accuracy and completeness:\n\n"
                f"Original query: {user_input}\n\n"
                f"Analysis:\n{worker_output}\n\n"
                f"Provide specific critique and improvements."
            )
            critic_result = await dispatcher.dispatch(
                critic_input, "general_qa",
                preferred_department=Department.KNOWLEDGE,
                user_approved=user_approved,
            )
            critique = critic_result.enriched_context or ""

            if critique:
                final = (
                    f"### Initial Analysis\n{worker_output}\n\n"
                    f"### Expert Review\n{critique}"
                )
            else:
                final = worker_output

            trace = [worker_result.to_dict(), critic_result.to_dict()]
            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Review & Critique Analysis\n{final}",
                system_prompt_fragment=worker_result.system_prompt_fragment,
                agent_trace=trace,
                iterations=2,
                quality_score=1.0 if critique else 0.5,
                duration_ms=(time.monotonic() - start) * 1000,
                success=True,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:review_critique] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 9: workflow (medium)
# ---------------------------------------------------------------------------

class WorkflowStrategy(OrchestrationStrategy):
    """DAG-based multi-agent workflow — wraps existing WorkflowOrchestrator."""

    name = "workflow"
    resource_weight = "medium"

    def is_applicable(self, intent: str, user_input: str) -> bool:
        try:
            from chat_app.workflow_orchestrator import detect_workflow
            return detect_workflow(user_input, intent) is not None
        except Exception as _exc:  # broad catch — resilience against all failures
            return False

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.workflow_orchestrator import get_workflow_orchestrator
            orchestrator = get_workflow_orchestrator()
            wf_result = await orchestrator.run(
                user_input, intent, user_approved=user_approved,
            )
            if not wf_result:
                return self._empty_result("No applicable workflow template")

            ctx = (
                f"### Multi-Agent Workflow Results\n{wf_result.combined_output}"
                if wf_result.combined_output else ""
            )
            return OrchestrationResult(
                strategy_used=self.name,
                context=ctx,
                agent_trace=wf_result.agent_trace,
                quality_score=1.0 if wf_result.success else 0.3,
                duration_ms=(time.monotonic() - start) * 1000,
                success=wf_result.success,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:workflow] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 10: swarm (heavy)
# ---------------------------------------------------------------------------

class SwarmStrategy(OrchestrationStrategy):
    """Agents self-organize by handing off work based on output analysis."""

    name = "swarm"
    resource_weight = "heavy"

    HANDOFF_SIGNALS = {
        "spl": "spl_generation",
        "query": "spl_generation",
        "config": "config_lookup",
        "troubleshoot": "troubleshooting",
        "security": "security",
        "optimize": "spl_optimization",
    }

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            dispatcher = get_agent_dispatcher()

            current_input = user_input
            current_intent = intent
            all_outputs = []
            trace = []
            visited = set()
            max_iter = getattr(settings, "max_iterations", 3)

            for i in range(max_iter):
                if current_intent in visited:
                    break
                visited.add(current_intent)

                result = await dispatcher.dispatch(
                    current_input, current_intent, user_approved=user_approved,
                )
                output = result.enriched_context or ""
                trace.append({**result.to_dict(), "swarm_step": i + 1})

                if output:
                    all_outputs.append(f"### Step {i + 1} [{result.agent_role}]\n{output}")

                next_intent = self._detect_handoff(output, current_intent)
                if not next_intent:
                    break
                current_input = f"{user_input}\n\nPrevious analysis:\n{output}"
                current_intent = next_intent

            combined = "\n\n".join(all_outputs)
            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Swarm Analysis\n{combined}" if combined else "",
                agent_trace=trace,
                iterations=len(trace),
                quality_score=min(1.0, len(all_outputs) / max(max_iter, 1)),
                duration_ms=(time.monotonic() - start) * 1000,
                success=bool(all_outputs),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:swarm] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    def _detect_handoff(self, output: str, current_intent: str) -> Optional[str]:
        if not output:
            return None
        output_lower = output.lower()
        for keyword, target in self.HANDOFF_SIGNALS.items():
            if target != current_intent and keyword in output_lower:
                if f"need to {keyword}" in output_lower or f"should {keyword}" in output_lower:
                    return target
        return None


# ---------------------------------------------------------------------------
# Strategy 11: human_in_loop (light)
# ---------------------------------------------------------------------------

class HumanInLoopStrategy(OrchestrationStrategy):
    """Single agent with Chainlit approval checkpoint before execution."""

    name = "human_in_loop"
    resource_weight = "light"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            import chainlit as cl

            actions = [
                cl.Action(name="approve", label="Approve", value="approve",
                          description="Allow the agent to proceed"),
                cl.Action(name="deny", label="Deny", value="deny",
                          description="Cancel this action"),
            ]
            response = await cl.AskActionMessage(
                content=(
                    f"The agent wants to perform a **{intent}** action.\n\n"
                    f"Query: _{user_input}_\n\nApprove to continue?"
                ),
                actions=actions,
                timeout=60,
            ).send()

            if not response or response.get("value") == "deny":
                return OrchestrationResult(
                    strategy_used=self.name,
                    context="Action was denied by user.",
                    success=False,
                    error="User denied the action",
                    duration_ms=(time.monotonic() - start) * 1000,
                )

            result = await SingleAgentStrategy().execute(
                user_input, intent, plan, context, settings, user_approved=True,
            )
            result.strategy_used = self.name
            return result

        except ImportError:
            # Chainlit not installed (API mode) — fall back to single agent
            logger.info("[ORCH:human_in_loop] Chainlit unavailable, falling back to single_agent")
            result = await SingleAgentStrategy().execute(
                user_input, intent, plan, context, settings,
                user_approved=user_approved,
            )
            result.strategy_used = self.name
            return result
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            # Any other error (timeout, network, etc.) — deny for safety
            logger.warning("[ORCH:human_in_loop] Approval failed, denying for safety: %s", exc)
            return OrchestrationResult(
                strategy_used=self.name,
                context="Action denied — approval system encountered an error.",
                success=False,
                error=f"Approval error: {exc}",
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 12: adaptive (heavy) — THE CUSTOM DEFAULT
# ---------------------------------------------------------------------------

class AdaptiveStrategy(OrchestrationStrategy):
    """Hierarchical + review/critique + continuous improvement using idle resources."""

    name = "adaptive"
    resource_weight = "heavy"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            from chat_app.agent_catalog import Department
            from chat_app.self_evaluator import evaluate_response_quality
            from chat_app.resource_manager import can_run_heavy_task
            dispatcher = get_agent_dispatcher()

            max_iter = getattr(settings, "max_iterations", 3)
            threshold = getattr(settings, "quality_threshold", 0.7)
            budget = getattr(settings, "max_duration_seconds", 30.0)
            use_fallback = getattr(settings, "resource_fallback", True)

            # Phase 1: hierarchical decomposition + worker execution
            hier = HierarchicalStrategy()
            hier_result = await hier.execute(
                user_input, intent, plan, context, settings, user_approved,
            )
            current_context = hier_result.context
            trace = list(hier_result.agent_trace)
            iterations = 1

            if not current_context:
                return await SingleAgentStrategy().execute(
                    user_input, intent, plan, context, settings, user_approved,
                )

            # Phase 2: critic + improvement loop
            best_score = 0.0
            best_context = current_context
            feedback = ""

            for i in range(max_iter):
                if use_fallback:
                    allowed, reason = can_run_heavy_task()
                    if not allowed:
                        logger.info("[ADAPTIVE] Stopping: %s", reason)
                        break

                elapsed = time.monotonic() - start
                if elapsed >= budget * 0.8:
                    logger.info("[ADAPTIVE] Time budget approaching (%.1fs)", elapsed)
                    break

                # Critic evaluates
                critic_input = (
                    f"Evaluate this Splunk analysis for: {user_input}\n\n"
                    f"Current output:\n{current_context}\n\n"
                    f"{'Previous feedback: ' + feedback if feedback else ''}\n"
                    f"Identify specific gaps and improvements."
                )
                critic_result = await dispatcher.dispatch(
                    critic_input, "general_qa",
                    preferred_department=Department.KNOWLEDGE,
                    user_approved=user_approved,
                )
                critique = critic_result.enriched_context or ""
                trace.append({
                    **critic_result.to_dict(),
                    "role": "critic", "iteration": i + 1,
                })

                quality = evaluate_response_quality(
                    response=current_context, user_query=user_input,
                    context=user_input,
                    chunks_found=max(len(hier_result.agent_trace), 1),
                )

                if quality.overall > best_score:
                    best_score = quality.overall
                    best_context = current_context

                if quality.overall >= threshold:
                    logger.info("[ADAPTIVE] Quality met (%.2f)", quality.overall)
                    break

                if not critique:
                    break

                # Worker refines
                feedback = critique[:300]
                refine_input = (
                    f"{user_input}\n\n"
                    f"Incorporate this feedback into an improved response:\n{feedback}"
                )
                worker_result = await dispatcher.dispatch(
                    refine_input, intent, user_approved=user_approved,
                )
                if worker_result.success and worker_result.enriched_context:
                    current_context = (
                        f"{worker_result.enriched_context}\n\n"
                        f"### Critic Feedback Applied\n{critique}"
                    )
                    trace.append({
                        **worker_result.to_dict(),
                        "role": "worker", "iteration": i + 1,
                    })
                    iterations += 1

            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Adaptive Multi-Agent Analysis\n{best_context}",
                system_prompt_fragment=hier_result.system_prompt_fragment,
                agent_trace=trace,
                iterations=iterations,
                quality_score=best_score,
                duration_ms=(time.monotonic() - start) * 1000,
                success=True,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:adaptive] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )
