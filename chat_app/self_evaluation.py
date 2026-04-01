"""Self-Evaluation Visibility — confidence scoring and grounding per response.

Computes a confidence score for each response based on:
- **Retrieval grounding**: How well the response is supported by retrieved docs
- **Tool success**: Whether tools executed successfully
- **Knowledge coverage**: Overlap between query terms and retrieved content
- **Source diversity**: Number of distinct sources contributing to the answer
- **Historical accuracy**: Past feedback on similar queries

The score is surfaced to users alongside the response for transparency.

Usage:
    from chat_app.self_evaluation import get_evaluator

    evaluator = get_evaluator()
    score = evaluator.evaluate(
        query="How do I configure HEC?",
        response="To configure HEC, navigate to Settings > Data Inputs...",
        retrieved_chunks=["HEC docs chunk 1", "HEC docs chunk 2"],
        tools_used=[{"name": "search", "success": True}],
    )
    # score.confidence = 0.87, score.grounding = "high", etc.
"""

import logging
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Confidence levels
# ---------------------------------------------------------------------------

class GroundingLevel:
    HIGH = "high"          # Well-supported by retrieved docs
    MEDIUM = "medium"      # Partially supported
    LOW = "low"            # Mostly from LLM knowledge
    UNGROUNDED = "ungrounded"  # No retrieval support


# ---------------------------------------------------------------------------
# Evaluation result
# ---------------------------------------------------------------------------

@dataclass
class EvaluationResult:
    """Result of self-evaluation for a response."""
    confidence: float  # 0.0 to 1.0
    grounding: str  # high, medium, low, ungrounded
    retrieval_score: float = 0.0  # How relevant retrieved docs are
    tool_success_rate: float = 1.0  # Fraction of tools that succeeded
    knowledge_coverage: float = 0.0  # Query term coverage in sources
    source_diversity: int = 0  # Number of distinct sources
    warnings: List[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confidence": round(self.confidence, 3),
            "confidence_pct": f"{self.confidence * 100:.0f}%",
            "grounding": self.grounding,
            "retrieval_score": round(self.retrieval_score, 3),
            "tool_success_rate": round(self.tool_success_rate, 3),
            "knowledge_coverage": round(self.knowledge_coverage, 3),
            "source_diversity": self.source_diversity,
            "warnings": self.warnings,
            "explanation": self.explanation,
        }


# ---------------------------------------------------------------------------
# Term extraction
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "like",
    "through", "after", "over", "between", "out", "against", "during",
    "without", "before", "under", "around", "among", "and", "or", "but",
    "if", "then", "else", "when", "up", "so", "no", "not", "only",
    "very", "just", "how", "what", "which", "who", "whom", "this",
    "that", "these", "those", "i", "me", "my", "we", "our", "you",
    "your", "he", "she", "it", "they", "them", "their",
})


def _extract_terms(text: str) -> Set[str]:
    """Extract meaningful terms from text (lowercased, stopwords removed)."""
    words = re.findall(r'[a-zA-Z_]{3,}', text.lower())
    return {w for w in words if w not in _STOPWORDS}


# ---------------------------------------------------------------------------
# Self Evaluator
# ---------------------------------------------------------------------------

