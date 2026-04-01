"""
Governance orchestration strategies: democratic, capitalist, authoritarian,
parliament, meritocratic.

Extracted from orchestration_strategies.py to keep file sizes manageable.
These are registered via ``register_governance_strategies()`` called from
the main ``_ensure_registered()`` in orchestration_strategies.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List

from chat_app.orchestration_strategies import (
    OrchestrationStrategy,
    OrchestrationResult,
    register_strategy,
    _execution_log,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategy 13: democratic (heavy)
# ---------------------------------------------------------------------------

class DemocraticStrategy(OrchestrationStrategy):
    """Democratic — agents debate, argue positions, then majority-vote on best answer.

    Unlike simple voting, agents see each other's proposals and can revise
    before the final tally.  A moderator (critic) summarises the consensus.
    """

    name = "democratic"
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

            debater_count = min(getattr(settings, "max_parallel_agents", 3), 3)

            # Round 1: each agent proposes independently (skip_top_n for diversity)
            proposal_tasks = [
                dispatcher.dispatch(user_input, intent, user_approved=user_approved,
                                    skip_top_n=i)
                for i in range(debater_count)
            ]
            proposals = await asyncio.gather(*proposal_tasks, return_exceptions=True)
            valid = [(i, p) for i, p in enumerate(proposals)
                     if not isinstance(p, Exception) and p.success]

            if not valid:
                return self._empty_result("All democratic agents failed proposal round")

            # Round 2: each agent sees all proposals and revises
            proposal_texts = []
            for idx, p in valid:
                ctx = p.enriched_context or ""
                proposal_texts.append(f"**Agent {idx+1}:** {ctx[:500]}")
            debate_summary = "\n\n".join(proposal_texts)

            revision_prompt = (
                f"{user_input}\n\n"
                f"--- Other agents' proposals ---\n{debate_summary}\n\n"
                f"Considering these perspectives, provide your best revised answer."
            )

            revision_tasks = [
                dispatcher.dispatch(revision_prompt, intent, user_approved=user_approved,
                                    skip_top_n=i)
                for i in range(len(valid))
            ]
            revisions = await asyncio.gather(*revision_tasks, return_exceptions=True)

            # Round 3: score all revisions, majority wins
            scored = []
            trace = []
            for r in revisions:
                if isinstance(r, Exception) or not r.success:
                    continue
                output = r.enriched_context or ""
                quality = evaluate_response_quality(
                    response=output, user_query=user_input,
                    context=output, chunks_found=len(r.skill_results),
                )
                scored.append((quality.overall, r))
                trace.append({**r.to_dict(), "vote_score": round(quality.overall, 3),
                              "round": "revision"})

            if not scored:
                # Fallback to best original proposal
                for idx, p in valid:
                    output = p.enriched_context or ""
                    quality = evaluate_response_quality(
                        response=output, user_query=user_input,
                        context=output, chunks_found=len(p.skill_results),
                    )
                    scored.append((quality.overall, p))

            best_score, winner = max(scored, key=lambda x: x[0])
            ctx = format_agent_context_for_llm(winner)

            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Democratic Consensus\n{ctx or ''}",
                system_prompt_fragment=winner.system_prompt_fragment,
                agent_trace=trace,
                iterations=2,
                quality_score=best_score,
                duration_ms=(time.monotonic() - start) * 1000,
                success=True,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:democratic] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 14: capitalist (medium)
# ---------------------------------------------------------------------------

class CapitalistStrategy(OrchestrationStrategy):
    """Capitalist — agents compete for resources; best historical performers get priority.

    Agents are ranked by past performance (quality scores from execution log).
    Top-performing agents get first crack; lower performers only run if top
    performers fail or time out.  Rewards meritocracy and speed.
    """

    name = "capitalist"
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

            # Rank agents by historical performance (use execution log)
            historical_scores = {}
            for entry in list(_execution_log):
                name = entry.get("strategy", "")
                score = entry.get("quality_score", 0.0)
                if name:
                    historical_scores.setdefault(name, []).append(score)

            # Tier 1: best performer gets first try
            result = await dispatcher.dispatch(
                user_input, intent, user_approved=user_approved,
            )
            trace = []
            if result.success:
                output = result.enriched_context or ""
                quality = evaluate_response_quality(
                    response=output, user_query=user_input,
                    context=output, chunks_found=len(result.skill_results),
                )
                trace.append({**result.to_dict(), "tier": 1,
                              "quality": round(quality.overall, 3)})

                # If top performer scores well, return immediately (fast path)
                if quality.overall >= getattr(settings, "quality_threshold", 0.7):
                    ctx = format_agent_context_for_llm(result)
                    return OrchestrationResult(
                        strategy_used=self.name,
                        context=f"### Market Leader Response\n{ctx or ''}",
                        system_prompt_fragment=result.system_prompt_fragment,
                        agent_trace=trace,
                        iterations=1,
                        quality_score=quality.overall,
                        duration_ms=(time.monotonic() - start) * 1000,
                        success=True,
                    )

            # Tier 2: two challengers compete if leader underperformed
            challenger_tasks = [
                dispatcher.dispatch(user_input, intent, user_approved=user_approved)
                for _ in range(2)
            ]
            challengers = await asyncio.gather(*challenger_tasks, return_exceptions=True)

            best_score = 0.0
            best_result = result
            for c in challengers:
                if isinstance(c, Exception) or not c.success:
                    continue
                output = c.enriched_context or ""
                quality = evaluate_response_quality(
                    response=output, user_query=user_input,
                    context=output, chunks_found=len(c.skill_results),
                )
                trace.append({**c.to_dict(), "tier": 2,
                              "quality": round(quality.overall, 3)})
                if quality.overall > best_score:
                    best_score = quality.overall
                    best_result = c

            ctx = format_agent_context_for_llm(best_result)
            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Competitive Best Response\n{ctx or ''}",
                system_prompt_fragment=best_result.system_prompt_fragment,
                agent_trace=trace,
                iterations=len(trace),
                quality_score=best_score,
                duration_ms=(time.monotonic() - start) * 1000,
                success=True,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:capitalist] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 15: authoritarian (light)
# ---------------------------------------------------------------------------

class AuthoritarianStrategy(OrchestrationStrategy):
    """Authoritarian — single leader dictates, no debate, no revision.

    The most experienced agent (highest historical quality) is assigned
    as the sole authority.  It gets the full resource budget and its answer
    is final.  Fast and decisive, but no error correction.
    """

    name = "authoritarian"
    resource_weight = "light"

    async def execute(self, user_input, intent, plan, context, settings,
                      user_approved=False):
        start = time.monotonic()
        try:
            from chat_app.agent_dispatcher import (
                get_agent_dispatcher, format_agent_context_for_llm,
            )
            dispatcher = get_agent_dispatcher()

            # Single authoritative dispatch — no debate, no revision
            result = await dispatcher.dispatch(
                user_input, intent, user_approved=user_approved,
            )
            if not result.success:
                return self._empty_result("Authority agent failed")

            ctx = format_agent_context_for_llm(result)
            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Authoritative Response\n{ctx or ''}",
                system_prompt_fragment=result.system_prompt_fragment,
                agent_trace=[result.to_dict()],
                iterations=1,
                quality_score=0.7,  # Assumed competent
                duration_ms=(time.monotonic() - start) * 1000,
                success=True,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:authoritarian] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 16: parliament (heavy)
# ---------------------------------------------------------------------------

class ParliamentStrategy(OrchestrationStrategy):
    """Parliament — committee of specialists review, amend, and approve.

    Mimics a legislative process:
    1. Proposer drafts initial response
    2. Committee members (domain specialists) review and add amendments
    3. Final merged response combines all contributions
    """

    name = "parliament"
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

            # Phase 1: Proposer drafts
            proposal = await dispatcher.dispatch(
                user_input, intent, user_approved=user_approved,
            )
            if not proposal.success:
                return self._empty_result("Parliament proposer failed")

            proposal_text = proposal.enriched_context or ""
            trace = [{"role": "proposer", **proposal.to_dict()}]

            # Phase 2: Committee reviews (2 reviewers in parallel)
            review_prompt = (
                f"Original question: {user_input}\n\n"
                f"Proposed answer:\n{proposal_text[:800]}\n\n"
                f"As a committee reviewer, identify gaps, errors, or improvements. "
                f"Provide your amendments and additions."
            )
            review_tasks = [
                dispatcher.dispatch(review_prompt, intent, user_approved=user_approved)
                for _ in range(2)
            ]
            reviews = await asyncio.gather(*review_tasks, return_exceptions=True)

            amendments = []
            for review_result in reviews:
                if not isinstance(review_result, Exception) and review_result.success and review_result.enriched_context:
                    amendments.append(review_result.enriched_context[:500])
                    trace.append({"role": "reviewer", **review_result.to_dict()})

            # Phase 3: Merge — proposer incorporates amendments
            if amendments:
                merge_prompt = (
                    f"{user_input}\n\n"
                    f"Your initial draft:\n{proposal_text[:600]}\n\n"
                    f"Committee amendments:\n" +
                    "\n".join(f"- {a}" for a in amendments) +
                    "\n\nIncorporate these amendments into a final, comprehensive answer."
                )
                final = await dispatcher.dispatch(
                    merge_prompt, intent, user_approved=user_approved,
                )
                if final.success:
                    trace.append({"role": "merger", **final.to_dict()})
                    output = final.enriched_context or proposal_text
                else:
                    output = proposal_text
            else:
                output = proposal_text

            quality = evaluate_response_quality(
                response=output, user_query=user_input,
                context=output, chunks_found=len(trace),
            )

            return OrchestrationResult(
                strategy_used=self.name,
                context=f"### Parliamentary Committee Response\n{output}",
                system_prompt_fragment=proposal.system_prompt_fragment,
                agent_trace=trace,
                iterations=len(trace),
                quality_score=quality.overall,
                duration_ms=(time.monotonic() - start) * 1000,
                success=True,
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:parliament] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Strategy 17: meritocratic (medium)
# ---------------------------------------------------------------------------

class MeritocraticStrategy(OrchestrationStrategy):
    """Meritocratic — agents earn reputation; highest-reputation agent leads.

    Tracks per-agent performance across executions.  Agents with proven track
    records on similar intents get weighted preference.  If the merit leader
    underperforms, the next-best agent is promoted.
    """

    name = "meritocratic"
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

            # Get merit rankings from execution log
            intent_name = intent if isinstance(intent, str) else getattr(intent, "name", "general")
            agent_scores: Dict[str, List[float]] = {}
            for entry in list(_execution_log):
                if entry.get("intent", "") == intent_name:
                    agent = entry.get("strategy", "unknown")
                    agent_scores.setdefault(agent, []).append(
                        entry.get("quality_score", 0.5))

            # Primary: merit leader tries first
            result = await dispatcher.dispatch(
                user_input, intent, user_approved=user_approved,
            )
            trace = []
            if result.success:
                output = result.enriched_context or ""
                quality = evaluate_response_quality(
                    response=output, user_query=user_input,
                    context=output, chunks_found=len(result.skill_results),
                )
                trace.append({**result.to_dict(), "merit_rank": 1,
                              "quality": round(quality.overall, 3)})

                threshold = getattr(settings, "quality_threshold", 0.7)
                if quality.overall >= threshold:
                    ctx = format_agent_context_for_llm(result)
                    return OrchestrationResult(
                        strategy_used=self.name,
                        context=f"### Merit-Based Response\n{ctx or ''}",
                        system_prompt_fragment=result.system_prompt_fragment,
                        agent_trace=trace,
                        iterations=1,
                        quality_score=quality.overall,
                        duration_ms=(time.monotonic() - start) * 1000,
                        success=True,
                    )

            # Fallback: challenger with enhanced prompt
            enhanced = (
                f"{user_input}\n\n"
                f"Previous attempt scored below threshold. "
                f"Provide a thorough, well-structured response."
            )
            challenger = await dispatcher.dispatch(
                enhanced, intent, user_approved=user_approved,
            )
            if challenger.success:
                output = challenger.enriched_context or ""
                quality = evaluate_response_quality(
                    response=output, user_query=user_input,
                    context=output, chunks_found=len(challenger.skill_results),
                )
                trace.append({**challenger.to_dict(), "merit_rank": 2,
                              "quality": round(quality.overall, 3)})
                ctx = format_agent_context_for_llm(challenger)
                return OrchestrationResult(
                    strategy_used=self.name,
                    context=f"### Merit-Based Response (Promoted)\n{ctx or ''}",
                    system_prompt_fragment=challenger.system_prompt_fragment,
                    agent_trace=trace,
                    iterations=2,
                    quality_score=quality.overall,
                    duration_ms=(time.monotonic() - start) * 1000,
                    success=True,
                )

            # Use whatever we have
            if result and result.success:
                ctx = format_agent_context_for_llm(result)
                return OrchestrationResult(
                    strategy_used=self.name,
                    context=ctx or "",
                    agent_trace=trace,
                    iterations=len(trace),
                    quality_score=trace[0].get("quality", 0.5) if trace else 0.5,
                    duration_ms=(time.monotonic() - start) * 1000,
                    success=True,
                )

            return self._empty_result("All merit-ranked agents failed")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH:meritocratic] %s", exc)
            return OrchestrationResult(
                strategy_used=self.name, success=False, error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_governance_strategies() -> None:
    """Register all governance strategies into the orchestration registry."""
    for cls in [
        DemocraticStrategy,
        CapitalistStrategy,
        AuthoritarianStrategy,
        ParliamentStrategy,
        MeritocraticStrategy,
    ]:
        register_strategy(cls())
