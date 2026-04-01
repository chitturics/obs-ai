"""Agent Self-Assessment — structured pre/post execution evaluation.

Before executing: Can I handle this? Do I have enough information?
After executing: Did I answer well? Should I delegate or clarify?

Usage:
    from chat_app.agent_self_assessment import get_assessor

    assessor = get_assessor()

    # Pre-execution: should I proceed or ask for clarification?
    pre = assessor.assess_pre(agent, intent, user_input, available_chunks)
    if pre.should_ask_user:
        # Surface pre.clarification_questions to the user

    # Post-execution: how did I do?
    post = assessor.assess_post(agent, intent, skill_results)
    if post.should_delegate:
        # Hand off to post.delegate_to agent
"""

import logging
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AssessmentResult:
    """Structured self-assessment output."""
    agent_name: str
    phase: str  # "pre" or "post"
    confidence: float = 0.5
    should_ask_user: bool = False
    clarification_questions: List[str] = field(default_factory=list)
    should_delegate: bool = False
    delegate_to: Optional[str] = None
    delegate_reason: str = ""
    knowledge_gaps: List[str] = field(default_factory=list)
    reasoning: List[str] = field(default_factory=list)
    quality_estimate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "agent": self.agent_name,
            "phase": self.phase,
            "confidence": round(self.confidence, 3),
        }
        if self.should_ask_user:
            d["should_ask_user"] = True
            d["clarification_questions"] = self.clarification_questions
        if self.should_delegate:
            d["should_delegate"] = True
            d["delegate_to"] = self.delegate_to
            d["delegate_reason"] = self.delegate_reason
        if self.knowledge_gaps:
            d["knowledge_gaps"] = self.knowledge_gaps
        if self.reasoning:
            d["reasoning"] = self.reasoning
        return d


_CLARIFICATION_THRESHOLD = 0.3  # Below this, ask user
_DELEGATION_THRESHOLD = 0.2     # Below this, delegate
_VAGUE_PATTERNS = [
    re.compile(r"^(how|what|why|help|tell me|show me|can you)\b", re.IGNORECASE),
    re.compile(r"^.{1,15}$"),  # Very short queries
]
_SPECIFIC_PATTERNS = [
    re.compile(r"index\s*=", re.IGNORECASE),
    re.compile(r"\|", re.IGNORECASE),
    re.compile(r"sourcetype\s*=", re.IGNORECASE),
    re.compile(r"\.conf\b", re.IGNORECASE),
]


