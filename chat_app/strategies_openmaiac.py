"""
OpenMAIC-inspired orchestration strategies.

Extracted from orchestration_strategies.py to keep file sizes manageable.
These classes are re-exported from orchestration_strategies.py for backward
compatibility — all existing imports continue to work unchanged.

Strategies:
    TwoStagePipelineStrategy  — plan phase + sequential execution phase
    ActionEngineStrategy      — typed actions with state machine execution
    DirectorGraphStrategy     — DAG orchestration with conditional routing
    FeedbackLoopStrategy      — multi-turn self-critique and refinement
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from chat_app.orchestration_base import (
    OrchestrationResult,
    OrchestrationStrategy,
)

logger = logging.getLogger(__name__)


class TwoStagePipelineStrategy(OrchestrationStrategy):
    """Two-stage pipeline: plan phase generates outline, execute phase fills it."""

    name = "two_stage_pipeline"
    resource_weight = "medium"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.agent_dispatcher import (
                get_agent_dispatcher, format_agent_context_for_llm,
            )

            # Phase 1: Plan — decompose query into steps
            steps = await self._plan_phase(user_input, intent)
            if not steps:
                # Fallback to single dispatch
                dispatcher = get_agent_dispatcher()
                result = await dispatcher.dispatch(user_input, intent,
                                                   user_approved=user_approved)
                ctx = format_agent_context_for_llm(result)
                return OrchestrationResult(
                    strategy_used=self.name, context=ctx or "",
                    system_prompt_fragment=result.system_prompt_fragment,
                    agent_trace=[result.to_dict()], iterations=1,
                    quality_score=1.0 if result.success else 0.0,
                    duration_ms=(time.monotonic() - start) * 1000,
                    success=result.success,
                )

            # Phase 2: Execute — dispatch each step sequentially
            context_parts = []
            trace = []
            dispatcher = get_agent_dispatcher()

            for i, step in enumerate(steps[:getattr(settings, "max_iterations", 3)]):
                step_desc = step.get("description", user_input)
                dept_hint = step.get("department")

                try:
                    from chat_app.agent_catalog import Department
                    preferred_department = Department(dept_hint) if dept_hint else None
                except (ValueError, ImportError):
                    preferred_department = None

                result = await dispatcher.dispatch(
                    user_input=step_desc, intent=intent,
                    preferred_department=preferred_department,
                    user_approved=user_approved,
                )
                if result.success and result.enriched_context:
                    context_parts.append(
                        f"### Step {i+1}: {step_desc}\n{result.enriched_context}"
                    )
                    trace.append(result.to_dict())

            merged = "\n\n---\n\n".join(context_parts) if context_parts else ""
            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Two-Stage Pipeline Analysis\n{merged}" if merged else "",
                agent_trace=trace,
                iterations=len(trace),
                quality_score=len(trace) / max(len(steps), 1),
                duration_ms=(time.monotonic() - start) * 1000,
                success=bool(context_parts),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:two_stage_pipeline] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def _plan_phase(self, user_input: str, intent: str) -> List[Dict]:
        """Use LLM to decompose query into execution steps."""
        try:
            from chat_app.llm_utils import generate_text  # type: ignore[attr-defined]
            prompt = (
                f"Break this query into 2-3 execution steps. "
                f"For each step, give: description, department (engineering/operations/data/security/knowledge).\n"
                f"Query: {user_input}\n"
                f"Intent: {intent}\n\n"
                f"Reply in this exact format, one step per line:\n"
                f"1. [description] | [department]\n"
                f"2. [description] | [department]\n"
            )
            result = await generate_text(prompt, max_tokens=200)
            steps = []
            for line in result.strip().split("\n"):
                line = line.strip()
                if not line or not line[0].isdigit():
                    continue
                parts = line.split("|")
                desc = parts[0].strip().lstrip("0123456789.) ")
                dept = parts[1].strip() if len(parts) > 1 else "engineering"
                steps.append({"description": desc, "department": dept})
            return steps
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[ORCH:two_stage] Plan phase failed: %s", exc)
            return []


class ActionEngineStrategy(OrchestrationStrategy):
    """Action engine: typed actions with state machine execution."""

    name = "action_engine"
    resource_weight = "medium"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.action_engine import (
                ActionEngine, ActionType, build_plan_from_steps,
            )

            # Generate action plan from query
            steps = await self._generate_action_plan(user_input, intent)
            if not steps:
                # Default: simple retrieve + analyze
                steps = [
                    {"action_type": "retrieve", "description": user_input},
                    {"action_type": "analyze", "description": f"Analyze: {user_input}"},
                ]

            action_plan = build_plan_from_steps(steps)
            engine = ActionEngine(
                max_actions=15,
                timeout_per_action=getattr(settings, "max_duration_seconds", 30) / 3,
            )
            result_plan = await engine.execute_plan(action_plan, context)
            output = engine.get_accumulated_output(result_plan)

            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Action Engine Analysis\n{output}" if output else "",
                agent_trace=[a.to_dict() for a in result_plan.actions],
                iterations=len(result_plan.actions),
                quality_score=result_plan.success_count() / max(len(result_plan.actions), 1),
                duration_ms=(time.monotonic() - start) * 1000,
                success=result_plan.state == "completed",
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:action_engine] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def _generate_action_plan(self, user_input: str, intent: str) -> List[Dict]:
        """Use LLM to generate typed action steps."""
        action_types = "retrieve, generate_spl, analyze, validate, transform, explain, optimize, execute_search, compare, summarize"
        try:
            from chat_app.llm_utils import generate_text  # type: ignore[attr-defined]
            prompt = (
                f"Plan actions for this query. Available action types: {action_types}\n"
                f"Query: {user_input}\nIntent: {intent}\n\n"
                f"Reply with 2-4 actions, one per line:\n"
                f"1. [action_type] | [description]\n"
            )
            result = await generate_text(prompt, max_tokens=200)
            steps = []
            for line in result.strip().split("\n"):
                line = line.strip()
                if not line or not line[0].isdigit():
                    continue
                parts = line.split("|")
                atype = parts[0].strip().lstrip("0123456789.) ").lower().replace(" ", "_")
                desc = parts[1].strip() if len(parts) > 1 else user_input
                steps.append({"action_type": atype, "description": desc})
            return steps
        except Exception as _exc:  # broad catch — resilience against all failures
            return []


class DirectorGraphStrategy(OrchestrationStrategy):
    """Director graph: DAG orchestration with conditional routing."""

    name = "director_graph"
    resource_weight = "heavy"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.director_graph import (
                DirectorGraphExecutor, GRAPH_TEMPLATES,
            )

            template = self._select_template(user_input, intent)
            graph = GRAPH_TEMPLATES.get(template)
            if graph is None:
                graph = GRAPH_TEMPLATES.get("director_loop")
            if graph is None:
                return self._empty_result("No graph templates available")

            max_hops = 10
            try:
                orch_cfg = getattr(settings, "director_graph", None)
                if orch_cfg and hasattr(orch_cfg, "get"):
                    max_hops = orch_cfg.get("max_hops", 10)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)  # was: pass

            executor = DirectorGraphExecutor(max_hops=max_hops)
            result = await executor.execute(graph, user_input, intent, context)

            return OrchestrationResult(
                strategy_used=self.name,
                context=result.get("context", ""),
                agent_trace=result.get("trace", []),
                iterations=result.get("iterations", 1),
                quality_score=result.get("quality", 0.5),
                duration_ms=(time.monotonic() - start) * 1000,
                success=bool(result.get("context")),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:director_graph] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    def _select_template(self, user_input: str, intent: str) -> str:
        """Select best graph template based on query characteristics."""
        lower = user_input.lower()
        word_count = len(user_input.split())

        # Complex multi-aspect queries → deep_analysis
        if word_count > 30 or "analyze" in lower and "validate" in lower:
            return "deep_analysis"

        # Comparison / multi-perspective → parallel_experts
        compare_kw = {"compare", "difference", "vs", "versus", "contrast"}
        if any(kw in lower for kw in compare_kw):
            return "parallel_experts"

        # Quality-critical queries → iterative_refinement
        quality_kw = {"best practice", "optimize", "improve", "refine"}
        if any(kw in lower for kw in quality_kw):
            return "iterative_refinement"

        return "director_loop"


class FeedbackLoopStrategy(OrchestrationStrategy):
    """Interactive feedback: multi-turn self-critique and refinement."""

    name = "feedback_loop"
    resource_weight = "medium"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.agent_dispatcher import (
                get_agent_dispatcher, format_agent_context_for_llm,
            )
            dispatcher = get_agent_dispatcher()

            # 1. Generate initial response
            initial_result = await dispatcher.dispatch(
                user_input, intent, user_approved=user_approved,
            )
            initial_ctx = format_agent_context_for_llm(initial_result) or ""

            if not initial_result.success:
                return OrchestrationResult(
                    strategy_used=self.name, context=initial_ctx,
                    quality_score=0.0, iterations=1,
                    duration_ms=(time.monotonic() - start) * 1000,
                    success=False,
                )

            # 2. Self-critique
            critique = await self._self_critique(initial_ctx, user_input, intent)
            quality = critique.get("quality", 0.5)
            threshold = getattr(settings, "quality_threshold", 0.7)

            if quality >= threshold:
                return OrchestrationResult(
                    strategy_used=self.name, context=initial_ctx,
                    system_prompt_fragment=initial_result.system_prompt_fragment,
                    agent_trace=[initial_result.to_dict()],
                    quality_score=quality, iterations=1,
                    duration_ms=(time.monotonic() - start) * 1000,
                    success=True,
                )

            # 3. Refinement loop
            refined = initial_ctx
            trace = [initial_result.to_dict()]
            max_iter = getattr(settings, "max_iterations", 3) - 1
            final_quality = quality

            for i in range(max_iter):
                gaps = critique.get("gaps", "")
                refinement_query = f"{user_input}\n\nPlease also address: {gaps}"

                refine_result = await dispatcher.dispatch(
                    refinement_query, intent,
                    user_approved=user_approved,
                    skip_top_n=1,  # Try a different agent
                )
                if refine_result.success and refine_result.enriched_context:
                    refined = refined + "\n\n### Refinement\n" + refine_result.enriched_context
                    trace.append(refine_result.to_dict())

                critique = await self._self_critique(refined, user_input, intent)
                final_quality = critique.get("quality", 0.5)
                if final_quality >= threshold:
                    break

            # 4. If still below threshold, flag for clarification
            spf = initial_result.system_prompt_fragment or ""
            if final_quality < threshold:
                gaps = critique.get("gaps", "Need more specific information")
                spf = f"[NEEDS_CLARIFICATION] {gaps}"

            return OrchestrationResult(
                strategy_used=self.name,
                context=refined,
                system_prompt_fragment=spf,
                agent_trace=trace,
                quality_score=final_quality,
                iterations=len(trace),
                duration_ms=(time.monotonic() - start) * 1000,
                success=True,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:feedback_loop] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def _self_critique(
        self, context: str, user_input: str, intent: str
    ) -> Dict[str, Any]:
        """Use LLM to assess response quality and identify gaps."""
        try:
            from chat_app.llm_utils import generate_text  # type: ignore[attr-defined]
            prompt = (
                f"Rate this response for the query '{user_input}' (intent: {intent}).\n\n"
                f"Response:\n{context[:1500]}\n\n"
                f"Reply in this exact format:\n"
                f"QUALITY: [0.0-1.0]\n"
                f"GAPS: [what's missing or could be improved, or 'none']\n"
            )
            result = await generate_text(prompt, max_tokens=100)
            quality = 0.5
            gaps = ""
            for line in result.strip().split("\n"):
                if line.startswith("QUALITY:"):
                    try:
                        quality = float(line.split(":")[1].strip())
                        quality = max(0.0, min(1.0, quality))
                    except (ValueError, IndexError) as _exc:
                        logger.debug("Could not parse QUALITY score from assessment line: %s", _exc)
                elif line.startswith("GAPS:"):
                    gaps = line.split(":", 1)[1].strip()
            return {"quality": quality, "gaps": gaps}
        except Exception as _exc:  # broad catch — resilience against all failures
            return {"quality": 0.5, "gaps": "Assessment unavailable"}
