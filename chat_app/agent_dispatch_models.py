"""
Agent Dispatch Models — Data classes and constants for the Agent Dispatcher.

Extracted from agent_dispatcher.py for size management.
AgentDispatcher imports from this module.

Provides:
- Agent scoring constants (EXPERTISE_SCORE_*, bonus weights, history parameters)
- AgentDispatchResult dataclass
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from chat_app.skill_executor import SkillExecResult


# ---------------------------------------------------------------------------
# Agent Scoring Constants
# ---------------------------------------------------------------------------

EXPERTISE_SCORE_LEAD = 4.0
EXPERTISE_SCORE_EXPERT = 3.0
EXPERTISE_SCORE_SPECIALIST = 2.0
EXPERTISE_SCORE_GENERALIST = 1.0

SKILL_AVAILABILITY_BONUS = 0.3          # Bonus per executable skill the agent has
INTENT_MATCH_BONUS = 1.0               # Bonus when agent explicitly handles this intent
ROLE_KEYWORD_MATCH_BONUS = 0.5         # Bonus when agent's role appears in user query
TAG_MATCH_BONUS = 0.2                  # Bonus per matching tag found in user query
DEPARTMENT_RELEVANCE_BONUS = 0.3       # Bonus when agent's department matches query topics
HISTORICAL_QUALITY_WEIGHT = 1.0        # Max bonus from historical quality scores
SUCCESS_RATE_BONUS = 0.5               # Max bonus for 100% historical success rate
MIN_DISPATCHES_FOR_HISTORY = 3         # Minimum dispatches before history affects scoring
RECENT_QUALITY_WINDOW = 30             # Number of recent quality scores to consider
RECENCY_WEIGHT_INCREMENT = 0.1         # Weight increase per position in quality window


# ---------------------------------------------------------------------------
# Dispatch result
# ---------------------------------------------------------------------------

@dataclass
class AgentDispatchResult:
    """Result of an agent dispatch operation."""
    agent_name: str
    agent_role: str
    department: str
    skills_executed: List[str] = field(default_factory=list)
    skill_results: List[SkillExecResult] = field(default_factory=list)
    enriched_context: str = ""
    system_prompt_fragment: str = ""
    success: bool = True
    error: Optional[str] = None
    duration_ms: float = 0.0
    reflection: Optional[Dict[str, Any]] = None
    # Enterprise: clarification support
    clarification_needed: bool = False
    clarification_questions: List[str] = field(default_factory=list)

    def get_combined_output(self) -> str:
        """Combine all skill results into a single context block."""
        parts = []
        for result in self.skill_results:
            if result.success and result.output:
                parts.append(result.output)
        return "\n\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "department": self.department,
            "skills_executed": self.skills_executed,
            "success": self.success,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "reflection": self.reflection,
        }
