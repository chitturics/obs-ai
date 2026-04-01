"""
SupervisorAgent — Orchestration strategy with explicit task decomposition,
intra-department routing, structured findings, synthesis, and escalation.

Registered as the 18th orchestration strategy ("supervisor").

Key differences from adaptive/hierarchical:
1. Structured ResearchFinding outputs from each worker agent
2. Intra-department routing — multiple agents from the same department
3. Quality-gated escalation mid-execution
4. Provenance-tracked synthesis
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from chat_app.schemas import ResearchFinding

logger = logging.getLogger(__name__)

# Quality threshold for escalation
DEFAULT_QUALITY_THRESHOLD = 0.5
MAX_ESCALATION_ROUNDS = 2


class SupervisorAgent:
    """Explicit coordinator for complex, multi-aspect queries.

    Workflow:
    1. Decompose query into sub-tasks
    2. Assign agents (intra-department routing)
    3. Execute and collect ResearchFindings
    4. Quality check — escalate if below threshold
    5. Synthesize findings into final context
    """

    def __init__(self, quality_threshold: float = DEFAULT_QUALITY_THRESHOLD):
        self.quality_threshold = quality_threshold

    async def supervise(
        self,
        user_input: str,
        intent: str,
        context: Any = None,
        settings: Any = None,
        user_approved: bool = False,
    ) -> "SupervisorResult":
        """Execute the supervised workflow."""
        start = time.monotonic()
        findings: List[ResearchFinding] = []
        agent_trace: List[Dict[str, Any]] = []

        try:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            dispatcher = get_agent_dispatcher()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[SUPERVISOR] Cannot get dispatcher: %s", exc)
            return SupervisorResult(
                findings=[],
                synthesized_context="",
                quality_score=0.0,
                duration_ms=(time.monotonic() - start) * 1000,
                success=False,
                error=str(exc),
            )

        # 1. Decompose into sub-tasks
        sub_tasks = self._decompose(user_input, intent)
        logger.info("[SUPERVISOR] Decomposed '%s' into %d sub-tasks", intent, len(sub_tasks))

        # 2. Assign agents
        assignments = self._assign_agents(sub_tasks, dispatcher)

        # 3. Execute in parallel and collect findings
        async def _execute_subtask(task_desc: str, dept: Optional[str]) -> ResearchFinding:
            try:
                from chat_app.agent_catalog import Department
                preferred_dept = None
                if dept:
                    try:
                        preferred_dept = Department(dept)
                    except ValueError as _exc:
                        logger.debug("Unknown department %r, routing without department filter: %s", dept, _exc)

                result = await dispatcher.dispatch(
                    user_input=user_input,
                    intent=intent,
                    preferred_department=preferred_dept,
                    user_approved=user_approved,
                    max_skills=2,
                )

                agent_trace.append(result.to_dict())

                finding = ResearchFinding(
                    topic=task_desc,
                    summary=result.enriched_context[:500] if result.enriched_context else "",
                    confidence=0.7 if result.success else 0.2,
                    agent_name=result.agent_name,
                    sources=[s for s in result.skills_executed],
                    metadata={
                        "department": result.department,
                        "duration_ms": result.duration_ms,
                    },
                )
                return finding
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                return ResearchFinding(
                    topic=task_desc,
                    summary=f"Error: {exc}",
                    confidence=0.0,
                )

        coros = [_execute_subtask(desc, dept) for desc, dept in assignments]
        findings = await asyncio.gather(*coros)
        findings = list(findings)

        # 4. Quality check and escalation
        avg_confidence = sum(f.confidence for f in findings) / max(len(findings), 1)
        escalation_round = 0

        while avg_confidence < self.quality_threshold and escalation_round < MAX_ESCALATION_ROUNDS:
            escalation_round += 1
            logger.info(
                "[SUPERVISOR] Escalating (round %d): avg_confidence=%.2f < threshold=%.2f",
                escalation_round, avg_confidence, self.quality_threshold,
            )
            # Escalate: dispatch to a different department for additional perspectives
            low_findings = [f for f in findings if f.confidence < self.quality_threshold]
            for lf in low_findings[:2]:  # Escalate max 2 low-confidence findings
                escalated = await _execute_subtask(
                    f"Deep analysis: {lf.topic}",
                    "engineering",  # Escalate to engineering as fallback
                )
                findings.append(escalated)

            avg_confidence = sum(f.confidence for f in findings) / max(len(findings), 1)

        # 5. Synthesize
        synthesized = self._synthesize(findings)
        quality_score = min(1.0, avg_confidence)

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "[SUPERVISOR] Complete: %d findings, quality=%.2f, escalations=%d, %.0fms",
            len(findings), quality_score, escalation_round, duration_ms,
        )

        return SupervisorResult(
            findings=findings,
            synthesized_context=synthesized,
            quality_score=quality_score,
            agent_trace=agent_trace,
            duration_ms=duration_ms,
            success=True,
            escalation_rounds=escalation_round,
        )

    def _decompose(self, user_input: str, intent: str) -> List[str]:
        """Decompose a query into sub-tasks based on structure and intent."""
        sub_tasks = []

        # Split on common multi-part patterns
        # "X and Y", "X, then Y", "first X, then Y"
        parts = re.split(r'\b(?:and then|then|and also|and|,\s*then)\b', user_input, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 5]

        if len(parts) > 1:
            sub_tasks = parts
        else:
            # Single task — still decompose into analysis + recommendation
            sub_tasks = [user_input]
            if len(user_input.split()) > 15:
                # Long query — add analysis sub-task
                sub_tasks.append(f"Analyze context for: {user_input[:100]}")

        return sub_tasks[:5]  # Cap at 5 sub-tasks

    def _assign_agents(
        self, sub_tasks: List[str], dispatcher: Any
    ) -> List[Tuple[str, Optional[str]]]:
        """Assign department preferences to sub-tasks (intra-department routing)."""
        assignments = []
        for task_desc in sub_tasks:
            dept = self._infer_department(task_desc)
            assignments.append((task_desc, dept))
        return assignments

    def _infer_department(self, task_desc: str) -> Optional[str]:
        """Infer the best department for a sub-task."""
        desc_lower = task_desc.lower()
        if any(kw in desc_lower for kw in ("config", "props", "transforms", "inputs", "outputs")):
            return "engineering"
        if any(kw in desc_lower for kw in ("search", "spl", "query", "stats", "eval")):
            return "data"
        if any(kw in desc_lower for kw in ("deploy", "restart", "health", "monitor")):
            return "operations"
        if any(kw in desc_lower for kw in ("security", "auth", "encrypt", "cert")):
            return "security"
        if any(kw in desc_lower for kw in ("dashboard", "report", "alert")):
            return "knowledge"
        return None

    def _synthesize(self, findings: List[ResearchFinding]) -> str:
        """Synthesize findings into a single context string."""
        if not findings:
            return ""

        parts = []
        for i, f in enumerate(findings, 1):
            if not f.summary:
                continue
            header = f"**{f.topic}**"
            if f.agent_name:
                header += f" (via {f.agent_name})"
            parts.append(f"{header}\n{f.summary}")

            if f.recommendations:
                parts.append("Recommendations: " + "; ".join(f.recommendations))

        return "\n\n".join(parts)


class SupervisorResult:
    """Result from a supervised execution."""

    def __init__(
        self,
        findings: List[ResearchFinding],
        synthesized_context: str = "",
        quality_score: float = 0.0,
        agent_trace: Optional[List[Dict[str, Any]]] = None,
        duration_ms: float = 0.0,
        success: bool = True,
        error: Optional[str] = None,
        escalation_rounds: int = 0,
    ):
        self.findings = findings
        self.synthesized_context = synthesized_context
        self.quality_score = quality_score
        self.agent_trace = agent_trace or []
        self.duration_ms = duration_ms
        self.success = success
        self.error = error
        self.escalation_rounds = escalation_rounds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "findings_count": len(self.findings),
            "quality_score": round(self.quality_score, 4),
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "escalation_rounds": self.escalation_rounds,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Orchestration Strategy Registration
# ---------------------------------------------------------------------------

def _register_supervisor_strategy() -> None:
    """Register SupervisorAgent as the 18th orchestration strategy."""
    try:
        from chat_app.orchestration_strategies import (
            OrchestrationResult,
            OrchestrationStrategy,
            register_strategy,
        )

        class SupervisorStrategy(OrchestrationStrategy):
            """Supervisor-coordinated multi-agent execution with structured findings."""

            name = "supervisor"
            resource_weight = "heavy"

            async def execute(
                self,
                user_input: str,
                intent: str,
                plan: Any,
                context: Any,
                settings: Any,
                user_approved: bool = False,
            ) -> OrchestrationResult:
                supervisor = SupervisorAgent()
                result = await supervisor.supervise(
                    user_input=user_input,
                    intent=intent,
                    context=context,
                    settings=settings,
                    user_approved=user_approved,
                )

                return OrchestrationResult(
                    strategy_used="supervisor",
                    context=result.synthesized_context,
                    agent_trace=result.agent_trace,
                    quality_score=result.quality_score,
                    duration_ms=result.duration_ms,
                    success=result.success,
                    error=result.error,
                )

            def is_applicable(self, intent: str, user_input: str) -> bool:
                # Auto-detect: long queries with multiple intents
                word_count = len(user_input.split())
                has_multi_part = bool(re.search(
                    r'\b(and then|then|and also|first.*then)\b',
                    user_input, re.IGNORECASE,
                ))
                return word_count > 30 or has_multi_part

        register_strategy(SupervisorStrategy())
        logger.info("[SUPERVISOR] Registered as orchestration strategy #18")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[SUPERVISOR] Strategy registration failed: %s", exc)


# Auto-register on import
_register_supervisor_strategy()
