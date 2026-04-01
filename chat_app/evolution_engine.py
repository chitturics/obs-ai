"""
Evolution Engine — Continuous Self-Assessment, Diagnosis, and Improvement.

Implements Operations Research (optimization, resource allocation) and Game Theory
(agent competition, strategy payoff matrices, exploration vs exploitation) to drive
the system toward ever-improving quality targets.

The journey: assess → diagnose → plan → act → validate → set new targets → repeat.
Quality targets auto-adjust: when met, they tighten. The destination always moves forward.

Architecture:
    EvolutionEngine (singleton)
    ├── StalenessDetector      — monitors freshness of knowledge, agents, prompts
    ├── RootCauseAnalyzer      — diagnoses WHY quality is declining
    ├── AdaptiveTargetManager  — OR-inspired self-adjusting quality goals
    ├── StrategyPayoffTracker  — Game Theory payoff matrix for orchestration strategies
    ├── AgentCompetition       — Reputation-based agent ranking with UCB1 exploration
    └── EvolutionCycle         — The continuous assess → act loop

Data structures and assessor subsystems: evolution_assessors.py
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------

from chat_app.evolution_assessors import EvolutionAssessorsMixin  # noqa: F401
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


# ---------------------------------------------------------------------------
# Evolution Engine
# ---------------------------------------------------------------------------

class EvolutionEngine(EvolutionAssessorsMixin):
    """
    Core continuous self-assessment and improvement engine.

    Implements the never-ending journey toward perfection:
    1. ASSESS — measure current state against adaptive targets
    2. DIAGNOSE — identify root causes of any gaps
    3. PLAN — prioritize improvement actions by expected impact
    4. ACT — execute improvements (re-ingest, adjust weights, retrain)
    5. VALIDATE — measure impact of changes
    6. EVOLVE — adjust targets, update strategy payoffs, repeat
    """

    STATE_FILE = "/app/data/evolution_state.json"

    def __init__(self):
        self._state = EvolutionState()
        self._targets: Dict[str, AdaptiveTarget] = {}
        self._strategy_payoffs: Dict[str, StrategyPayoff] = {}  # key: "strategy:intent"
        self._agent_reputation: Dict[str, float] = {}  # agent_name → reputation score
        self._agent_plays: Dict[str, int] = defaultdict(int)  # for UCB1
        self._total_plays: int = 0
        self._improvement_queue: List[ImprovementAction] = []
        self._initialized = False

        # Initialize default adaptive targets
        self._init_default_targets()

        # Load persisted state
        self._load_state()

    def _init_default_targets(self):
        """Initialize the targets we're always chasing."""
        defaults = {
            "response_quality": AdaptiveTarget(
                name="response_quality", current_target=0.65, baseline=0.5,
                tighten_step=0.02, relax_step=0.01, min_target=0.4, max_target=0.95,
            ),
            "retrieval_hit_rate": AdaptiveTarget(
                name="retrieval_hit_rate", current_target=0.70, baseline=0.5,
                tighten_step=0.03, relax_step=0.01, min_target=0.3, max_target=0.98,
            ),
            "agent_selection_accuracy": AdaptiveTarget(
                name="agent_selection_accuracy", current_target=0.60, baseline=0.5,
                tighten_step=0.02, relax_step=0.01, min_target=0.3, max_target=0.95,
            ),
            "latency_p95_seconds": AdaptiveTarget(
                name="latency_p95_seconds", current_target=12.0, baseline=15.0,
                tighten_step=-0.5, relax_step=0.3, min_target=3.0, max_target=30.0,
                tighten_threshold=5, relax_threshold=3,
            ),
            "skill_success_rate": AdaptiveTarget(
                name="skill_success_rate", current_target=0.70, baseline=0.6,
                tighten_step=0.02, relax_step=0.01, min_target=0.4, max_target=0.98,
            ),
            "knowledge_coverage": AdaptiveTarget(
                name="knowledge_coverage", current_target=0.60, baseline=0.4,
                tighten_step=0.03, relax_step=0.01, min_target=0.3, max_target=0.95,
            ),
        }
        for name, target in defaults.items():
            if name not in self._targets:
                self._targets[name] = target

    # -----------------------------------------------------------------------
    # Evolution Cycle — The Core Loop
    # -----------------------------------------------------------------------

    async def run_assessment(self) -> Dict[str, Any]:
        """
        Run a full evolution assessment cycle.

        This is the heartbeat of continuous improvement:
        1. Detect staleness across all components
        2. Measure current values against adaptive targets
        3. Diagnose root causes of any gaps
        4. Generate prioritized improvement actions
        5. Update targets based on measurements
        6. Persist state
        """
        cycle_start = time.time()
        result: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_number": self._state.assessment_count + 1,
        }

        # Step 1: Detect staleness
        staleness = await self.detect_staleness()
        stale_count = sum(
            1 for report in staleness
            if report.level in (StalenessLevel.STALE, StalenessLevel.CRITICAL)
        )
        result["staleness"] = {
            "total_components": len(staleness),
            "stale_or_critical": stale_count,
            "components": {report.component: report.level.value for report in staleness},
        }

        # Step 2: Gather current measurements and update targets
        measurements = await self._gather_measurements()
        for name, value in measurements.items():
            if name in self._targets:
                self._targets[name].update(value)
        result["measurements"] = {key: round(value, 4) for key, value in measurements.items()}

        # Step 3: Evaluate targets
        target_status = {}
        gaps = []
        for name, target in self._targets.items():
            gap = target.gap()
            is_met = target.current_value >= target.current_target
            target_status[name] = {
                "target": round(target.current_target, 4),
                "current": round(target.current_value, 4),
                "met": is_met,
                "gap": round(gap, 4),
                "trend": target.trend,
            }
            if not is_met:
                gaps.append((name, gap))

        result["targets"] = target_status
        result["gaps_count"] = len(gaps)

        # Step 4: Diagnose root causes
        if gaps:
            diagnosis = await self.diagnose_root_causes()
            result["diagnosis"] = {
                "primary_cause": diagnosis.primary_cause.value,
                "confidence": round(diagnosis.confidence, 2),
                "evidence": diagnosis.evidence[:5],
                "recommended_actions": diagnosis.recommended_actions[:5],
            }

            # Step 5: Generate improvement actions
            for action_desc in diagnosis.recommended_actions[:3]:
                action = ImprovementAction(
                    action_id=f"ev-{self._state.assessment_count}-{len(self._improvement_queue)}",
                    description=action_desc,
                    priority=ImprovementPriority.HIGH if diagnosis.confidence > 0.5 else ImprovementPriority.MEDIUM,
                    root_cause=diagnosis.primary_cause,
                    expected_impact=diagnosis.confidence * 0.3,
                    component=gaps[0][0] if gaps else "",
                )
                self._improvement_queue.append(action)
        else:
            result["diagnosis"] = {
                "primary_cause": "healthy",
                "confidence": 0.9,
                "evidence": ["All targets met"],
                "recommended_actions": ["Continue monitoring"],
            }

        # Step 6: Update state
        self._state.assessment_count += 1
        self._state.last_assessment = result["timestamp"]
        self._state.targets = {name: target.to_dict() for name, target in self._targets.items()}
        self._state.agent_reputation = dict(self._agent_reputation)

        # Update improvement actions
        self._state.improvement_actions = [
            asdict(action) for action in self._improvement_queue[-50:]
        ]

        # Record cycle
        elapsed_ms = (time.time() - cycle_start) * 1000
        result["elapsed_ms"] = round(elapsed_ms, 1)
        self._state.cycle_history.append({
            "timestamp": result["timestamp"],
            "cycle": result["cycle_number"],
            "gaps": len(gaps),
            "stale": stale_count,
            "elapsed_ms": round(elapsed_ms, 1),
        })
        if len(self._state.cycle_history) > 100:
            self._state.cycle_history = self._state.cycle_history[-100:]

        # Persist
        self._save_state()

        logger.info(
            "[EVOLUTION] Assessment #%d complete: %d gaps, %d stale, %.0fms",
            result["cycle_number"], len(gaps), stale_count, elapsed_ms,
        )

        return result

    async def _gather_measurements(self) -> Dict[str, float]:
        """Gather current metric values from all subsystems."""
        measurements: Dict[str, float] = {}

        # Response quality from observability
        try:
            from chat_app.observability import get_observability_manager
            obs = get_observability_manager()
            slos = obs.get_slo_status()
            for slo in slos:
                if slo.definition.name == "response_quality" and slo.sample_count > 0:
                    measurements["response_quality"] = slo.current_value
                elif slo.definition.name == "response_latency_p95" and slo.sample_count > 0:
                    measurements["latency_p95_seconds"] = slo.current_value
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # Agent selection accuracy from dispatcher
        try:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            dispatcher = get_agent_dispatcher()
            metrics = dispatcher.get_agent_metrics()
            if metrics:
                total_dispatches = sum(m.get("dispatches", 0) for m in metrics.values())
                total_successes = sum(m.get("successes", 0) for m in metrics.values())
                if total_dispatches > 0:
                    measurements["agent_selection_accuracy"] = total_successes / total_dispatches

                # Average quality across agents
                qualities = [m.get("avg_quality", 0) for m in metrics.values() if m.get("avg_quality", 0) > 0]
                if qualities:
                    measurements["response_quality"] = measurements.get(
                        "response_quality", sum(qualities) / len(qualities)
                    )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # Skill success rate
        try:
            from chat_app.skill_executor import get_skill_executor
            executor = get_skill_executor()
            log = executor.get_execution_log()
            if log:
                recent = log[-100:]
                successes = sum(1 for entry in recent if entry.get("success"))
                measurements["skill_success_rate"] = successes / len(recent)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # Retrieval hit rate from learning trend
        try:
            from chat_app.resource_manager import get_learning_trend
            trend = get_learning_trend()
            if trend.get("quality_avg"):
                measurements["retrieval_hit_rate"] = trend["quality_avg"]
            if trend.get("success_rate_avg"):
                measurements["knowledge_coverage"] = trend["success_rate_avg"]
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # GCI Agent quality metrics (factuality, alignment, cohesion)
        try:
            from chat_app.gci_agent import get_gci_agent
            gci = get_gci_agent()
            status = gci.get_status()
            if status.get("total_interactions", 0) > 0:
                # Use GCI overall score (1-10 scale, normalize to 0-1)
                trends = gci.get_agent_trends()
                if trends:
                    avg_overall = sum(t.get("avg_overall", 0) for t in trends) / len(trends)
                    normalized = avg_overall / 10.0  # Convert 1-10 to 0-1
                    # Use GCI data as a secondary signal for response quality
                    if "response_quality" not in measurements:
                        measurements["response_quality"] = normalized
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        # Orchestration execution metrics
        try:
            from chat_app.orchestration_strategies import get_orchestration_summary
            orch_summary = get_orchestration_summary()
            if orch_summary.get("total", 0) > 0:
                # Use orchestration success rate as a signal
                if "skill_success_rate" not in measurements:
                    measurements["skill_success_rate"] = orch_summary.get("success_rate", 0.0)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("%s", exc)

        return measurements

    # -----------------------------------------------------------------------
    # Execute Improvements
    # -----------------------------------------------------------------------

    async def execute_next_improvement(self) -> Optional[Dict[str, Any]]:
        """Execute the highest-priority pending improvement action."""
        pending = [action for action in self._improvement_queue if action.status == "pending"]
        if not pending:
            return None

        # Sort by priority (CRITICAL > HIGH > MEDIUM > LOW)
        priority_order = {
            ImprovementPriority.CRITICAL: 0,
            ImprovementPriority.HIGH: 1,
            ImprovementPriority.MEDIUM: 2,
            ImprovementPriority.LOW: 3,
        }
        pending.sort(key=lambda action: priority_order.get(action.priority, 99))
        action = pending[0]
        action.status = "in_progress"

        try:
            result = await self._execute_action(action)
            action.status = "completed"
            action.completed_at = datetime.now(timezone.utc).isoformat()
            action.result = result
            return {"action": action.description, "result": result, "status": "completed"}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            action.status = "failed"
            action.result = str(exc)
            return {"action": action.description, "result": str(exc), "status": "failed"}

    async def _execute_action(self, action: ImprovementAction) -> str:
        """Execute a specific improvement action."""
        desc_lower = action.description.lower()

        # Action: Rebuild prompt overlay
        if "prompt overlay" in desc_lower or ("rebuild" in desc_lower and "prompt" in desc_lower):
            try:
                from chat_app.self_learning import rebuild_prompt_overlay
                overlay = await rebuild_prompt_overlay(None)
                return f"Prompt overlay rebuilt: {len(overlay or '')} chars"
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                return f"Failed to rebuild overlay: {exc}"

        # Action: Rebuild knowledge graph
        if "knowledge graph" in desc_lower:
            try:
                from chat_app.knowledge_graph import rebuild_knowledge_graph
                await rebuild_knowledge_graph()
                return "Knowledge graph rebuilt"
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                return f"Failed to rebuild KG: {exc}"

        # Action: Evaluate SLOs
        if "slo" in desc_lower or "monitoring" in desc_lower:
            try:
                from chat_app.observability import get_observability_manager
                obs = get_observability_manager()
                alerts = obs.evaluate_alerts()
                return f"SLO evaluation complete: {len(alerts)} alerts fired"
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                return f"SLO evaluation failed: {exc}"

        # Action: Refresh collection weights
        if "collection weight" in desc_lower or "retrieval boost" in desc_lower:
            try:
                from chat_app.self_learning import get_retrieval_boost_scores
                scores = await get_retrieval_boost_scores(None)
                return f"Collection weights refreshed: {len(scores or {})} collections"
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                return f"Weight refresh failed: {exc}"

        return f"Action acknowledged (manual execution needed): {action.description}"

    # -----------------------------------------------------------------------
    # State Persistence
    # -----------------------------------------------------------------------

    def _save_state(self):
        """Persist evolution state to disk."""
        try:
            state_dir = Path(self.STATE_FILE).parent
            state_dir.mkdir(parents=True, exist_ok=True)

            # Serialize strategy payoffs
            self._state.strategy_payoffs = {
                key: {
                    "strategy": payoff.strategy,
                    "intent": payoff.intent,
                    "plays": payoff.plays,
                    "wins": payoff.wins,
                    "total_quality": payoff.total_quality,
                    "total_latency_ms": payoff.total_latency_ms,
                    "last_played": payoff.last_played,
                }
                for key, payoff in self._strategy_payoffs.items()
            }

            # Serialize targets with history
            self._state.targets = {}
            for name, target in self._targets.items():
                target_dict = target.to_dict()
                target_dict["history"] = target.history[-50:]  # Last 50 for persistence
                target_dict["consecutive_met"] = target.consecutive_met
                target_dict["consecutive_missed"] = target.consecutive_missed
                target_dict["baseline"] = target.baseline
                self._state.targets[name] = target_dict

            with open(self.STATE_FILE, "w") as state_file:
                json.dump(asdict(self._state), state_file, indent=2, default=str)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.debug("[EVOLUTION] Failed to save state: %s", exc)

    def _load_state(self):
        """Load evolution state from disk."""
        try:
            if not Path(self.STATE_FILE).exists():
                return

            with open(self.STATE_FILE) as state_file:
                data = json.load(state_file)

            self._state.assessment_count = data.get("assessment_count", 0)
            self._state.last_assessment = data.get("last_assessment", "")
            self._state.staleness_reports = data.get("staleness_reports", [])
            self._state.root_cause_history = data.get("root_cause_history", [])
            self._state.cycle_history = data.get("cycle_history", [])

            # Restore targets
            for name, target_data in data.get("targets", {}).items():
                if name in self._targets:
                    self._targets[name].current_target = target_data.get(
                        "current_target", self._targets[name].current_target
                    )
                    self._targets[name].current_value = target_data.get("current_value", 0)
                    self._targets[name].best_achieved = target_data.get("best_achieved", 0)
                    self._targets[name].baseline = target_data.get("baseline", self._targets[name].baseline)
                    self._targets[name].consecutive_met = target_data.get("consecutive_met", 0)
                    self._targets[name].consecutive_missed = target_data.get("consecutive_missed", 0)
                    self._targets[name].history = target_data.get("history", [])
                    self._targets[name].trend = target_data.get("trend", "unknown")

            # Restore strategy payoffs
            for key, payoff_data in data.get("strategy_payoffs", {}).items():
                self._strategy_payoffs[key] = StrategyPayoff(
                    strategy=payoff_data.get("strategy", ""),
                    intent=payoff_data.get("intent", ""),
                    plays=payoff_data.get("plays", 0),
                    wins=payoff_data.get("wins", 0),
                    total_quality=payoff_data.get("total_quality", 0),
                    total_latency_ms=payoff_data.get("total_latency_ms", 0),
                    last_played=payoff_data.get("last_played", 0),
                )

            # Restore agent reputation
            self._agent_reputation = data.get("agent_reputation", {})
            for name in self._agent_reputation:
                self._agent_plays[name] = self._agent_plays.get(name, 0) or 1
                self._total_plays += self._agent_plays[name]

            # Restore improvement queue
            for action_dict in data.get("improvement_actions", []):
                self._improvement_queue.append(ImprovementAction(
                    action_id=action_dict.get("action_id", ""),
                    description=action_dict.get("description", ""),
                    priority=ImprovementPriority(action_dict.get("priority", "medium")),
                    root_cause=RootCause(action_dict.get("root_cause", "healthy")),
                    expected_impact=action_dict.get("expected_impact", 0),
                    component=action_dict.get("component", ""),
                    status=action_dict.get("status", "pending"),
                    created_at=action_dict.get("created_at", ""),
                    completed_at=action_dict.get("completed_at"),
                    result=action_dict.get("result", ""),
                ))

            logger.info(
                "[EVOLUTION] Restored state: %d assessments, %d targets, %d payoffs, %d agents",
                self._state.assessment_count, len(self._targets),
                len(self._strategy_payoffs), len(self._agent_reputation),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[EVOLUTION] Failed to load state: %s", exc)

    # -----------------------------------------------------------------------
    # Status & Reporting
    # -----------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive evolution status."""
        return {
            "assessment_count": self._state.assessment_count,
            "last_assessment": self._state.last_assessment,
            "targets": {name: target.to_dict() for name, target in self._targets.items()},
            "staleness_summary": {
                "total": len(self._state.staleness_reports),
                "by_level": self._count_by_level(),
            },
            "root_cause_history": self._state.root_cause_history[-10:],
            "improvement_queue": {
                "pending": sum(1 for action in self._improvement_queue if action.status == "pending"),
                "completed": sum(1 for action in self._improvement_queue if action.status == "completed"),
                "failed": sum(1 for action in self._improvement_queue if action.status == "failed"),
            },
            "strategy_payoff_summary": {
                "strategies_tracked": len(self._strategy_payoffs),
                "total_plays": sum(payoff.plays for payoff in self._strategy_payoffs.values()),
            },
            "agent_competition": {
                "agents_ranked": len(self._agent_reputation),
                "top_3": self.get_agent_rankings()[:3],
            },
            "cycle_history": self._state.cycle_history[-10:],
            "philosophy": "The journey never stops. When we reach the destination, we set new targets.",
        }

    def get_targets(self) -> Dict[str, Dict]:
        """Get all adaptive targets with current status."""
        return {name: target.to_dict() for name, target in self._targets.items()}

    def get_improvement_queue(self) -> List[Dict]:
        """Get the prioritized improvement action queue."""
        return [asdict(action) for action in self._improvement_queue[-30:]]

    def _count_by_level(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for report in self._state.staleness_reports:
            counts[report.get("level", "unknown")] += 1
        return dict(counts)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: Optional[EvolutionEngine] = None


def get_evolution_engine() -> EvolutionEngine:
    """Get or create the singleton EvolutionEngine."""
    global _engine
    if _engine is None:
        _engine = EvolutionEngine()
    return _engine
