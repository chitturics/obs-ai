"""Toolformer-Style Tool Use — model learns when to call tools vs answer from memory.

Scores each query to decide whether tool execution would improve the response,
or if the LLM can answer directly from its knowledge. This prevents unnecessary
tool calls and improves response latency for simple questions.

Scoring factors:
- **Query complexity**: Simple factual vs multi-step analytical
- **Tool history**: How often this intent benefits from tools
- **Retrieval quality**: If RAG already has good coverage
- **Confidence threshold**: Only call tools when expected improvement > threshold

Usage:
    from chat_app.toolformer import get_tool_decision_engine

    engine = get_tool_decision_engine()
    decision = engine.should_use_tools(
        query="What is the stats command?",
        intent="spl_help",
        retrieval_score=0.85,
    )
    if decision.use_tools:
        # Execute tools
    else:
        # Answer from LLM knowledge + retrieval only
"""

import logging
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool decision result
# ---------------------------------------------------------------------------

@dataclass
class ToolDecision:
    """Decision on whether to invoke tools for a query."""
    use_tools: bool
    confidence: float  # 0.0 to 1.0 — how confident we are in the decision
    reason: str
    recommended_tools: List[str] = field(default_factory=list)
    skip_reason: Optional[str] = None  # Why tools were skipped

    def to_dict(self) -> Dict[str, Any]:
        return {
            "use_tools": self.use_tools,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "recommended_tools": self.recommended_tools,
            "skip_reason": self.skip_reason,
        }


# ---------------------------------------------------------------------------
# Intent-to-tool-need mapping (learned defaults)
# ---------------------------------------------------------------------------

# How often each intent benefits from tool execution (0.0 = never, 1.0 = always)
_INTENT_TOOL_NEED: Dict[str, float] = {
    # Always need tools
    "splunk_search": 1.0,
    "saved_search": 0.9,
    "splunk_admin": 0.9,
    "config_health_check": 0.95,
    "data_transform": 0.8,
    "observability": 0.85,
    "cribl_admin": 0.9,

    # Sometimes need tools
    "spl_explain": 0.3,   # Can often explain from knowledge
    "spl_help": 0.2,      # Mostly RAG/knowledge
    "general": 0.15,      # Rarely needs tools
    "greeting": 0.0,      # Never needs tools
    "feedback": 0.0,
    "tutorial": 0.1,

    # Moderate tool need
    "config_analysis": 0.7,
    "migration": 0.6,
    "security": 0.7,
}

# Complexity indicators that suggest tool use
_COMPLEXITY_PATTERNS: List[re.Pattern] = [
    re.compile(r'\bindex\s*=', re.IGNORECASE),       # SPL query
    re.compile(r'\|\s*\w+'),                          # Piped commands
    re.compile(r'\bsearch\b.*\bfor\b', re.IGNORECASE),  # Search requests
    re.compile(r'\bcheck\b.*\b(health|status)\b', re.IGNORECASE),  # Health checks
    re.compile(r'\blist\b.*\b(all|every)\b', re.IGNORECASE),  # List operations
    re.compile(r'\bdelete\b|\bremove\b|\brestart\b', re.IGNORECASE),  # Destructive ops
    re.compile(r'\bdeploy\b|\brollback\b|\bmigrate\b', re.IGNORECASE),  # Deployment ops
    re.compile(r'\bcompare\b|\bdiff\b|\banalyze\b', re.IGNORECASE),  # Analysis ops
]

# Simple question indicators (don't need tools)
_SIMPLE_PATTERNS: List[re.Pattern] = [
    re.compile(r'^(what|how)\s+(is|does|do)\s+\w+', re.IGNORECASE),  # Definition questions
    re.compile(r'^explain\s+', re.IGNORECASE),         # Explain requests
    re.compile(r'^(hi|hello|hey|thanks|thank)', re.IGNORECASE),  # Greetings
    re.compile(r'^(show|tell)\s+me\s+(about|what)', re.IGNORECASE),  # Info requests
]

_TOOL_USE_THRESHOLD = 0.5  # Use tools if score > this


# ---------------------------------------------------------------------------
# Tool Decision Engine
# ---------------------------------------------------------------------------

