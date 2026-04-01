"""Business analytics — query taxonomy, knowledge gaps, adoption metrics."""
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace


def QueryRecord(*, query, intent, confidence, quality, user_id, timestamp,
                response_time_ms, chunks_found, feedback=None):
    return SimpleNamespace(
        query=query, intent=intent, confidence=confidence, quality=quality,
        user_id=user_id, timestamp=timestamp, response_time_ms=response_time_ms,
        chunks_found=chunks_found, feedback=feedback,
    )


class AnalyticsEngine:
    def __init__(self, max_records: int = 10000):
        self._records: list = []
        self._max = max_records
        self._daily_active: dict[str, set] = defaultdict(set)
        self._feature_usage: Counter = Counter()
        self._knowledge_gaps: Counter = Counter()

    def record(self, query: str, intent: str, confidence: float, quality: float,
               user_id: str, response_time_ms: float, chunks_found: int):
        r = QueryRecord(query=query, intent=intent, confidence=confidence,
                        quality=quality, user_id=user_id, response_time_ms=response_time_ms,
                        chunks_found=chunks_found,
                        timestamp=datetime.now(timezone.utc).isoformat())
        self._records.append(r)
        if len(self._records) > self._max:
            self._records = self._records[-self._max:]

        self._daily_active[datetime.now(timezone.utc).strftime("%Y-%m-%d")].add(user_id)
        self._feature_usage[intent] += 1
        if confidence < 0.4 and chunks_found < 2:
            self._knowledge_gaps[" ".join(sorted(set(query.lower().split())))[:100]] += 1

    def record_feedback(self, query: str, feedback: str):
        for r in reversed(self._records):
            if r.query == query:
                r.feedback = feedback
                break

    def get_question_taxonomy(self) -> dict:
        recs = self._records
        total = max(len(recs), 1)
        return {
            "total_queries": len(recs),
            "by_intent": dict(Counter(r.intent for r in recs).most_common(20)),
            "by_confidence": {
                "high": sum(1 for r in recs if r.confidence > 0.7),
                "medium": sum(1 for r in recs if 0.4 <= r.confidence <= 0.7),
                "low": sum(1 for r in recs if r.confidence < 0.4),
            },
            "avg_confidence": sum(r.confidence for r in recs) / total,
            "avg_quality": sum(r.quality for r in recs) / total,
            "avg_response_time_ms": sum(r.response_time_ms for r in recs) / total,
        }

    def get_knowledge_gaps(self, top_n: int = 20) -> list[dict]:
        return [{"pattern": p, "occurrences": c} for p, c in self._knowledge_gaps.most_common(top_n)]

    def get_adoption_metrics(self) -> dict:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        days_7 = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        days_30 = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]
        union = lambda dates: set().union(*(self._daily_active.get(d, set()) for d in dates))
        return {
            "today_active": len(self._daily_active.get(today, set())),
            "7d_active": len(union(days_7)), "30d_active": len(union(days_30)),
            "total_queries": len(self._records),
            "feature_heatmap": dict(self._feature_usage.most_common(15)),
            "daily_trend": {d: len(self._daily_active.get(d, set())) for d in days_7},
        }

    def get_roi_estimate(self) -> dict:
        total = len(self._records)
        automated = sum(1 for r in self._records if r.confidence > 0.6)
        return {
            "total_queries": total, "automated_queries": automated,
            "automation_rate": round(automated / max(total, 1), 3),
            "estimated_time_saved_hours": round((automated * 5) / 60, 1),
            "avg_cost_per_query": 0.001,
        }


# Singleton — kept as module var so tests can reset via `mod._engine = None`
_engine: AnalyticsEngine | None = None

def get_analytics_engine() -> AnalyticsEngine:
    global _engine
    if _engine is None:
        _engine = AnalyticsEngine()
    return _engine
