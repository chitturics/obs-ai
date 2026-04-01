"""
Evolution Assessors — Assessment subsystems for the Evolution Engine.

Extracted from evolution_engine.py for size management.
EvolutionEngine imports EvolutionAssessorsMixin from this module.

Provides:
- Re-exports all types from evolution_types for backward compatibility
- EvolutionAssessorsMixin — staleness detection, root-cause analysis,
  strategy payoff matrix, and agent competition methods
"""
from __future__ import annotations

import logging
import math
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chat_app.evolution_types import (  # noqa: F401
    AdaptiveTarget,
    EvolutionState,
    ImprovementAction,
    ImprovementPriority,
    RootCause,
    RootCauseAnalysis,
    StalenessLevel,
    StalenessReport,
    StrategyPayoff,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Assessor Mixin — staleness, root-cause, strategy payoff, agent competition
# ---------------------------------------------------------------------------

class EvolutionAssessorsMixin:
    """
    Mixin providing staleness detection, root-cause analysis,
    strategy payoff matrix, and agent competition methods.

    Expects the host class to provide:
    - self._targets: Dict[str, AdaptiveTarget]
    - self._state: EvolutionState
    - self._strategy_payoffs: Dict[str, StrategyPayoff]
    - self._agent_reputation: Dict[str, float]
    - self._agent_plays: Dict[str, int]
    - self._total_plays: int
    """

    # -----------------------------------------------------------------------
    # Staleness Detection
    # -----------------------------------------------------------------------

    async def detect_staleness(self) -> List[StalenessReport]:
        """Detect staleness across all knowledge components."""
        reports = []

        # 1. Collection staleness
        reports.extend(await self._check_collection_staleness())

        # 2. Knowledge graph staleness
        reports.append(await self._check_kg_staleness())

        # 3. Agent quality staleness
        reports.extend(await self._check_agent_staleness())

        # 4. Prompt overlay staleness
        reports.append(await self._check_prompt_staleness())

        # 5. Learning cycle staleness
        reports.append(await self._check_learning_staleness())

        self._state.staleness_reports = [
            {key: (value.value if hasattr(value, 'value') else value) for key, value in vars(report).items()}
            for report in reports
        ]
        return reports

    async def _check_collection_staleness(self) -> List[StalenessReport]:
        """Check each collection for freshness and effectiveness."""
        reports = []
        try:
            import chromadb
            chroma_url = os.environ.get("CHROMA_HTTP_URL", "http://localhost:8001")
            from urllib.parse import urlparse
            parsed = urlparse(chroma_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8001
            client = chromadb.HttpClient(host=host, port=port)
            collections = client.list_collections()

            for coll in collections:
                name = coll if isinstance(coll, str) else getattr(coll, 'name', str(coll))
                try:
                    col_obj = client.get_collection(name) if isinstance(coll, str) else coll
                    count = col_obj.count()
                except Exception:  # broad catch — resilience at boundary
                    count = 0
                level = StalenessLevel.FRESH if count > 50 else (
                    StalenessLevel.AGING if count > 10 else StalenessLevel.STALE
                )
                reports.append(StalenessReport(
                    component=f"collection:{name}",
                    level=level,
                    diagnosis=f"{count} documents" if count > 0 else "Empty collection — needs ingestion",
                ))

            if not collections:
                reports.append(StalenessReport(
                    component="collections",
                    level=StalenessLevel.CRITICAL,
                    diagnosis="No collections found in ChromaDB",
                ))
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[EVOLUTION] Collection staleness check failed: %s", exc)
            reports.append(StalenessReport(
                component="collections",
                level=StalenessLevel.CRITICAL,
                diagnosis=f"Cannot check collections: {exc}",
            ))
        return reports

    async def _check_kg_staleness(self) -> StalenessReport:
        """Check knowledge graph freshness."""
        try:
            kg_file = Path("/app/data/knowledge_graph.json")
            if kg_file.exists():
                age_hours = (time.time() - kg_file.stat().st_mtime) / 3600
                level = (
                    StalenessLevel.FRESH if age_hours < 24 else
                    StalenessLevel.AGING if age_hours < 72 else
                    StalenessLevel.STALE if age_hours < 168 else
                    StalenessLevel.CRITICAL
                )
                return StalenessReport(
                    component="knowledge_graph",
                    level=level,
                    age_hours=round(age_hours, 1),
                    last_updated=datetime.fromtimestamp(
                        kg_file.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                    diagnosis=f"KG file age: {age_hours:.0f}h" + (
                        " — consider rebuild"
                        if level in (StalenessLevel.STALE, StalenessLevel.CRITICAL) else ""
                    ),
                )
            return StalenessReport(
                component="knowledge_graph",
                level=StalenessLevel.CRITICAL,
                diagnosis="KG file missing — needs initial build",
            )
        except (OSError, ValueError) as exc:
            return StalenessReport(
                component="knowledge_graph",
                level=StalenessLevel.CRITICAL,
                diagnosis=f"Cannot check KG: {exc}",
            )

    async def _check_agent_staleness(self) -> List[StalenessReport]:
        """Check agent quality freshness — are agents still performing well?"""
        reports = []
        try:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            dispatcher = get_agent_dispatcher()
            metrics = dispatcher.get_agent_metrics()

            for agent_name, data in metrics.items():
                dispatches = data.get("dispatches", 0)
                quality = data.get("avg_quality", 0)
                success = data.get("success_rate", 0)

                if dispatches < 5:
                    level = StalenessLevel.AGING
                    diag = f"Insufficient data ({dispatches} dispatches)"
                elif quality < 0.4:
                    level = StalenessLevel.CRITICAL
                    diag = f"Poor quality ({quality:.2f}) over {dispatches} dispatches"
                elif quality < 0.6:
                    level = StalenessLevel.STALE
                    diag = f"Below-average quality ({quality:.2f})"
                else:
                    level = StalenessLevel.FRESH
                    diag = f"Healthy: quality={quality:.2f}, success={success:.2f}"

                reports.append(StalenessReport(
                    component=f"agent:{agent_name}",
                    level=level,
                    quality_trend="declining" if quality < 0.5 else "stable",
                    diagnosis=diag,
                ))
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[EVOLUTION] Agent staleness check failed: %s", exc)
        return reports

    async def _check_prompt_staleness(self) -> StalenessReport:
        """Check if prompt overlay is current."""
        try:
            from chat_app.self_learning import get_dynamic_prompt_overlay
            overlay = get_dynamic_prompt_overlay()
            if overlay and len(overlay) > 50:
                return StalenessReport(
                    component="prompt_overlay",
                    level=StalenessLevel.FRESH,
                    diagnosis=f"Active overlay: {len(overlay)} chars",
                )
            return StalenessReport(
                component="prompt_overlay",
                level=StalenessLevel.STALE,
                diagnosis="No prompt overlay — learning cycle may not have run",
            )
        except Exception:  # broad catch — resilience at boundary
            return StalenessReport(
                component="prompt_overlay",
                level=StalenessLevel.AGING,
                diagnosis="Cannot check overlay",
            )

    async def _check_learning_staleness(self) -> StalenessReport:
        """Check when the last learning cycle ran."""
        try:
            report_file = Path("/app/data/learning_report.json")
            if report_file.exists():
                age_hours = (time.time() - report_file.stat().st_mtime) / 3600
                level = (
                    StalenessLevel.FRESH if age_hours < 24 else
                    StalenessLevel.AGING if age_hours < 72 else
                    StalenessLevel.STALE if age_hours < 168 else
                    StalenessLevel.CRITICAL
                )
                return StalenessReport(
                    component="learning_cycle",
                    level=level,
                    age_hours=round(age_hours, 1),
                    last_updated=datetime.fromtimestamp(
                        report_file.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                    diagnosis=f"Last learning cycle: {age_hours:.0f}h ago",
                )
            return StalenessReport(
                component="learning_cycle",
                level=StalenessLevel.CRITICAL,
                diagnosis="No learning report found — learning cycle never ran",
            )
        except (OSError, ValueError) as exc:
            return StalenessReport(
                component="learning_cycle",
                level=StalenessLevel.CRITICAL,
                diagnosis=f"Cannot check learning state: {exc}",
            )

    # -----------------------------------------------------------------------
    # Root Cause Analysis
    # -----------------------------------------------------------------------

    async def diagnose_root_causes(self) -> RootCauseAnalysis:
        """
        Diagnose WHY quality is below target.

        Cross-references multiple signals to triangulate the root cause:
        - High retrieval + low quality → bad prompts
        - Low retrieval + any quality → bad ingestion
        - Quality declining over time → model drift
        - Context always at budget → hitting limits
        """
        evidence = []
        causes: Dict[RootCause, float] = defaultdict(float)

        # Gather signals
        quality_val = self._targets.get(
            "response_quality", AdaptiveTarget(name="rq", current_target=0.5, baseline=0.5)
        ).current_value
        retrieval_val = self._targets.get(
            "retrieval_hit_rate", AdaptiveTarget(name="rh", current_target=0.5, baseline=0.5)
        ).current_value
        agent_val = self._targets.get(
            "agent_selection_accuracy", AdaptiveTarget(name="aa", current_target=0.5, baseline=0.5)
        ).current_value

        quality_trend = self._targets.get(
            "response_quality", AdaptiveTarget(name="rq", current_target=0.5, baseline=0.5)
        ).trend
        retrieval_trend = self._targets.get(
            "retrieval_hit_rate", AdaptiveTarget(name="rh", current_target=0.5, baseline=0.5)
        ).trend

        # Signal 1: High retrieval but low quality → bad prompts
        if retrieval_val > 0.6 and quality_val < 0.5:
            causes[RootCause.BAD_PROMPTS] += 0.4
            evidence.append(
                f"Retrieval hit rate ({retrieval_val:.2f}) is decent but response quality "
                f"({quality_val:.2f}) is low — prompts may not be extracting value from context"
            )

        # Signal 2: Low retrieval → bad ingestion or stale knowledge
        if retrieval_val < 0.4:
            causes[RootCause.BAD_INGESTION] += 0.3
            causes[RootCause.STALE_KNOWLEDGE] += 0.2
            evidence.append(
                f"Retrieval hit rate ({retrieval_val:.2f}) is low — collections may be sparse or poorly indexed"
            )

        # Signal 3: Quality declining → model drift
        if quality_trend == "declining":
            causes[RootCause.MODEL_DRIFT] += 0.3
            evidence.append(
                "Response quality trend is declining — model may be drifting or prompt overlay degrading"
            )

        # Signal 4: Both retrieval and quality declining → stale knowledge
        if quality_trend == "declining" and retrieval_trend == "declining":
            causes[RootCause.STALE_KNOWLEDGE] += 0.3
            evidence.append("Both quality and retrieval declining — knowledge base likely outdated")

        # Signal 5: Agent selection accuracy low → agent mismatch
        if agent_val < 0.5:
            causes[RootCause.AGENT_MISMATCH] += 0.25
            evidence.append(
                f"Agent selection accuracy ({agent_val:.2f}) is low — wrong agents being dispatched"
            )

        # Signal 6: Check staleness reports for critical components
        stale_critical = [
            report for report in self._state.staleness_reports
            if report.get("level") in ("critical", "stale")
        ]
        if len(stale_critical) >= 3:
            causes[RootCause.STALE_KNOWLEDGE] += 0.2
            evidence.append(f"{len(stale_critical)} components are stale/critical")

        # Determine primary cause
        if not causes:
            return RootCauseAnalysis(
                primary_cause=RootCause.HEALTHY,
                confidence=0.8,
                evidence=["All signals within normal range"],
            )

        sorted_causes = sorted(causes.items(), key=lambda item: item[1], reverse=True)
        primary = sorted_causes[0]
        secondary = [cause for cause, weight in sorted_causes[1:3] if weight > 0.15]

        # Generate recommended actions based on root cause
        actions = self._recommend_actions(primary[0], secondary)

        analysis = RootCauseAnalysis(
            primary_cause=primary[0],
            confidence=min(primary[1], 1.0),
            evidence=evidence,
            secondary_causes=secondary,
            recommended_actions=actions,
        )

        self._state.root_cause_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "primary": primary[0].value,
            "confidence": round(primary[1], 2),
            "evidence_count": len(evidence),
            "actions_count": len(actions),
        })
        # Keep last 50
        if len(self._state.root_cause_history) > 50:
            self._state.root_cause_history = self._state.root_cause_history[-50:]

        return analysis

    def _recommend_actions(self, primary: RootCause, secondary: List[RootCause]) -> List[str]:
        """Generate actionable recommendations based on root cause."""
        action_map = {
            RootCause.BAD_PROMPTS: [
                "Review and update system prompt template",
                "Rebuild prompt overlay from recent feedback",
                "Check if context compression is cutting relevant content",
                "Increase max_tokens budget for LLM context",
            ],
            RootCause.BAD_INGESTION: [
                "Trigger full re-ingestion of document directories",
                "Check document formats — ensure parsers handle all file types",
                "Verify ChromaDB health and collection integrity",
                "Review chunking parameters (token size, overlap)",
            ],
            RootCause.HITTING_LIMITS: [
                "Increase context budget (max_tokens in config)",
                "Improve context compression quality",
                "Reduce k_multiplier to focus on higher-quality chunks",
                "Enable reranking to better prioritize chunks",
            ],
            RootCause.MODEL_DRIFT: [
                "Run model customization with latest Q&A pairs",
                "Check Ollama model version — may need update",
                "Review negative feedback patterns for systematic issues",
                "Reset prompt overlay and rebuild from scratch",
            ],
            RootCause.STALE_KNOWLEDGE: [
                "Run full learning cycle immediately",
                "Trigger document re-ingestion for changed files",
                "Rebuild knowledge graph from sources",
                "Update collection weights from recent feedback",
            ],
            RootCause.AGENT_MISMATCH: [
                "Review agent-intent mapping quality scores",
                "Increase exploration rate for agent selection",
                "Check if new intents need dedicated agents",
                "Review agent expertise tags for accuracy",
            ],
            RootCause.STRATEGY_SUBOPTIMAL: [
                "Review strategy payoff matrix for each intent",
                "Consider switching default strategy based on performance data",
                "Enable adaptive strategy selection",
                "Increase strategy exploration rate",
            ],
            RootCause.HEALTHY: [
                "Continue monitoring — all systems nominal",
            ],
        }
        result = action_map.get(primary, ["Investigate manually"])
        for secondary_cause in secondary[:1]:
            result.extend(action_map.get(secondary_cause, [])[:2])
        return result

    # -----------------------------------------------------------------------
    # Strategy Payoff Matrix (Game Theory)
    # -----------------------------------------------------------------------

    def record_strategy_outcome(
        self,
        strategy: str,
        intent: str,
        quality: float,
        latency_ms: float,
        quality_target: float = 0.6,
    ):
        """Record the outcome of using a strategy for an intent (payoff matrix entry)."""
        key = f"{strategy}:{intent}"
        if key not in self._strategy_payoffs:
            self._strategy_payoffs[key] = StrategyPayoff(strategy=strategy, intent=intent)

        payoff = self._strategy_payoffs[key]
        payoff.plays += 1
        payoff.total_quality += quality
        payoff.total_latency_ms += latency_ms
        payoff.last_played = time.time()
        if quality >= quality_target:
            payoff.wins += 1

    def get_best_strategy_for_intent(self, intent: str, exploration_rate: float = 0.1) -> Optional[str]:
        """
        UCB1-based strategy selection — balances exploitation (best known) with exploration.

        UCB1 = avg_quality + C * sqrt(ln(N) / n_i)
        where N = total plays, n_i = plays of this strategy, C = exploration parameter.
        """
        import random

        candidates = {key: value for key, value in self._strategy_payoffs.items() if value.intent == intent}
        if not candidates:
            return None

        total_plays = sum(value.plays for value in candidates.values())
        if total_plays < 5:
            # Too little data — explore randomly
            return random.choice(list(candidates.values())).strategy

        # Epsilon-greedy exploration
        if random.random() < exploration_rate:
            return random.choice(list(candidates.values())).strategy

        # UCB1 selection
        best_score = -1.0
        best_strategy = None
        exploration_constant = 1.41  # sqrt(2), standard UCB1 exploration parameter

        for payoff in candidates.values():
            if payoff.plays == 0:
                return payoff.strategy  # Untried strategy gets priority

            avg_quality = payoff.avg_quality
            exploration_bonus = exploration_constant * math.sqrt(math.log(total_plays) / payoff.plays)
            ucb_score = avg_quality + exploration_bonus

            if ucb_score > best_score:
                best_score = ucb_score
                best_strategy = payoff.strategy

        return best_strategy

    def get_strategy_payoff_matrix(self) -> Dict[str, Any]:
        """Get the full strategy payoff matrix for analysis."""
        matrix: Dict[str, Dict] = defaultdict(dict)
        for key, payoff in self._strategy_payoffs.items():
            matrix[payoff.intent][payoff.strategy] = {
                "plays": payoff.plays,
                "wins": payoff.wins,
                "win_rate": round(payoff.win_rate, 3),
                "avg_quality": round(payoff.avg_quality, 3),
                "avg_latency_ms": round(payoff.avg_latency_ms, 1),
            }

        # Find Nash equilibria (dominant strategies per intent)
        nash = {}
        for intent, strategies in matrix.items():
            if strategies:
                best = max(strategies.items(), key=lambda item: item[1]["avg_quality"])
                nash[intent] = {
                    "dominant_strategy": best[0],
                    "avg_quality": best[1]["avg_quality"],
                    "plays": best[1]["plays"],
                }

        return {
            "matrix": dict(matrix),
            "nash_equilibria": nash,
            "total_strategies_tracked": len(self._strategy_payoffs),
        }

    # -----------------------------------------------------------------------
    # Agent Competition (Reputation System)
    # -----------------------------------------------------------------------

    def record_agent_outcome(self, agent_name: str, quality: float, success: bool):
        """Update agent reputation based on outcome. Agents compete for dispatch."""
        # Exponential moving average for reputation
        learning_rate = 0.15  # How quickly reputation adjusts to new outcomes
        current = self._agent_reputation.get(agent_name, 0.5)
        reward = quality if success else quality * 0.5
        self._agent_reputation[agent_name] = current * (1 - learning_rate) + reward * learning_rate
        self._agent_plays[agent_name] = self._agent_plays.get(agent_name, 0) + 1
        self._total_plays += 1

    def get_agent_ucb1_scores(self) -> Dict[str, float]:
        """
        Get UCB1 exploration-exploitation scores for all agents.

        Agents with high reputation AND low play count get boosted (exploration).
        """
        scores = {}
        exploration_constant = 1.41
        for name, reputation in self._agent_reputation.items():
            plays = self._agent_plays.get(name, 1)
            if self._total_plays > 0 and plays > 0:
                exploration = exploration_constant * math.sqrt(math.log(self._total_plays) / plays)
            else:
                exploration = 1.0  # High exploration for new agents
            scores[name] = round(reputation + exploration, 4)
        return scores

    def get_agent_rankings(self) -> List[Dict[str, Any]]:
        """Get agents ranked by reputation (competitive leaderboard)."""
        rankings = []
        for name, reputation in sorted(
            self._agent_reputation.items(), key=lambda item: item[1], reverse=True
        ):
            rankings.append({
                "agent": name,
                "reputation": round(reputation, 4),
                "plays": self._agent_plays.get(name, 0),
                "ucb1_score": self.get_agent_ucb1_scores().get(name, 0),
            })
        return rankings