class ToolDecisionEngine:
    """Decides when to use tools vs answer from LLM knowledge."""

    def __init__(self):
        self._lock = threading.Lock()
        # Track tool use outcomes for learning
        self._tool_outcomes: Dict[str, Dict[str, int]] = defaultdict(lambda: {"used": 0, "skipped": 0, "tool_helped": 0, "tool_wasted": 0})
        self._total_decisions = 0

    def should_use_tools(
        self,
        query: str,
        intent: str = "general",
        retrieval_score: float = 0.0,
        available_tools: Optional[List[str]] = None,
        user_explicitly_requested: bool = False,
    ) -> ToolDecision:
        """Decide whether to invoke tools for a query.

        Args:
            query: The user's input.
            intent: Classified intent.
            retrieval_score: How good the RAG retrieval was (0-1).
            available_tools: Tools that could be used.
            user_explicitly_requested: User asked for a specific tool action.

        Returns:
            ToolDecision with use_tools flag and reasoning.
        """
        self._total_decisions += 1

        # Explicit user request always uses tools
        if user_explicitly_requested:
            return ToolDecision(
                use_tools=True,
                confidence=1.0,
                reason="User explicitly requested tool execution",
                recommended_tools=available_tools or [],
            )

        # Compute tool need score
        scores = {}

        # 1. Intent-based need
        intent_need = _INTENT_TOOL_NEED.get(intent, 0.3)
        scores["intent"] = intent_need

        # 2. Query complexity
        complexity = self._score_complexity(query)
        scores["complexity"] = complexity

        # 3. Retrieval coverage (high retrieval = less tool need)
        retrieval_factor = max(0, 1.0 - retrieval_score)
        scores["retrieval_gap"] = retrieval_factor * 0.5

        # 4. Historical tool effectiveness for this intent
        history_score = self._get_historical_score(intent)
        scores["history"] = history_score

        # Weighted combination
        weights = {"intent": 0.40, "complexity": 0.25, "retrieval_gap": 0.20, "history": 0.15}
        total_score = sum(scores[k] * weights[k] for k in weights)

        use_tools = total_score > _TOOL_USE_THRESHOLD

        # Build reasoning
        reason_parts = []
        if intent_need > 0.7:
            reason_parts.append(f"intent '{intent}' typically needs tools")
        if complexity > 0.5:
            reason_parts.append("query is complex/action-oriented")
        if retrieval_score > 0.7:
            reason_parts.append("good retrieval coverage available")
        if not reason_parts:
            reason_parts.append("standard heuristic scoring")

        return ToolDecision(
            use_tools=use_tools,
            confidence=abs(total_score - _TOOL_USE_THRESHOLD) + 0.5,
            reason="; ".join(reason_parts),
            recommended_tools=available_tools[:5] if available_tools and use_tools else [],
            skip_reason=None if use_tools else self._skip_reason(scores),
        )

    def _score_complexity(self, query: str) -> float:
        """Score query complexity (0 = simple, 1 = complex)."""
        complex_matches = sum(1 for p in _COMPLEXITY_PATTERNS if p.search(query))
        simple_matches = sum(1 for p in _SIMPLE_PATTERNS if p.search(query))

        if simple_matches > 0 and complex_matches == 0:
            return 0.1
        if complex_matches >= 3:
            return 0.9
        if complex_matches >= 1:
            return 0.5 + (complex_matches * 0.1)
        return 0.3  # Default moderate complexity

    def _get_historical_score(self, intent: str) -> float:
        """Get historical tool effectiveness for an intent."""
        outcomes = self._tool_outcomes.get(intent)
        if not outcomes or outcomes["used"] == 0:
            return 0.5  # No data, neutral
        total = outcomes["used"]
        helped = outcomes.get("tool_helped", 0)
        return helped / total if total > 0 else 0.5

    def _skip_reason(self, scores: Dict[str, float]) -> str:
        """Generate reason for skipping tools."""
        if scores["intent"] < 0.2:
            return "Intent rarely benefits from tools"
        if scores["retrieval_gap"] < 0.15:
            return "Good retrieval coverage — tools unlikely to add value"
        if scores["complexity"] < 0.2:
            return "Simple question — LLM knowledge sufficient"
        return "Combined score below threshold"

    # ----- Feedback / Learning -----

    def record_outcome(self, intent: str, used_tools: bool, tool_helped: bool) -> None:
        """Record whether tool use helped the response quality.

        Call this after getting user feedback to improve future decisions.
        """
        with self._lock:
            outcomes = self._tool_outcomes[intent]
            if used_tools:
                outcomes["used"] += 1
                if tool_helped:
                    outcomes["tool_helped"] += 1
                else:
                    outcomes["tool_wasted"] += 1
            else:
                outcomes["skipped"] += 1

    def get_stats(self) -> Dict[str, Any]:
        """Get tool decision statistics."""
        intent_stats = {}
        for intent, outcomes in self._tool_outcomes.items():
            total = outcomes["used"] + outcomes["skipped"]
            if total > 0:
                intent_stats[intent] = {
                    "total": total,
                    "tool_used": outcomes["used"],
                    "tool_skipped": outcomes["skipped"],
                    "tool_helped": outcomes["tool_helped"],
                    "tool_wasted": outcomes["tool_wasted"],
                    "effectiveness": round(outcomes["tool_helped"] / max(outcomes["used"], 1), 3),
                }
        return {
            "total_decisions": self._total_decisions,
            "intent_stats": intent_stats,
            "threshold": _TOOL_USE_THRESHOLD,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_intent_tool_needs(self) -> Dict[str, float]:
        """Get the current intent-to-tool-need mapping."""
        return dict(_INTENT_TOOL_NEED)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[ToolDecisionEngine] = None
_instance_lock = threading.Lock()


def get_tool_decision_engine() -> ToolDecisionEngine:
    """Get the global ToolDecisionEngine singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ToolDecisionEngine()
    return _instance