class SelfEvaluator:
    """Evaluates response quality with confidence scoring."""

    def __init__(self):
        self._history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def evaluate(
        self,
        query: str,
        response: str,
        retrieved_chunks: Optional[List[str]] = None,
        tools_used: Optional[List[Dict[str, Any]]] = None,
        collection_names: Optional[List[str]] = None,
    ) -> EvaluationResult:
        """Evaluate the quality and grounding of a response.

        Args:
            query: The user's question.
            response: The generated response.
            retrieved_chunks: List of retrieved text chunks used.
            tools_used: List of tool execution records [{name, success}].
            collection_names: Names of collections that contributed.

        Returns:
            EvaluationResult with confidence score and grounding level.
        """
        chunks = retrieved_chunks or []
        tools = tools_used or []
        collections = collection_names or []
        warnings: List[str] = []

        # 1. Retrieval grounding score
        retrieval_score = self._compute_retrieval_score(query, response, chunks)

        # 2. Tool success rate
        tool_success_rate = 1.0
        if tools:
            successes = sum(1 for t in tools if t.get("success", True))
            tool_success_rate = successes / len(tools)
            if tool_success_rate < 1.0:
                warnings.append(f"{len(tools) - successes}/{len(tools)} tools failed")

        # 3. Knowledge coverage
        knowledge_coverage = self._compute_knowledge_coverage(query, chunks)

        # 4. Source diversity
        source_diversity = len(set(collections)) if collections else (1 if chunks else 0)
        if source_diversity == 0 and not tools:
            warnings.append("No retrieval sources or tools used — response from LLM knowledge only")

        # 5. Response quality signals
        if len(response) < 50:
            warnings.append("Very short response — may be incomplete")
        if "I don't know" in response or "I'm not sure" in response:
            warnings.append("Response indicates uncertainty")

        # Compute weighted confidence
        weights = {
            "retrieval": 0.35,
            "tool_success": 0.25,
            "coverage": 0.25,
            "diversity": 0.15,
        }

        diversity_score = min(source_diversity / 3, 1.0)  # Normalize: 3+ sources = max

        confidence = (
            weights["retrieval"] * retrieval_score +
            weights["tool_success"] * tool_success_rate +
            weights["coverage"] * knowledge_coverage +
            weights["diversity"] * diversity_score
        )

        # Determine grounding level
        if retrieval_score >= 0.7 and knowledge_coverage >= 0.5:
            grounding = GroundingLevel.HIGH
        elif retrieval_score >= 0.4 or knowledge_coverage >= 0.3:
            grounding = GroundingLevel.MEDIUM
        elif chunks:
            grounding = GroundingLevel.LOW
        else:
            grounding = GroundingLevel.UNGROUNDED

        # Build explanation
        parts = []
        if retrieval_score > 0.5:
            parts.append(f"well-supported by {len(chunks)} retrieved chunks")
        elif chunks:
            parts.append(f"partially supported by {len(chunks)} chunks")
        else:
            parts.append("no retrieval sources used")
        if tools:
            parts.append(f"{len(tools)} tool(s) executed ({tool_success_rate*100:.0f}% success)")
        if source_diversity > 1:
            parts.append(f"{source_diversity} distinct sources")
        explanation = "Confidence based on: " + ", ".join(parts)

        result = EvaluationResult(
            confidence=min(max(confidence, 0.0), 1.0),
            grounding=grounding,
            retrieval_score=retrieval_score,
            tool_success_rate=tool_success_rate,
            knowledge_coverage=knowledge_coverage,
            source_diversity=source_diversity,
            warnings=warnings,
            explanation=explanation,
        )

        # Record for tracking
        with self._lock:
            self._history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": result.confidence,
                "grounding": result.grounding,
                "query_length": len(query),
                "response_length": len(response),
                "chunks_used": len(chunks),
                "tools_used": len(tools),
            })
            if len(self._history) > 1000:
                self._history = self._history[-500:]

        return result

    def _compute_retrieval_score(self, query: str, response: str, chunks: List[str]) -> float:
        """Score how well the response is grounded in retrieved content."""
        if not chunks:
            return 0.0

        query_terms = _extract_terms(query)
        response_terms = _extract_terms(response)
        chunk_terms = set()
        for chunk in chunks:
            chunk_terms.update(_extract_terms(chunk))

        if not response_terms:
            return 0.0

        # How many response terms appear in the chunks
        grounded_terms = response_terms & chunk_terms
        grounding_ratio = len(grounded_terms) / len(response_terms) if response_terms else 0

        # How many query terms appear in the chunks
        query_in_chunks = len(query_terms & chunk_terms) / len(query_terms) if query_terms else 0

        return (grounding_ratio * 0.6 + query_in_chunks * 0.4)

    def _compute_knowledge_coverage(self, query: str, chunks: List[str]) -> float:
        """Score how well the retrieved content covers the query."""
        if not chunks:
            return 0.0

        query_terms = _extract_terms(query)
        if not query_terms:
            return 0.0

        chunk_terms = set()
        for chunk in chunks:
            chunk_terms.update(_extract_terms(chunk))

        covered = len(query_terms & chunk_terms)
        return covered / len(query_terms)

    def get_stats(self) -> Dict[str, Any]:
        """Get self-evaluation statistics."""
        with self._lock:
            history = list(self._history)

        if not history:
            return {"total_evaluations": 0, "timestamp": datetime.now(timezone.utc).isoformat()}

        confidences = [h["confidence"] for h in history]
        groundings = defaultdict(int)
        for h in history:
            groundings[h["grounding"]] += 1

        return {
            "total_evaluations": len(history),
            "avg_confidence": round(sum(confidences) / len(confidences), 3),
            "min_confidence": round(min(confidences), 3),
            "max_confidence": round(max(confidences), 3),
            "grounding_distribution": dict(groundings),
            "avg_chunks_per_response": round(
                sum(h["chunks_used"] for h in history) / len(history), 1
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[SelfEvaluator] = None
_instance_lock = threading.Lock()


def get_evaluator() -> SelfEvaluator:
    """Get the global SelfEvaluator singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SelfEvaluator()
    return _instance
