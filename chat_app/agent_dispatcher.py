"""
Agent Dispatcher — Routes queries to the best agent persona and executes their skills.

This is the component that makes agents REAL:
- Selects the best agent persona for a query based on intent + expertise
- Injects the agent's personality into the LLM system prompt
- Executes the agent's skill chain via SkillExecutor
- Tracks agent activity and performance
- Supports multi-agent delegation for complex tasks

Flow:
    User Query → IntentClassifier → AgentDispatcher → Agent Persona
        → SkillExecutor(skill_1) → SkillExecutor(skill_2) → ...
        → Enriched Context → LLM Response

Secondary methods (planning, reflection, metrics, collaboration): agent_dispatcher_helpers.py
Data models and scoring constants: agent_dispatch_models.py
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from chat_app.agent_catalog import (
    AgentCatalog,
    AgentPersona,
    Department,
    ExpertiseLevel,
    get_agent_catalog,
)
from chat_app.agent_dispatch_models import (  # noqa: F401
    AgentDispatchResult,
    DEPARTMENT_RELEVANCE_BONUS,
    EXPERTISE_SCORE_EXPERT,
    EXPERTISE_SCORE_GENERALIST,
    EXPERTISE_SCORE_LEAD,
    EXPERTISE_SCORE_SPECIALIST,
    HISTORICAL_QUALITY_WEIGHT,
    INTENT_MATCH_BONUS,
    MIN_DISPATCHES_FOR_HISTORY,
    RECENT_QUALITY_WINDOW,
    RECENCY_WEIGHT_INCREMENT,
    ROLE_KEYWORD_MATCH_BONUS,
    SKILL_AVAILABILITY_BONUS,
    SUCCESS_RATE_BONUS,
    TAG_MATCH_BONUS,
)
from chat_app.agent_dispatcher_helpers import AgentDispatcherHelpersMixin
from chat_app.skill_catalog import get_skill_catalog
from chat_app.skill_executor import (
    SkillExecResult,
    SkillExecutor,
    get_skill_executor,
)

logger = logging.getLogger(__name__)

try:
    from chat_app.logging_utils import structured_log
except ImportError:
    def structured_log(lg, level, tag, msg, **kw):  # type: ignore
        lg.log(level, "[%s] %s %s", tag, msg, kw)


# ---------------------------------------------------------------------------
# Agent Dispatcher
# ---------------------------------------------------------------------------

class AgentDispatcher(AgentDispatcherHelpersMixin):
    """
    Routes queries to the best agent persona and orchestrates skill execution.

    The dispatcher:
    1. Takes a user query + classified intent
    2. Selects the best agent from the catalog
    3. Determines which of the agent's skills to execute
    4. Runs skills via SkillExecutor
    5. Returns enriched context + agent personality for LLM
    """

    def __init__(
        self,
        agent_catalog: Optional[AgentCatalog] = None,
        skill_executor: Optional[SkillExecutor] = None,
    ):
        self._catalog = agent_catalog or get_agent_catalog()
        self._executor = skill_executor or get_skill_executor()
        self._dispatch_log: List[Dict[str, Any]] = []
        self._agent_metrics: Dict[str, Dict[str, Any]] = {}
        # Quality tracking: {agent_name: {intent: [scores]}}
        self._agent_quality: Dict[str, Dict[str, List[float]]] = {}
        # Maps skill_name → executor source (or None if unresolvable), avoids O(n^2) lookups
        self._handler_cache: Dict[str, Optional[str]] = {}
        # Last selection reasoning (for observability)
        self._last_reasoning: Dict[str, Any] = {}
        # Restore quality data from Redis
        self._restore_quality()

    # Skills that produce context and should run first (information gathering)
    _CONTEXT_PRODUCER_KEYS: Set[str] = {
        "search_knowledge_base", "analyze_spl", "validate_spl",
        "read_config", "security_audit", "analyze_metrics",
        "list_indexes", "diagnose_issue",
    }

    # Skills that consume context and should run later (synthesis/output)
    _CONTEXT_CONSUMER_KEYS: Set[str] = {
        "generate_spl", "optimize_spl", "write_documentation",
        "generate_report", "explain_concept",
    }

    def select_agent(
        self,
        intent: str,
        user_input: str = "",
        preferred_department: Optional[Department] = None,
        skip_top_n: int = 0,
    ) -> Optional[AgentPersona]:
        """
        Select the best agent for a given intent and query.

        Selection strategy:
        1. Get all agents for the intent
        2. If preferred_department specified, filter by department
        3. Score agents by expertise + skills + quality + context awareness
        4. Return the highest-scoring agent
        """
        candidates = self._catalog.get_for_intent(intent)

        if not candidates and user_input:
            # Fallback: search by each significant keyword in the user input
            seen: Set[str] = set()
            for word in user_input.lower().split():
                if len(word) < 3:
                    continue
                for agent in self._catalog.search(word):
                    if agent.name not in seen:
                        seen.add(agent.name)
                        candidates.append(agent)

        if not candidates:
            # Last resort: general_assistant
            fallback = self._catalog.get("general_assistant")
            if fallback:
                return fallback
            return None

        # Filter by department if specified
        if preferred_department:
            department_matches = [agent for agent in candidates if agent.department == preferred_department]
            if department_matches:
                candidates = department_matches

        # Score candidates
        def score_agent(agent: AgentPersona) -> float:
            expertise_scores = {
                ExpertiseLevel.LEAD: EXPERTISE_SCORE_LEAD,
                ExpertiseLevel.EXPERT: EXPERTISE_SCORE_EXPERT,
                ExpertiseLevel.SPECIALIST: EXPERTISE_SCORE_SPECIALIST,
                ExpertiseLevel.GENERALIST: EXPERTISE_SCORE_GENERALIST,
            }
            score = expertise_scores.get(agent.expertise, EXPERTISE_SCORE_GENERALIST)

            # Bonus for having more executable skills (cached resolution)
            executable_skills = 0
            for skill_name in agent.skills:
                if skill_name not in self._handler_cache:
                    skill = get_skill_catalog().get(skill_name)
                    if skill:
                        source, _ = self._executor.resolve_handler(skill.handler_key)
                        self._handler_cache[skill_name] = source
                    else:
                        self._handler_cache[skill_name] = None
                if self._handler_cache.get(skill_name):
                    executable_skills += 1
            score += executable_skills * SKILL_AVAILABILITY_BONUS

            # Bonus for intent match specificity
            if intent in agent.intents:
                score += INTENT_MATCH_BONUS

            # Bonus for keyword match in user input
            if user_input:
                input_lower = user_input.lower()
                if agent.role.lower() in input_lower:
                    score += ROLE_KEYWORD_MATCH_BONUS
                for tag in agent.tags:
                    if tag in input_lower:
                        score += TAG_MATCH_BONUS

                # Context-aware: boost agents whose department matches query topics
                department_keywords = {
                    "security": ["security", "threat", "audit", "compliance", "vulnerability"],
                    "data": ["data", "index", "search", "spl", "query", "report"],
                    "operations": ["deploy", "monitor", "health", "container", "service"],
                    "engineering": ["code", "script", "build", "test", "config", "pipeline"],
                    "infrastructure": ["network", "server", "cloud", "platform", "dns"],
                    "knowledge": ["document", "learn", "knowledge", "docs", "wiki"],
                }
                department_name = (
                    agent.department.value if hasattr(agent.department, 'value')
                    else str(agent.department)
                )
                for keyword in department_keywords.get(department_name, []):
                    if keyword in input_lower:
                        score += DEPARTMENT_RELEVANCE_BONUS

            # Quality-weighted bonus from historical performance (capped 0-1.0)
            agent_quality_history = self._agent_quality.get(agent.name, {})
            intent_quality_scores = agent_quality_history.get(intent, [])
            if intent_quality_scores:
                recent_scores = intent_quality_scores[-RECENT_QUALITY_WINDOW:]
                # Exponential moving average: more recent scores weighted higher
                total_weight = 0.0
                weighted_sum = 0.0
                for position, quality_score in enumerate(recent_scores):
                    recency_weight = 1.0 + position * RECENCY_WEIGHT_INCREMENT
                    weighted_sum += quality_score * recency_weight
                    total_weight += recency_weight
                average_quality = weighted_sum / total_weight if total_weight > 0 else 0.5
                score += min(max(average_quality, 0.0), 1.0) * HISTORICAL_QUALITY_WEIGHT

            # Success rate bonus from metrics
            agent_metrics = self._agent_metrics.get(agent.name)
            if agent_metrics and agent_metrics["dispatches"] >= MIN_DISPATCHES_FOR_HISTORY:
                success_rate = agent_metrics["successes"] / agent_metrics["dispatches"]
                score += success_rate * SUCCESS_RATE_BONUS

            # Tool effectiveness bonus: agents whose skills have high historical success rates
            try:
                from chat_app.tool_effectiveness import get_effectiveness_tracker
                tracker = get_effectiveness_tracker()
                intent_tool_stats = tracker._intent_stats.get(intent, {})
                if intent_tool_stats:
                    skill_success_rates = []
                    for skill_name in agent.skills:
                        skill_obj = get_skill_catalog().get(skill_name)
                        if skill_obj and skill_obj.handler_key in intent_tool_stats:
                            stats = intent_tool_stats[skill_obj.handler_key]
                            if stats.total_executions >= 3:
                                skill_success_rates.append(stats.success_rate)
                    if skill_success_rates:
                        avg_success = sum(skill_success_rates) / len(skill_success_rates)
                        score += 0.5 * avg_success
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.debug("%s", exc)

            return score

        # Score all candidates and build reasoning trace
        scored = [(score_agent(agent), agent) for agent in candidates]

        # Episodic memory adjustment based on dispatch log
        try:
            if self._dispatch_log:
                for index, (sc, agent) in enumerate(scored):
                    agent_dispatches = [
                        entry for entry in self._dispatch_log
                        if entry.get("agent_name") == agent.name
                        and entry.get("reasoning", {}).get("intent") == intent
                    ]
                    if agent_dispatches:
                        recent = agent_dispatches[-5:]
                        successes = sum(1 for entry in recent if entry.get("success"))
                        failures = len(recent) - successes
                        if successes > failures:
                            scored[index] = (sc + 0.3 * (successes / len(recent)), agent)
                        elif failures > successes and len(recent) >= 2:
                            scored[index] = (sc - 0.2 * (failures / len(recent)), agent)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        scored.sort(key=lambda item: item[0], reverse=True)
        # skip_top_n enables diversity (e.g., voting strategy picks Nth-best agent)
        pick_idx = min(skip_top_n, len(scored) - 1)
        best_score, best = scored[pick_idx]

        # Build reasoning trace for dispatch log
        reasoning = {
            "intent": intent,
            "candidates_count": len(candidates),
            "top_3": [
                {
                    "agent": a.name,
                    "score": round(s, 2),
                    "dept": a.department.value if hasattr(a.department, 'value') else str(a.department),
                }
                for s, a in scored[:3]
            ],
            "selection_reason": self._explain_selection(best, intent, user_input, best_score),
        }
        self._last_reasoning = reasoning

        structured_log(logger, logging.INFO, "DISPATCH", "Agent selected",
                       agent=best.name, role=best.role, intent=intent,
                       score=round(best_score, 2), candidates=len(candidates),
                       top_3=[t["agent"] for t in reasoning["top_3"]],
                       reason=reasoning["selection_reason"])
        return best

    def _explain_selection(
        self, agent: AgentPersona, intent: str, user_input: str, score: float
    ) -> str:
        """Generate a human-readable explanation of why this agent was selected."""
        reasons = []
        if intent in agent.intents:
            reasons.append(f"intent '{intent}' match")
        expertise_name = (
            agent.expertise.value if hasattr(agent.expertise, 'value') else str(agent.expertise)
        )
        reasons.append(f"{expertise_name} expertise")
        if user_input and agent.role.lower() in user_input.lower():
            reasons.append("role keyword match")
        quality_data = self._agent_quality.get(agent.name, {})
        if quality_data.get(intent):
            avg = sum(quality_data[intent][-10:]) / len(quality_data[intent][-10:])
            reasons.append(f"quality={avg:.2f}")
        return "; ".join(reasons) if reasons else "best available"

    async def dispatch(
        self,
        user_input: str,
        intent: str,
        params: Dict[str, Any] = None,
        max_skills: int = 5,
        preferred_department: Optional[Department] = None,
        user_approved: bool = False,
        skip_top_n: int = 0,
    ) -> AgentDispatchResult:
        """
        Dispatch a query to the best agent and execute their skills.

        Args:
            user_input: The user's query
            intent: Classified intent
            params: Additional parameters for skill execution
            max_skills: Maximum number of skills to execute
            preferred_department: Optional department preference
            user_approved: Whether user has pre-approved all skills
            skip_top_n: Skip top N agents (for diversity in voting strategy)

        Returns:
            AgentDispatchResult with enriched context and agent info
        """
        start = time.monotonic()
        params = params or {}
        request_id = params.get("request_id", "")

        structured_log(logger, logging.INFO, "AGENT", "dispatch_start",
                       agent="pending", intent=intent, rid=request_id)

        # 1. Select the best agent
        agent = self.select_agent(intent, user_input, preferred_department, skip_top_n=skip_top_n)
        if not agent:
            structured_log(logger, logging.WARNING, "AGENT", "dispatch_end",
                           agent="none", intent=intent, rid=request_id,
                           duration_ms=round((time.monotonic() - start) * 1000, 1),
                           success=False, skills=0)
            return AgentDispatchResult(
                agent_name="none", agent_role="none", department="none",
                success=False, error="No suitable agent found for this query",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        # 1b. Inject GCI improvement feedback into agent context
        try:
            from chat_app.gci_agent import get_gci_agent
            improvement_feedback = get_gci_agent().get_agent_feedback(agent.name)
            if improvement_feedback:
                agent._gci_overlay = improvement_feedback
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # 1c. Persona-aware agent scoring — boost agents matching user persona
        try:
            user_persona = params.get("user_persona", "")
            if user_persona:
                from chat_app.persona_orchestration import get_persona_orchestrator
                persona_orchestrator = get_persona_orchestrator()
                agent_dept = (
                    agent.department.value if hasattr(agent.department, "value")
                    else str(agent.department)
                )
                agent_exp = (
                    agent.expertise.value if hasattr(agent.expertise, "value")
                    else str(agent.expertise)
                )
                persona_score = persona_orchestrator.score_agent(user_persona, agent_dept, agent_exp)
                if persona_score > 0:
                    structured_log(logger, logging.DEBUG, "DISPATCH", "Persona match",
                                   agent=agent.name, persona=user_persona, boost=round(persona_score, 2))
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # 1d. Pre-execution self-assessment: can this agent handle it?
        try:
            from chat_app.agent_self_assessment import get_assessor
            pre_assessment = get_assessor().assess_pre(
                agent, intent, user_input,
                retrieved_chunks=len(params.get("memory_chunks", [])) if params else 0,
            )
            if pre_assessment.should_ask_user and pre_assessment.clarification_questions:
                question_count = len(pre_assessment.clarification_questions)
                structured_log(logger, logging.INFO, "AGENT", "clarify",
                               agent=agent.name, questions=question_count, rid=request_id)
                return AgentDispatchResult(
                    agent_name=agent.name, agent_role=agent.role,
                    department=agent.department.value,
                    success=True,
                    clarification_needed=True,
                    clarification_questions=pre_assessment.clarification_questions,
                    duration_ms=(time.monotonic() - start) * 1000,
                )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # 2. Determine which skills to execute
        skills_to_run = self._plan_agent_skills(agent, intent, user_input, max_skills)

        structured_log(logger, logging.INFO, "DISPATCH", "Skill chain planned",
                       agent=agent.name, intent=intent,
                       skills=skills_to_run, count=len(skills_to_run))

        # 3. Execute skills — parallel when independent, sequential as fallback
        skill_results: List[SkillExecResult] = []
        skills_executed: List[str] = []

        # Pre-build params for each skill
        all_skill_params = []
        all_handler_keys = []
        for skill_name in skills_to_run:
            skill_params = {**params, "user_input": user_input, "intent": intent}
            skill = get_skill_catalog().get(skill_name)
            handler_key = skill.handler_key if skill else ""

            if skill and skill.handler_key in ("analyze_spl", "optimize_spl", "validate_spl"):
                query = self._extract_spl(user_input)
                if query:
                    skill_params["query"] = query
            elif skill and skill.handler_key == "generate_spl":
                skill_params["description"] = user_input
            elif skill and skill.handler_key == "search_knowledge_base":
                skill_params["query"] = user_input

            all_skill_params.append(skill_params)
            all_handler_keys.append(handler_key)

        # Try parallel execution if skills are independent and user pre-approved
        if (len(skills_to_run) > 1
                and user_approved
                and self._are_skills_independent(skills_to_run)):
            structured_log(logger, logging.INFO, "DISPATCH", "Executing skills in parallel",
                           agent=agent.name, skills=skills_to_run)
            tasks = [
                self._executor.execute(
                    skill_name=skill_name, params=skill_params,
                    user_approved=user_approved,
                )
                for skill_name, skill_params in zip(skills_to_run, all_skill_params)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for index, result in enumerate(results):
                parallel_skill_name = skills_to_run[index]
                if isinstance(result, Exception):
                    logger.warning("[DISPATCH] Parallel skill %s failed: %s",
                                   parallel_skill_name, result)
                    exec_result = SkillExecResult(
                        success=False, output="",
                        skill_name=parallel_skill_name,
                        handler_key=all_handler_keys[index],
                        error=str(result),
                    )
                    structured_log(logger, logging.WARNING, "AGENT", "skill_exec",
                                   agent=agent.name, skill=parallel_skill_name,
                                   duration_ms=0, success=False)
                    skill_results.append(exec_result)
                else:
                    structured_log(logger, logging.INFO, "AGENT", "skill_exec",
                                   agent=agent.name, skill=parallel_skill_name,
                                   duration_ms=round(getattr(result, "duration_ms", 0), 1),
                                   success=result.success)
                    skill_results.append(result)
                skills_executed.append(parallel_skill_name)
        else:
            # Sequential execution (fallback for dependent skills or single skill)
            for skill_name, skill_params in zip(skills_to_run, all_skill_params):
                skill_start = time.monotonic()
                result = await self._executor.execute(
                    skill_name=skill_name, params=skill_params,
                    user_approved=user_approved,
                )
                skill_duration_ms = round((time.monotonic() - skill_start) * 1000, 1)
                structured_log(logger, logging.INFO, "AGENT", "skill_exec",
                               agent=agent.name, skill=skill_name,
                               duration_ms=skill_duration_ms, success=result.success)
                skill_results.append(result)
                skills_executed.append(skill_name)

                # If a skill failed with approval_required, stop chain
                if result.approval_required:
                    break
                if not result.success:
                    structured_log(logger, logging.WARNING, "DISPATCH", "Skill failed, continuing chain",
                                   skill=skill_name, error=result.error,
                                   agent=agent.name, handler=result.handler_key)

        # 4. Build enriched context
        enriched_parts = []
        for result in skill_results:
            if result.success and result.output:
                enriched_parts.append(
                    f"**[Agent: {agent.display_name} | Skill: {result.skill_name}]**\n"
                    f"{result.output}"
                )

        enriched_context = "\n\n---\n\n".join(enriched_parts) if enriched_parts else ""

        # 5. Build result
        duration_ms = (time.monotonic() - start) * 1000
        dispatch_result = AgentDispatchResult(
            agent_name=agent.name,
            agent_role=agent.role,
            department=agent.department.value,
            skills_executed=skills_executed,
            skill_results=skill_results,
            enriched_context=enriched_context,
            system_prompt_fragment=agent.get_system_prompt_fragment(),
            success=any(r.success for r in skill_results) if skill_results else True,
            duration_ms=duration_ms,
        )

        # 6. Post-execution self-reflection
        reflection = self._reflect_on_execution(dispatch_result, intent)
        dispatch_result.reflection = reflection

        structured_log(logger, logging.INFO, "DISPATCH", "Dispatch complete",
                       agent=agent.name, intent=intent,
                       skills_run=len(skills_executed),
                       success=dispatch_result.success,
                       duration_ms=round(duration_ms, 1),
                       quality=reflection.get("estimated_quality") if reflection else None,
                       context_chars=len(enriched_context))
        structured_log(logger, logging.INFO, "AGENT", "dispatch_end",
                       agent=agent.name, intent=intent, rid=request_id,
                       duration_ms=round(duration_ms, 1),
                       success=dispatch_result.success,
                       skills=len(skills_executed))

        self._record_dispatch(dispatch_result)

        # Record to unified activity timeline
        try:
            from chat_app.activity_timeline import get_timeline
            get_timeline().record(
                event_type="agent_dispatch",
                actor=agent.name,
                action="dispatch",
                target=intent or "unknown",
                details={
                    "skills_executed": skills_executed,
                    "duration_ms": round(duration_ms, 1),
                    "quality": reflection.get("estimated_quality") if reflection else None,
                },
                status="ok" if dispatch_result.success else "error",
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # Record Prometheus dispatch metrics
        try:
            from chat_app.prometheus_metrics import record_agent_dispatch
            record_agent_dispatch(
                agent_name=agent.name,
                intent=intent or "unknown",
                success=bool(dispatch_result.success),
                duration_ms=duration_ms,
                quality=(
                    dispatch_result.reflection.get("estimated_quality", 0.0)
                    if dispatch_result.reflection else 0.0
                ),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # Record to universal execution tracker
        try:
            from chat_app.execution_tracker import get_execution_store, WorkflowTrace
            import uuid as _uuid
            trace = WorkflowTrace(
                trace_id=_uuid.uuid4().hex[:12],
                category="agent",
                name=agent.name,
                actor=params.get("username", "") if params else "",
                intent=intent or "",
                agent=agent.name,
                department=(
                    agent.department.value
                    if hasattr(agent.department, "value") else ""
                ),
                persona=params.get("user_persona", "") if params else "",
                strategy=params.get("strategy", "") if params else "",
                started_at=(
                    dispatch_result._started_at
                    if hasattr(dispatch_result, "_started_at") else ""
                ),
                finished_at=datetime.now(timezone.utc).isoformat(),
                latency_ms=duration_ms,
                success=dispatch_result.success,
                error=dispatch_result.error,
                handler_key=f"agent:{agent.name}",
            )
            for skill_result in skill_results:
                trace.children.append(WorkflowTrace(
                    trace_id=_uuid.uuid4().hex[:12],
                    parent_id=trace.trace_id,
                    category="skill",
                    name=skill_result.skill_name,
                    handler_key=skill_result.handler_key,
                    handler_source=skill_result.source or "",
                    success=skill_result.success,
                    latency_ms=skill_result.duration_ms,
                    error=skill_result.error,
                ))
            get_execution_store().record(trace)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        return dispatch_result


# ---------------------------------------------------------------------------
# Convenience: format agent context for LLM
# ---------------------------------------------------------------------------

def format_agent_context_for_llm(result: AgentDispatchResult) -> Optional[str]:
    """
    Format agent dispatch result as additional context for the LLM prompt.

    This is injected into the system prompt so the LLM:
    1. Adopts the agent's personality
    2. Uses the agent's skill outputs as grounding context
    3. Follows department-specific response structure
    """
    if not result.success and not result.enriched_context:
        return None

    parts = []

    # Agent personality injection
    if result.system_prompt_fragment:
        parts.append(f"### Active Agent\n{result.system_prompt_fragment}")

    # Department response template
    try:
        from chat_app.prompts import AGENT_RESPONSE_TEMPLATES
        template = AGENT_RESPONSE_TEMPLATES.get(result.department, "")
        if template:
            parts.append(f"### Response Format Guidelines\n{template}")
    except ImportError:
        pass

    # Skill results as context
    if result.enriched_context:
        parts.append(f"### Agent Analysis\n{result.enriched_context}")

    return "\n\n".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_dispatcher: Optional[AgentDispatcher] = None


def get_agent_dispatcher() -> AgentDispatcher:
    """Get or create the singleton AgentDispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = AgentDispatcher()
    return _dispatcher
