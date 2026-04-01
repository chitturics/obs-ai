"""Response Provenance — tracks source attribution for every answer.

Every response gets a provenance record showing:
- Which collections/sources contributed
- Confidence per source
- Whether the answer is grounded (RAG) or ungrounded (LLM knowledge)
- Source diversity score

Usage:
    from chat_app.provenance import ProvenanceTracker, ResponseProvenance

    tracker = get_provenance_tracker()
    prov = tracker.record(
        query="What is HEC?",
        sources=[{"collection": "spl_docs", "chunk_id": "hec_01", "score": 0.92}],
        grounding="high",
        confidence=0.87,
    )
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ResponseProvenance:
    """Source attribution for a single response."""
    query: str = ""
    sources: List[Dict[str, Any]] = field(default_factory=list)
    grounding: str = "unknown"  # high, medium, low, ungrounded
    confidence: float = 0.0
    source_diversity: int = 0
    collections_used: List[str] = field(default_factory=list)
    is_grounded: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        self.collections_used = list(set(s.get("collection", "") for s in self.sources if s.get("collection")))
        self.source_diversity = len(self.collections_used)
        self.is_grounded = self.grounding in ("high", "medium") and len(self.sources) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query[:200],
            "grounding": self.grounding,
            "confidence": round(self.confidence, 3),
            "source_count": len(self.sources),
            "source_diversity": self.source_diversity,
            "collections_used": self.collections_used,
            "is_grounded": self.is_grounded,
            "timestamp": self.timestamp,
        }


class ProvenanceTracker:
    """Tracks response provenance for audit and quality."""

    def __init__(self):
        self._records: deque = deque(maxlen=1000)
        self._lock = threading.Lock()

    def record(self, query: str, sources: List[Dict[str, Any]],
               grounding: str = "unknown", confidence: float = 0.0) -> ResponseProvenance:
        prov = ResponseProvenance(
            query=query, sources=sources,
            grounding=grounding, confidence=confidence,
        )
        with self._lock:
            self._records.append(prov)
        return prov

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            records = list(self._records)
        if not records:
            return {"total": 0}

        grounded = sum(1 for r in records if r.is_grounded)
        avg_conf = sum(r.confidence for r in records) / len(records)
        avg_diversity = sum(r.source_diversity for r in records) / len(records)

        grounding_dist = {}
        for r in records:
            grounding_dist[r.grounding] = grounding_dist.get(r.grounding, 0) + 1

        return {
            "total": len(records),
            "grounded_rate": round(grounded / len(records), 3),
            "avg_confidence": round(avg_conf, 3),
            "avg_source_diversity": round(avg_diversity, 1),
            "grounding_distribution": grounding_dist,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            records = list(self._records)
        records.reverse()
        return [r.to_dict() for r in records[:limit]]


_instance: Optional[ProvenanceTracker] = None


def get_provenance_tracker() -> ProvenanceTracker:
    global _instance
    if _instance is None:
        _instance = ProvenanceTracker()
    return _instance
