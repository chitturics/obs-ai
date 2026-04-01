"""
Cross-encoder reranker for the Splunk Assistant.

Provides cross-encoder reranking with quality metrics tracking.
"""
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

_RERANKER_AVAILABLE = False
_reranker_model = None

try:
    from sentence_transformers import CrossEncoder
    _RERANKER_AVAILABLE = True
except ImportError:
    logger.debug("sentence-transformers not installed - cross-encoder reranking disabled")


@dataclass
class RerankMetrics:
    """Quality metrics for a single reranking operation."""
    chunks_input: int = 0
    chunks_output: int = 0
    chunks_reordered: int = 0
    top_result_changed: bool = False
    avg_score_before: float = 0.0
    avg_score_after: float = 0.0
    latency_ms: float = 0.0
    intent: str = ""


class RerankStats:
    """Aggregated reranking quality statistics (last N operations)."""

    def __init__(self, max_history: int = 200):
        self._history: deque[RerankMetrics] = deque(maxlen=max_history)

    def record(self, metrics: RerankMetrics):
        self._history.append(metrics)

    def summary(self) -> Dict:
        if not self._history:
            return {"total_operations": 0}
        total = len(self._history)
        top_changed = sum(1 for m in self._history if m.top_result_changed)
        avg_reordered = sum(m.chunks_reordered for m in self._history) / total
        avg_latency = sum(m.latency_ms for m in self._history) / total
        avg_score_improvement = sum(
            m.avg_score_after - m.avg_score_before for m in self._history
        ) / total
        return {
            "total_operations": total,
            "top_result_changed_pct": round(top_changed / total * 100, 1),
            "avg_chunks_reordered": round(avg_reordered, 1),
            "avg_latency_ms": round(avg_latency, 1),
            "avg_score_improvement": round(avg_score_improvement, 2),
        }


# Module-level stats tracker
rerank_stats = RerankStats()


class Reranker:
    """
    Reranker class to manage the cross-encoder model.
    """

    def __init__(self):
        self.model = self._get_reranker()

    def _get_reranker(self):
        """Lazy-load the cross-encoder model (singleton)."""
        global _reranker_model
        if _reranker_model is None and _RERANKER_AVAILABLE:
            try:
                _reranker_model = CrossEncoder(
                    "cross-encoder/ms-marco-MiniLM-L-6-v2",
                    max_length=512,
                )
                logger.info("Cross-encoder reranker loaded: ms-marco-MiniLM-L-6-v2")
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                logger.warning(f"Failed to load cross-encoder model: {e}")
        return _reranker_model

    def rerank(
        self,
        query: str,
        scored_chunks: List[tuple],
        top_k: int = 10,
        intent: str = "",
    ) -> List[tuple]:
        """
        Re-score chunks with a cross-encoder for semantic relevance.

        Args:
            query: The user's original query text.
            scored_chunks: List of (score, ref, text, source, chunk_dict) tuples
                           from score_and_filter_chunks().
            top_k: Number of chunks to return after reranking.
            intent: Current query intent (for metrics tracking).

        Returns:
            Reranked list of (score, ref, text, source, chunk_dict) tuples,
            or the original list unchanged if the reranker is unavailable.
        """
        if self.model is None or not scored_chunks:
            return scored_chunks[:top_k]

        t0 = time.monotonic()
        try:
            pairs = [(query, chunk[2]) for chunk in scored_chunks]  # (query, text)
            ce_scores = self.model.predict(pairs)

            # Record original order for metrics
            original_order = [chunk[1] for chunk in scored_chunks]  # refs as identity
            avg_score_before = sum(c[0] for c in scored_chunks) / len(scored_chunks) if scored_chunks else 0.0

            # Combine: cross-encoder score (normalized 0-100) + original lexical score (weighted 30%)
            reranked = []
            for i, chunk in enumerate(scored_chunks):
                ce_normalized = float(ce_scores[i]) * 50  # sigmoid output ~0-1 -> 0-50
                original_score = chunk[0]
                combined = ce_normalized + (original_score * 0.3)
                reranked.append((combined, chunk[1], chunk[2], chunk[3], chunk[4]))

            reranked.sort(key=lambda x: -x[0])
            result = reranked[:top_k]

            # --- Quality metrics ---
            latency_ms = (time.monotonic() - t0) * 1000
            new_order = [chunk[1] for chunk in result]
            top_changed = bool(original_order and new_order and original_order[0] != new_order[0])
            # Count how many chunks moved position
            reordered_count = 0
            for idx, ref in enumerate(new_order):
                if idx < len(original_order) and original_order[idx] != ref:
                    reordered_count += 1
            avg_score_after = sum(c[0] for c in result) / len(result) if result else 0.0

            metrics = RerankMetrics(
                chunks_input=len(scored_chunks),
                chunks_output=len(result),
                chunks_reordered=reordered_count,
                top_result_changed=top_changed,
                avg_score_before=avg_score_before,
                avg_score_after=avg_score_after,
                latency_ms=latency_ms,
                intent=intent,
            )
            rerank_stats.record(metrics)

            if top_changed:
                logger.info(
                    "[RERANK] Top result changed after reranking "
                    "(reordered=%d/%d, latency=%.0fms, intent=%s)",
                    reordered_count, len(scored_chunks), latency_ms, intent or "unknown",
                )
            else:
                logger.debug(
                    "[RERANK] Reranked %d chunks (reordered=%d, latency=%.0fms)",
                    len(scored_chunks), reordered_count, latency_ms,
                )

            return result
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Cross-encoder reranking failed, using original scores: {e}")
            return scored_chunks[:top_k]


# Singleton instance
reranker = Reranker()


def get_rerank_stats() -> Dict:
    """Return aggregated reranking quality statistics."""
    return rerank_stats.summary()

