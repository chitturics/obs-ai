"""
Base classes for the orchestration strategy system.

Extracted to break circular imports between orchestration_strategies.py
and its strategy implementation modules (strategies_core.py,
strategies_openmaiac.py, governance_strategies.py).

Contents:
    OrchestrationResult  — unified output dataclass returned by every strategy
    OrchestrationStrategy — abstract base class that all strategies implement
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class OrchestrationResult:
    """Unified output from any orchestration strategy."""

    strategy_used: str
    context: str = ""
    system_prompt_fragment: str = ""
    agent_trace: List[Dict[str, Any]] = field(default_factory=list)
    iterations: int = 1
    quality_score: float = 0.0
    duration_ms: float = 0.0
    success: bool = True
    fallback_used: bool = False
    fallback_from: str = ""
    error: Optional[str] = None
    # ADR-003: Clarification protocol — agents may request more info before answering
    clarification_needed: bool = False
    clarification_questions: List[str] = field(default_factory=list)
    clarification_agent: str = ""

    def to_dict(self) -> Dict[str, Any]:
        summary = {
            "strategy_used": self.strategy_used,
            "iterations": self.iterations,
            "quality_score": round(self.quality_score, 4),
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "fallback_used": self.fallback_used,
            "fallback_from": self.fallback_from,
            "trace_steps": len(self.agent_trace),
        }
        if self.error:
            summary["error"] = self.error
        return summary


# ---------------------------------------------------------------------------
# Strategy base class
# ---------------------------------------------------------------------------

class OrchestrationStrategy(ABC):
    """Abstract base for all orchestration strategies."""

    name: str = "base"
    resource_weight: str = "light"  # "light" | "medium" | "heavy"

    @abstractmethod
    async def execute(
        self,
        user_input: str,
        intent: str,
        plan: Any,
        context: Any,
        settings: Any,
        user_approved: bool = False,
    ) -> OrchestrationResult:
        ...

    def is_applicable(self, intent: str, user_input: str) -> bool:
        return True

    def _empty_result(self, reason: str = "") -> OrchestrationResult:
        return OrchestrationResult(
            strategy_used=self.name, success=False, error=reason,
        )