class AgentSelfAssessor:
    """Structured self-assessment for agents."""

    def __init__(self):
        self._history: deque = deque(maxlen=500)
        self._lock = threading.Lock()

    def assess_pre(
        self,
        agent: Any,
        intent: str,
        user_input: str,
        retrieved_chunks: int = 0,
    ) -> AssessmentResult:
        """Pre-execution assessment: can this agent handle the query?"""
        reasoning = []
        score = 0.5
        questions = []
        gaps = []

        # Check intent alignment
        agent_intents = getattr(agent, "intents", [])
        if intent in agent_intents:
            score += 0.2
            reasoning.append(f"Intent '{intent}' is in agent's intent list")
        elif agent_intents:
            score -= 0.1
            reasoning.append(f"Intent '{intent}' not in agent's intents: {agent_intents[:5]}")

        # Check skill coverage
        agent_skills = getattr(agent, "skills", [])
        if len(agent_skills) >= 3:
            score += 0.1
            reasoning.append(f"Agent has {len(agent_skills)} skills available")
        else:
            reasoning.append(f"Agent has limited skills ({len(agent_skills)})")

        # Check query specificity
        is_vague = any(p.search(user_input) for p in _VAGUE_PATTERNS)
        is_specific = any(p.search(user_input) for p in _SPECIFIC_PATTERNS)

        if is_specific:
            score += 0.15
            reasoning.append("Query contains specific indicators (SPL, conf, index)")
        elif is_vague and len(user_input.split()) < 5:
            score -= 0.15
            reasoning.append("Query is vague — may need clarification")
            questions.append("Could you provide more specific details about what you're looking for?")

        # Check retrieval coverage
        if retrieved_chunks >= 5:
            score += 0.1
            reasoning.append(f"Good retrieval coverage ({retrieved_chunks} chunks)")
        elif retrieved_chunks == 0:
            score -= 0.1
            reasoning.append("No retrieval results — may lack knowledge to answer")
            gaps.append("No relevant documents found in knowledge base")

        # Check data source access
        data_sources = getattr(agent, "data_sources", None)
        if data_sources and not data_sources.collections:
            gaps.append("Agent has no configured data source collections")

        should_ask = score < _CLARIFICATION_THRESHOLD and len(questions) > 0
        should_delegate = score < _DELEGATION_THRESHOLD

        result = AssessmentResult(
            agent_name=getattr(agent, "name", "unknown"),
            phase="pre",
            confidence=min(max(score, 0.0), 1.0),
            should_ask_user=should_ask,
            clarification_questions=questions,
            should_delegate=should_delegate,
            knowledge_gaps=gaps,
            reasoning=reasoning,
        )
        self._record(result)
        return result

    def assess_post(
        self,
        agent: Any,
        intent: str,
        skill_results: List[Any],
        evaluation: Optional[Any] = None,
    ) -> AssessmentResult:
        """Post-execution assessment: how well did the agent perform?"""
        reasoning = []
        score = 0.5
        gaps = []

        # Check skill success rate
        if skill_results:
            successes = sum(1 for r in skill_results if getattr(r, "success", False))
            total = len(skill_results)
            success_rate = successes / total
            score = 0.3 + (success_rate * 0.5)
            reasoning.append(f"Skill success rate: {successes}/{total} ({success_rate*100:.0f}%)")
            if success_rate < 0.5:
                gaps.append(f"{total - successes} skills failed")
        else:
            reasoning.append("No skills were executed")
            score = 0.3

        # Check evaluation if available
        if evaluation:
            eval_conf = getattr(evaluation, "confidence", 0.5)
            score = (score + eval_conf) / 2
            grounding = getattr(evaluation, "grounding", "unknown")
            reasoning.append(f"Evaluation: confidence={eval_conf:.2f}, grounding={grounding}")

        # Determine if delegation needed
        should_delegate = score < _DELEGATION_THRESHOLD
        delegate_to = None
        delegate_reason = ""
        if should_delegate:
            delegate_reason = f"Low post-execution confidence ({score:.2f})"
            reasoning.append("Recommending delegation to a more specialized agent")

        result = AssessmentResult(
            agent_name=getattr(agent, "name", "unknown"),
            phase="post",
            confidence=min(max(score, 0.0), 1.0),
            should_delegate=should_delegate,
            delegate_to=delegate_to,
            delegate_reason=delegate_reason,
            knowledge_gaps=gaps,
            reasoning=reasoning,
            quality_estimate=score,
        )
        self._record(result)
        return result

    def get_history(self, agent_name: Optional[str] = None, limit: int = 50) -> List[Dict]:
        with self._lock:
            history = list(self._history)
        if agent_name:
            history = [h for h in history if h.get("agent") == agent_name]
        history.reverse()
        return history[:limit]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            history = list(self._history)
        if not history:
            return {"total_assessments": 0}
        confs = [h.get("confidence", 0) for h in history]
        return {
            "total_assessments": len(history),
            "avg_confidence": round(sum(confs) / len(confs), 3),
            "clarifications_suggested": sum(1 for h in history if h.get("should_ask_user")),
            "delegations_suggested": sum(1 for h in history if h.get("should_delegate")),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _record(self, result: AssessmentResult) -> None:
        with self._lock:
            self._history.append(result.to_dict())


_instance: Optional[AgentSelfAssessor] = None


def get_assessor() -> AgentSelfAssessor:
    global _instance
    if _instance is None:
        _instance = AgentSelfAssessor()
    return _instance
