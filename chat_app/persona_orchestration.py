"""Persona-Aware Orchestration — match user persona with agent persona.

Bridges user personas (Technical, Executive, Tutorial, Debug, Security) with
agent personas to optimize the orchestration pipeline:
- **Persona matching**: User persona influences agent selection scoring
- **Strategy adaptation**: Persona affects which orchestration strategy is preferred
- **Prompt injection**: Combined user+agent persona modifiers for LLM context
- **Persona versioning**: Track persona changes for audit/debugging

Usage:
    from chat_app.persona_orchestration import get_persona_orchestrator

    po = get_persona_orchestrator()
    match = po.match_agent("technical_expert", "splunk_search", agents)
    strategy = po.recommend_strategy("executive_summary", "config_health_check")
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persona-Agent affinity matrix
# ---------------------------------------------------------------------------

# Maps user persona ID → set of preferred agent departments/expertise
_PERSONA_AGENT_AFFINITY: Dict[str, Dict[str, Any]] = {
    "technical_expert": {
        "preferred_departments": {"engineering", "infrastructure", "data"},
        "preferred_expertise": {"expert", "lead"},
        "strategy_preference": "review_critique",
        "verbosity_weight": 0.0,  # No penalty for verbose agents
        "detail_boost": 1.5,      # Boost agents that give detailed answers
    },
    "executive_summary": {
        "preferred_departments": {"management", "operations"},
        "preferred_expertise": {"lead", "specialist"},
        "strategy_preference": "single_agent",
        "verbosity_weight": -0.5,  # Penalize verbose agents
        "detail_boost": 0.5,
    },
    "tutorial_mode": {
        "preferred_departments": {"knowledge", "support"},
        "preferred_expertise": {"specialist", "generalist"},
        "strategy_preference": "hierarchical",
        "verbosity_weight": 0.5,  # Prefer explanatory agents
        "detail_boost": 1.2,
    },
    "debug_mode": {
        "preferred_departments": {"engineering", "infrastructure", "security"},
        "preferred_expertise": {"expert", "lead"},
        "strategy_preference": "react",
        "verbosity_weight": 0.0,
        "detail_boost": 2.0,  # Maximum detail
    },
    "security_analyst": {
        "preferred_departments": {"security", "infrastructure", "operations"},
        "preferred_expertise": {"expert", "lead"},
        "strategy_preference": "review_critique",
        "verbosity_weight": 0.0,
        "detail_boost": 1.5,
    },
}

# Default for unknown personas
_DEFAULT_AFFINITY = {
    "preferred_departments": set(),
    "preferred_expertise": set(),
    "strategy_preference": "adaptive",
    "verbosity_weight": 0.0,
    "detail_boost": 1.0,
}


# ---------------------------------------------------------------------------
# Persona version tracking
# ---------------------------------------------------------------------------

@dataclass
class PersonaVersion:
    """Tracks a persona change for audit."""
    persona_id: str
    username: str
    changed_at: str
    previous_persona: Optional[str] = None


# ---------------------------------------------------------------------------
# Match result
# ---------------------------------------------------------------------------

@dataclass
class PersonaMatchResult:
    """Result of persona-agent matching."""
    user_persona: str
    recommended_agent: Optional[str] = None
    agent_score_boost: float = 0.0
    recommended_strategy: str = "adaptive"
    prompt_modifiers: List[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_persona": self.user_persona,
            "recommended_agent": self.recommended_agent,
            "agent_score_boost": round(self.agent_score_boost, 2),
            "recommended_strategy": self.recommended_strategy,
            "prompt_modifiers": self.prompt_modifiers,
            "reasoning": self.reasoning,
        }


# ---------------------------------------------------------------------------
# Persona Orchestrator
# ---------------------------------------------------------------------------

class PersonaOrchestrator:
    """Matches user personas with agent personas for optimal orchestration."""

    def __init__(self):
        self._version_history: List[PersonaVersion] = []
        self._lock = threading.Lock()
        self._match_count = 0

    def score_agent(
        self,
        user_persona_id: str,
        agent_department: str,
        agent_expertise: str,
    ) -> float:
        """Compute a persona-affinity score boost for an agent.

        Returns a score modifier (positive = preferred, negative = not preferred).
        This is added to the base agent dispatch score.
        """
        affinity = _PERSONA_AGENT_AFFINITY.get(user_persona_id, _DEFAULT_AFFINITY)
        score = 0.0

        # Department match
        if affinity["preferred_departments"] and agent_department in affinity["preferred_departments"]:
            score += 1.0

        # Expertise match
        if affinity["preferred_expertise"] and agent_expertise in affinity["preferred_expertise"]:
            score += 0.5

        # Detail boost
        score *= affinity.get("detail_boost", 1.0)

        return score

    def recommend_strategy(
        self,
        user_persona_id: str,
        intent: str,
    ) -> str:
        """Recommend an orchestration strategy based on user persona + intent.

        The persona preference is a soft suggestion — resource constraints
        and intent overrides still take precedence in the actual strategy selection.
        """
        affinity = _PERSONA_AGENT_AFFINITY.get(user_persona_id, _DEFAULT_AFFINITY)
        return affinity.get("strategy_preference", "adaptive")

    def match(
        self,
        user_persona_id: str,
        intent: str,
        available_agents: Optional[List[Dict[str, Any]]] = None,
    ) -> PersonaMatchResult:
        """Full persona-aware match: recommend agent + strategy + modifiers.

        Args:
            user_persona_id: The user's active persona ID.
            intent: The classified intent for the query.
            available_agents: Optional list of agent dicts with department/expertise.

        Returns:
            PersonaMatchResult with recommendations.
        """
        self._match_count += 1
        affinity = _PERSONA_AGENT_AFFINITY.get(user_persona_id, _DEFAULT_AFFINITY)
        strategy = affinity.get("strategy_preference", "adaptive")

        # Score agents if provided
        best_agent = None
        best_score = -1.0
        if available_agents:
            for agent in available_agents:
                dept = agent.get("department", "")
                expertise = agent.get("expertise", "")
                score = self.score_agent(user_persona_id, dept, expertise)
                if score > best_score:
                    best_score = score
                    best_agent = agent.get("name")

        # Build prompt modifiers
        modifiers = []
        try:
            from chat_app.user_persona import get_persona_prompt_modifier
            mod = get_persona_prompt_modifier(user_persona_id)
            if mod:
                modifiers.append(mod)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        reasoning_parts = [f"Persona '{user_persona_id}' prefers strategy '{strategy}'"]
        if best_agent:
            reasoning_parts.append(f"best agent match: {best_agent} (boost={best_score:.1f})")
        if affinity.get("preferred_departments"):
            reasoning_parts.append(f"prefers departments: {', '.join(sorted(affinity['preferred_departments']))}")

        return PersonaMatchResult(
            user_persona=user_persona_id,
            recommended_agent=best_agent,
            agent_score_boost=best_score if best_score > 0 else 0.0,
            recommended_strategy=strategy,
            prompt_modifiers=modifiers,
            reasoning="; ".join(reasoning_parts),
        )

    def record_persona_change(
        self,
        username: str,
        new_persona: str,
        previous_persona: Optional[str] = None,
    ) -> PersonaVersion:
        """Record a persona change for version tracking."""
        version = PersonaVersion(
            persona_id=new_persona,
            username=username,
            changed_at=datetime.now(timezone.utc).isoformat(),
            previous_persona=previous_persona,
        )
        with self._lock:
            self._version_history.append(version)
            if len(self._version_history) > 1000:
                self._version_history = self._version_history[-500:]
        return version

    def get_persona_history(self, username: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get persona change history."""
        with self._lock:
            history = list(self._version_history)
        if username:
            history = [v for v in history if v.username == username]
        history.reverse()
        return [
            {"persona_id": v.persona_id, "username": v.username,
             "changed_at": v.changed_at, "previous": v.previous_persona}
            for v in history[:limit]
        ]

    def get_affinity_matrix(self) -> Dict[str, Any]:
        """Get the full persona-agent affinity matrix for UI display."""
        matrix = {}
        for persona_id, affinity in _PERSONA_AGENT_AFFINITY.items():
            matrix[persona_id] = {
                "preferred_departments": sorted(affinity["preferred_departments"]),
                "preferred_expertise": sorted(affinity["preferred_expertise"]),
                "strategy_preference": affinity["strategy_preference"],
                "detail_boost": affinity.get("detail_boost", 1.0),
            }
        return matrix

    def get_stats(self) -> Dict[str, Any]:
        """Get persona orchestration statistics."""
        return {
            "total_matches": self._match_count,
            "version_history_size": len(self._version_history),
            "personas_configured": len(_PERSONA_AGENT_AFFINITY),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[PersonaOrchestrator] = None
_instance_lock = threading.Lock()


def get_persona_orchestrator() -> PersonaOrchestrator:
    """Get the global PersonaOrchestrator singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PersonaOrchestrator()
    return _instance
