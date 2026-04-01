"""
Agent Dispatcher Helpers — Secondary methods for the AgentDispatcher.

Extracted from agent_dispatcher.py for size management.
AgentDispatcher inherits from AgentDispatcherHelpersMixin.

Provides:
- _are_skills_independent, _execute_skills_parallel — parallel execution helpers
- _plan_agent_skills — skill selection with chain-of-thought scoring
- _extract_spl — SPL extraction utility
- _reflect_on_execution — post-dispatch quality assessment
- _record_dispatch — metrics and logging
- get_dispatch_log, get_agent_metrics — reporting
- record_quality, _persist_quality, _restore_quality — quality tracking
- collaborate — multi-agent collaboration
- _detect_departments — department auto-detection
- get_summary — dispatcher summary
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from chat_app.agent_catalog import Department
from chat_app.agent_dispatch_models import AgentDispatchResult
from chat_app.skill_executor import SkillExecResult


from chat_app.skill_catalog import get_skill_catalog  # noqa: E402


def _get_skill_catalog():
    """Indirection to allow tests to patch the module-level get_skill_catalog.

    Tests that patch ``chat_app.agent_dispatcher_helpers.get_skill_catalog`` will
    affect calls routed through this helper, preserving the pre-split test contract.
    For backward compatibility, ``chat_app.agent_dispatcher.get_skill_catalog`` is
    still the canonical patch target — see the re-export in agent_dispatcher.py.
    """
    return get_skill_catalog()

logger = logging.getLogger(__name__)

try:
    from chat_app.logging_utils import structured_log
except ImportError:
    def structured_log(lg, level, tag, msg, **kw):  # type: ignore
        lg.log(level, "[%s] %s %s", tag, msg, kw)


class AgentDispatcherHelpersMixin:
    """
    Mixin providing helper methods for AgentDispatcher.

    Expects the host class to provide:
    - self._catalog: AgentCatalog
    - self._executor: SkillExecutor
    - self._dispatch_log: List[Dict]
    - self._agent_metrics: Dict
    - self._agent_quality: Dict
    - self._handler_cache: Dict
    - self._last_reasoning: Dict
    - self._CONTEXT_PRODUCER_KEYS: set
    - self.select_agent(), self.record_quality() methods
    """

    def _are_skills_independent(self, skills: List[str]) -> bool:
        """
        Check if a list of skills are independent (no producer->consumer deps).

        Skills are independent if none of them consume context that another
        produces. If all are producers or all are consumers, they're independent.
        If there's a mix of producers and consumers, they're dependent.
        Also returns False if any skill requires approval (must run sequentially
        so the chain can stop on approval_required).
        """
        if len(skills) <= 1:
            return True

        skill_catalog = _get_skill_catalog()
        producers = set()
        consumers = set()
        for skill_name in skills:
            skill = skill_catalog.get(skill_name)
            if not skill:
                continue
            # Check approval requirement
            if getattr(skill, 'requires_approval', False):
                return False
            if skill.handler_key in self._CONTEXT_PRODUCER_KEYS:
                producers.add(skill_name)
            else:
                consumers.add(skill_name)

        # If there's a mix, they're dependent (producers must run first)
        if producers and consumers:
            return False
        return True

    async def _execute_skills_parallel(self, skills, handler_keys, params_list, user_approved):
        """Execute a list of skills in parallel and return combined results."""
        tasks = []
        for skill_name, params in zip(skills, params_list):
            task = self._executor.execute(
                skill_name=skill_name,
                params=params,
                user_approved=user_approved,
            )
            tasks.append(task)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        skill_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                skill_results.append(SkillExecResult(
                    skill_name=skills[i],
                    success=False,
                    output="",
                    error=str(result),
                ))
            else:
                skill_results.append(result)
        return skill_results

    def _plan_agent_skills(
        self,
        agent,
        intent: str,
        user_input: str,
        max_skills: int,
    ) -> List[str]:
        """
        Plan which of the agent's skills to execute for this query.

        Chain-of-thought scoring:
        - +3 for intent match
        - +2 for handler resolves
        - +1 per tag overlap with user_input
        - +1 per keyword match in handler_key
        - +0.5 for historical success on this intent
        - Dependency ordering: producers before consumers
        """
        skill_catalog = _get_skill_catalog()
        scored_skills: list[tuple[float, str, bool]] = []  # (score, name, is_producer)
        input_lower = user_input.lower()
        input_words = set(input_lower.split())

        for skill_name in agent.skills:
            skill = skill_catalog.get(skill_name)
            if not skill:
                continue

            # Check if the skill can actually execute (cached)
            if skill_name not in self._handler_cache:
                source, _ = self._executor.resolve_handler(skill.handler_key)
                self._handler_cache[skill_name] = source
            if not self._handler_cache.get(skill_name):
                continue

            score = 0.0

            # Intent match bonus
            if intent in skill.intents:
                score += 3.0

            # Handler resolves bonus
            score += 2.0

            # Tag overlap bonus
            for tag in getattr(skill, 'tags', []):
                if tag in input_lower:
                    score += 1.0

            # Keyword match: handler_key words vs input words
            handler_words = set(skill.handler_key.replace("_", " ").split())
            keyword_overlap = len(handler_words & input_words)
            score += keyword_overlap * 1.0

            # Action name match
            if hasattr(skill, 'action') and skill.action.lower() in input_lower:
                score += 1.5

            # Historical success rate for this skill on this intent
            skill_history = [
                entry for entry in self._executor.get_execution_log()
                if entry.get("skill") == skill_name and entry.get("success")
            ]
            if len(skill_history) >= 2:
                score += 0.5

            is_producer = skill.handler_key in self._CONTEXT_PRODUCER_KEYS
            scored_skills.append((score, skill_name, is_producer))

        # Sort: producers first (at same score), then by score descending
        scored_skills.sort(key=lambda item: (-int(item[2]), -item[0]))
        planned = [name for _, name, _ in scored_skills[:max_skills]]

        if planned:
            logger.info(
                "[PLAN] Skills for %s (intent=%s): %s",
                agent.name, intent,
                ", ".join(f"{name}({score:.1f})" for score, name, _ in scored_skills[:max_skills]),
            )
        return planned

    def _extract_spl(self, user_input: str) -> Optional[str]:
        """Extract SPL query from user input. Delegates to shared utility."""
        from shared.utils import extract_spl_from_text
        return extract_spl_from_text(user_input)

    def _reflect_on_execution(
        self, result: AgentDispatchResult, intent: str,
    ) -> Dict[str, Any]:
        """
        Post-execution self-reflection — assess quality of the dispatch.

        Evaluates:
        - Did skills produce useful output?
        - Was the right agent selected? (check if output mentions different expertise)
        - Should we auto-adjust quality scores?
        """
        reflection: Dict[str, Any] = {
            "skills_succeeded": sum(1 for r in result.skill_results if r.success),
            "skills_failed": sum(1 for r in result.skill_results if not r.success),
            "total_output_chars": len(result.enriched_context),
        }

        # Assess output quality heuristically
        output = result.enriched_context.lower()
        quality_signals = 0
        if len(output) > 100:
            quality_signals += 1  # Non-trivial output
        if any(kw in output for kw in ["error", "exception", "failed"]):
            quality_signals -= 1  # Error indicators
        if any(kw in output for kw in ["recommend", "suggest", "best practice", "example"]):
            quality_signals += 1  # Actionable content
        if result.success and result.skill_results:
            quality_signals += 1  # At least some skills succeeded

        # Score: 0.0 to 1.0
        estimated_quality = max(0.0, min(1.0, (quality_signals + 1) / 4.0))
        reflection["estimated_quality"] = round(estimated_quality, 2)

        # Auto-record quality for learning
        if result.agent_name != "none":
            self.record_quality(result.agent_name, intent, estimated_quality)
            reflection["quality_recorded"] = True

        # Check if a different agent might have been better
        if not result.success and self._last_reasoning.get("top_3"):
            top3 = self._last_reasoning["top_3"]
            if len(top3) > 1:
                reflection["alternative_agent"] = top3[1]["agent"]
                reflection["recommendation"] = (
                    f"Consider {top3[1]['agent']} (score={top3[1]['score']}) "
                    f"as alternative for failed dispatch"
                )
                structured_log(logger, logging.INFO, "AGENT", "delegate",
                               **{
                                   "from": result.agent_name,
                                   "to": top3[1]["agent"],
                                   "reason": "primary_agent_failed",
                               })

        logger.info(
            "[REFLECT] Agent %s: quality=%.2f skills=%d/%d output=%d chars",
            result.agent_name, estimated_quality,
            reflection["skills_succeeded"],
            reflection["skills_succeeded"] + reflection["skills_failed"],
            reflection["total_output_chars"],
        )
        return reflection

    def _record_dispatch(self, result: AgentDispatchResult):
        """Record dispatch for metrics and logging."""
        self._dispatch_log.append({
            "agent_name": result.agent_name,
            "agent_role": result.agent_role,
            "department": result.department,
            "skills_executed": result.skills_executed,
            "success": result.success,
            "duration_ms": round(result.duration_ms, 2),
            "timestamp": time.time(),
            "reasoning": self._last_reasoning,
            "reflection": result.reflection,
        })
        if len(self._dispatch_log) > 200:
            self._dispatch_log = self._dispatch_log[-200:]

        # Persist to execution journal
        try:
            from chat_app.execution_journal import get_journal
            from chat_app.schemas import AgentDispatchEvent
            get_journal().log(AgentDispatchEvent(
                agent_name=result.agent_name,
                department=result.department,
                skills_executed=result.skills_executed,
                success=result.success,
                duration_ms=result.duration_ms,
                error=result.error,
            ))
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # Update per-agent metrics
        if result.agent_name not in self._agent_metrics:
            self._agent_metrics[result.agent_name] = {
                "dispatches": 0, "successes": 0, "total_ms": 0.0,
            }
        metrics = self._agent_metrics[result.agent_name]
        metrics["dispatches"] += 1
        if result.success:
            metrics["successes"] += 1
        metrics["total_ms"] += result.duration_ms

        logger.info(
            "[DISPATCH] Agent %s: %d skills, %s, %.0fms",
            result.agent_name,
            len(result.skills_executed),
            "OK" if result.success else "FAIL",
            result.duration_ms,
        )

        # Record Prometheus metrics
        try:
            from prometheus_metrics import record_agent_dispatch
            quality = result.reflection.get("estimated_quality") if result.reflection else None
            record_agent_dispatch(
                agent_name=result.agent_name,
                department=result.department,
                success=result.success,
                latency=result.duration_ms / 1000.0,
                quality_score=quality,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

    def get_dispatch_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent dispatch log."""
        return self._dispatch_log[-limit:]

    def get_agent_metrics(self) -> Dict[str, Any]:
        """Get per-agent performance metrics."""
        metrics = {}
        for name, m in self._agent_metrics.items():
            quality_data = self._agent_quality.get(name, {})
            all_scores = [s for scores in quality_data.values() for s in scores]
            metrics[name] = {
                "dispatches": m["dispatches"],
                "success_rate": round(
                    m["successes"] / max(m["dispatches"], 1), 4
                ),
                "avg_latency_ms": round(
                    m["total_ms"] / max(m["dispatches"], 1), 2
                ),
                "avg_quality": round(
                    sum(all_scores) / len(all_scores), 3
                ) if all_scores else None,
            }
        return metrics

    def record_quality(self, agent_name: str, intent: str, score: float):
        """Record quality score (0.0-1.0) for an agent's response to an intent."""
        score = max(0.0, min(1.0, score))
        if agent_name not in self._agent_quality:
            self._agent_quality[agent_name] = {}
        if intent not in self._agent_quality[agent_name]:
            self._agent_quality[agent_name][intent] = []
        self._agent_quality[agent_name][intent].append(score)
        # Keep last 30 scores per agent+intent (weight recent higher)
        if len(self._agent_quality[agent_name][intent]) > 30:
            self._agent_quality[agent_name][intent] = self._agent_quality[agent_name][intent][-30:]
        # Persist quality data to Redis
        self._persist_quality()

    def _persist_quality(self):
        """Save agent quality scores to Redis for cross-restart persistence."""
        try:
            import redis
            import json
            from chat_app.settings import get_settings
            cfg = get_settings().cache
            if not cfg.enabled:
                return
            redis_client = redis.Redis(
                host=cfg.host, port=cfg.port, password=cfg.password,
                decode_responses=True, socket_connect_timeout=2,
            )
            redis_client.set("obsai:agent_quality", json.dumps(self._agent_quality), ex=86400 * 30)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

    def _restore_quality(self):
        """Load agent quality scores from Redis on startup."""
        try:
            import redis
            import json
            from chat_app.settings import get_settings
            cfg = get_settings().cache
            if not cfg.enabled:
                return
            redis_client = redis.Redis(
                host=cfg.host, port=cfg.port, password=cfg.password,
                decode_responses=True, socket_connect_timeout=2,
            )
            data = redis_client.get("obsai:agent_quality")
            if data:
                self._agent_quality = json.loads(data)
                total_scores = sum(
                    len(s) for d in self._agent_quality.values() for s in d.values()
                )
                logger.info(
                    "[DISPATCH] Restored %d quality scores for %d agents from Redis",
                    total_scores, len(self._agent_quality),
                )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

    async def collaborate(
        self,
        user_input: str,
        intent: str,
        departments: List[Department] = None,
        params: Dict[str, Any] = None,
        max_agents: int = 3,
    ) -> AgentDispatchResult:
        """
        Multi-agent collaboration: dispatch query to multiple department agents
        in sequence, passing accumulated context between them.

        Each agent's output becomes input context for the next, creating a
        chain of expert perspectives.

        Args:
            user_input: User query
            intent: Classified intent
            departments: Specific departments to consult (auto-detected if None)
            params: Additional parameters
            max_agents: Maximum number of agents to involve

        Returns:
            Combined AgentDispatchResult with all agents' contributions
        """
        start = time.monotonic()
        params = params or {}

        # Auto-detect departments from query keywords if not specified
        if not departments:
            departments = self._detect_departments(user_input)

        # Get one agent per department
        agents_to_run = []
        for dept in departments[:max_agents]:
            agent = self.select_agent(intent, user_input, preferred_department=dept)
            if agent and agent.name not in [a.name for a in agents_to_run]:
                agents_to_run.append(agent)

        if not agents_to_run:
            return AgentDispatchResult(
                agent_name="none", agent_role="none", department="none",
                success=False, error="No suitable agents found for collaboration",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        structured_log(logger, logging.INFO, "COLLAB", "Multi-agent dispatch started",
                       agents=[a.name for a in agents_to_run],
                       departments=[a.department.value for a in agents_to_run],
                       intent=intent)

        # Execute agents sequentially, passing context forward
        all_results: List[SkillExecResult] = []
        all_skills: List[str] = []
        accumulated_context = ""
        combined_prompt = ""

        for agent in agents_to_run:
            # Pass accumulated context from previous agents
            agent_params = {**params, "user_input": user_input, "intent": intent}
            if accumulated_context:
                agent_params["prior_agent_context"] = accumulated_context

            skills = self._plan_agent_skills(agent, intent, user_input, max_skills=3)
            for skill_name in skills:
                skill_params = {**agent_params}
                skill = _get_skill_catalog().get(skill_name)
                if skill and skill.handler_key == "search_knowledge_base":
                    skill_params["query"] = user_input

                result = await self._executor.execute(
                    skill_name=skill_name, params=skill_params,
                )
                all_results.append(result)
                all_skills.append(skill_name)

                if result.success and result.output:
                    accumulated_context += (
                        f"\n\n--- {agent.display_name} ({agent.department.value}) ---\n"
                        f"{result.output}"
                    )

            if agent.get_system_prompt_fragment():
                combined_prompt += f"\n{agent.get_system_prompt_fragment()}\n"

        duration_ms = (time.monotonic() - start) * 1000
        collab_result = AgentDispatchResult(
            agent_name="+".join(a.name for a in agents_to_run),
            agent_role="multi-agent collaboration",
            department="+".join(a.department.value for a in agents_to_run),
            skills_executed=all_skills,
            skill_results=all_results,
            enriched_context=accumulated_context,
            system_prompt_fragment=combined_prompt,
            success=any(r.success for r in all_results),
            duration_ms=duration_ms,
        )

        self._record_dispatch(collab_result)
        logger.info(
            "[COLLAB] Complete: %d agents, %d skills, %d chars context, %.0fms",
            len(agents_to_run), len(all_skills),
            len(accumulated_context), duration_ms,
        )
        return collab_result

    def _detect_departments(self, user_input: str) -> List[Department]:
        """Auto-detect which departments are relevant to a query."""
        input_lower = user_input.lower()
        department_keywords = {
            Department.SECURITY: ["security", "threat", "audit", "compliance", "vulnerability", "access"],
            Department.DATA: ["data", "index", "search", "spl", "query", "report", "dashboard"],
            Department.OPERATIONS: ["deploy", "monitor", "health", "container", "service", "performance"],
            Department.ENGINEERING: ["code", "script", "build", "test", "config", "pipeline", "automation"],
            Department.INFRASTRUCTURE: ["network", "server", "cloud", "platform", "dns", "firewall"],
            Department.KNOWLEDGE: ["document", "learn", "knowledge", "docs", "wiki", "training"],
        }
        scored = []
        for dept, keywords in department_keywords.items():
            matches = sum(1 for keyword in keywords if keyword in input_lower)
            if matches > 0:
                scored.append((matches, dept))
        scored.sort(key=lambda item: -item[0])
        return [dept for _, dept in scored] if scored else [Department.DATA]

    def get_summary(self) -> Dict[str, Any]:
        """Get dispatcher summary."""
        total_dispatches = sum(m["dispatches"] for m in self._agent_metrics.values())
        total_successes = sum(m["successes"] for m in self._agent_metrics.values())
        return {
            "total_dispatches": total_dispatches,
            "total_successes": total_successes,
            "success_rate": round(
                total_successes / max(total_dispatches, 1), 4
            ),
            "unique_agents_used": len(self._agent_metrics),
            "total_agents_available": self._catalog.count,
        }
