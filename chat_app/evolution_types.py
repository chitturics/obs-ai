"""
Evolution Types — Enums and data classes for the Evolution Engine.

Extracted from evolution_engine.py for size management.
Both evolution_assessors.py and evolution_engine.py import from this module.

Provides:
- Enums: StalenessLevel, RootCause, ImprovementPriority
- Dataclasses: StalenessReport, RootCauseAnalysis, AdaptiveTarget, ImprovementAction,
               StrategyPayoff, EvolutionState
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StalenessLevel(str, Enum):
    FRESH = "fresh"          # < 1 day since last update
    AGING = "aging"          # 1-3 days
    STALE = "stale"          # 3-7 days
    CRITICAL = "critical"    # > 7 days


class RootCause(str, Enum):
    BAD_PROMPTS = "bad_prompts"                  # High retrieval quality but low response quality
    BAD_INGESTION = "bad_ingestion"              # Low retrieval hits, collections sparse
    HITTING_LIMITS = "hitting_limits"            # Context budget saturated, token limits
    MODEL_DRIFT = "model_drift"                  # Same queries degrading over time
    STALE_KNOWLEDGE = "stale_knowledge"          # Knowledge base outdated
    AGENT_MISMATCH = "agent_mismatch"            # Wrong agents selected for intents
    STRATEGY_SUBOPTIMAL = "strategy_suboptimal"  # Wrong orchestration strategy
    HEALTHY = "healthy"                          # No issues detected


class ImprovementPriority(str, Enum):
    CRITICAL = "critical"    # Fix immediately
    HIGH = "high"            # Fix in next cycle
    MEDIUM = "medium"        # Fix when idle
    LOW = "low"              # Nice to have


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StalenessReport:
    """Staleness assessment for a knowledge component."""
    component: str           # e.g., "collection:spl_docs_mxbai_v2", "knowledge_graph", "agent:spl_expert"
    level: StalenessLevel
    last_updated: Optional[str] = None
    age_hours: float = 0.0
    quality_trend: str = "unknown"     # improving, stable, declining
    hit_rate_trend: str = "unknown"    # improving, stable, declining
    diagnosis: str = ""


@dataclass
class RootCauseAnalysis:
    """Root cause diagnosis for a quality issue."""
    primary_cause: RootCause
    confidence: float = 0.0            # 0.0-1.0
    evidence: List[str] = field(default_factory=list)
    secondary_causes: List[RootCause] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)


@dataclass
class AdaptiveTarget:
    """Self-adjusting quality target (always pushing higher)."""
    name: str
    current_target: float
    baseline: float                    # Starting point when first measured
    best_achieved: float = 0.0         # Highest value ever achieved
    current_value: float = 0.0
    trend: str = "unknown"             # improving, stable, declining
    consecutive_met: int = 0           # How many cycles target was met
    consecutive_missed: int = 0        # How many cycles target was missed
    tighten_threshold: int = 3         # Tighten after N consecutive successes
    relax_threshold: int = 5           # Relax after N consecutive failures
    tighten_step: float = 0.02         # How much to tighten (2%)
    relax_step: float = 0.01           # How much to relax (1%, slower relaxation)
    min_target: float = 0.3            # Never go below this
    max_target: float = 0.98           # Never exceed this
    history: List[Dict[str, Any]] = field(default_factory=list)

    def update(self, measured_value: float):
        """Update target based on measured value. The journey never stops."""
        self.current_value = measured_value
        self.best_achieved = max(self.best_achieved, measured_value)

        # Track trend over recent history
        recent = [h["value"] for h in self.history[-10:]] if self.history else []
        if len(recent) >= 3:
            first_half = sum(recent[:len(recent)//2]) / max(len(recent)//2, 1)
            second_half = sum(recent[len(recent)//2:]) / max(len(recent) - len(recent)//2, 1)
            if second_half > first_half + 0.02:
                self.trend = "improving"
            elif second_half < first_half - 0.02:
                self.trend = "declining"
            else:
                self.trend = "stable"

        is_met = measured_value >= self.current_target

        if is_met:
            self.consecutive_met += 1
            self.consecutive_missed = 0
            # Tighten: when we consistently meet the target, raise the bar
            if self.consecutive_met >= self.tighten_threshold:
                old_target = self.current_target
                self.current_target = min(
                    self.current_target + self.tighten_step,
                    self.max_target,
                )
                self.consecutive_met = 0
                if self.current_target != old_target:
                    logger.info(
                        "[EVOLUTION] Target '%s' tightened: %.2f → %.2f (met %d consecutive times)",
                        self.name, old_target, self.current_target, self.tighten_threshold,
                    )
        else:
            self.consecutive_missed += 1
            self.consecutive_met = 0
            # Relax: slower relaxation to maintain pressure
            if self.consecutive_missed >= self.relax_threshold:
                old_target = self.current_target
                self.current_target = max(
                    self.current_target - self.relax_step,
                    self.min_target,
                )
                self.consecutive_missed = 0
                if self.current_target != old_target:
                    logger.info(
                        "[EVOLUTION] Target '%s' relaxed: %.2f → %.2f (missed %d consecutive times)",
                        self.name, old_target, self.current_target, self.relax_threshold,
                    )

        self.history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "value": round(measured_value, 4),
            "target": round(self.current_target, 4),
            "met": is_met,
        })
        # Keep last 200 history entries
        if len(self.history) > 200:
            self.history = self.history[-200:]

    def gap(self) -> float:
        """Distance from current value to target. Negative = above target."""
        return self.current_target - self.current_value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "current_target": round(self.current_target, 4),
            "current_value": round(self.current_value, 4),
            "baseline": round(self.baseline, 4),
            "best_achieved": round(self.best_achieved, 4),
            "gap": round(self.gap(), 4),
            "trend": self.trend,
            "consecutive_met": self.consecutive_met,
            "consecutive_missed": self.consecutive_missed,
            "history_length": len(self.history),
        }


@dataclass
class ImprovementAction:
    """A prioritized improvement action."""
    action_id: str
    description: str
    priority: ImprovementPriority
    root_cause: RootCause
    expected_impact: float = 0.0       # 0.0-1.0 estimated improvement
    component: str = ""
    status: str = "pending"            # pending, in_progress, completed, failed
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    result: str = ""


@dataclass
class StrategyPayoff:
    """Game Theory payoff record for an orchestration strategy on an intent."""
    strategy: str
    intent: str
    plays: int = 0                     # Times this strategy was used for this intent
    wins: int = 0                      # Times quality was above target
    total_quality: float = 0.0
    total_latency_ms: float = 0.0
    last_played: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / max(self.plays, 1)

    @property
    def avg_quality(self) -> float:
        return self.total_quality / max(self.plays, 1)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(self.plays, 1)


@dataclass
class EvolutionState:
    """Complete evolution state — persisted to disk."""
    last_assessment: str = ""
    assessment_count: int = 0
    targets: Dict[str, Dict] = field(default_factory=dict)
    staleness_reports: List[Dict] = field(default_factory=list)
    root_cause_history: List[Dict] = field(default_factory=list)
    improvement_actions: List[Dict] = field(default_factory=list)
    strategy_payoffs: Dict[str, Dict] = field(default_factory=dict)  # key: "strategy:intent"
    agent_reputation: Dict[str, float] = field(default_factory=dict)
    cycle_history: List[Dict] = field(default_factory=list)
