"""Tests for chat_app.analytics — Business intelligence and query analytics."""

import pytest
from datetime import datetime, timezone

from chat_app.analytics import (
    QueryRecord,
    AnalyticsEngine,
    get_analytics_engine,
)


# ---------------------------------------------------------------------------
# QueryRecord tests
# ---------------------------------------------------------------------------

class TestQueryRecord:
    def test_creation(self):
        r = QueryRecord(
            query="show failed logins",
            intent="spl_generation",
            confidence=0.85,
            quality=0.9,
            user_id="user1",
            timestamp="2025-01-01T00:00:00Z",
            response_time_ms=150.0,
            chunks_found=3,
        )
        assert r.query == "show failed logins"
        assert r.feedback is None


# ---------------------------------------------------------------------------
# AnalyticsEngine — record
# ---------------------------------------------------------------------------

class TestRecord:
    def test_record_query(self):
        engine = AnalyticsEngine()
        engine.record("show logins", "spl_generation", 0.8, 0.9,
                      "user1", 100.0, 3)
        assert len(engine._records) == 1

    def test_record_caps_at_max(self):
        engine = AnalyticsEngine(max_records=5)
        for i in range(10):
            engine.record(f"query {i}", "general_qa", 0.5, 0.5,
                          "user1", 100.0, 2)
        assert len(engine._records) == 5

    def test_record_tracks_daily_active(self):
        engine = AnalyticsEngine()
        engine.record("q1", "general_qa", 0.7, 0.8, "user1", 100.0, 2)
        engine.record("q2", "general_qa", 0.7, 0.8, "user2", 100.0, 2)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert len(engine._daily_active[today]) == 2


# ---------------------------------------------------------------------------
# Question taxonomy
# ---------------------------------------------------------------------------

class TestQuestionTaxonomy:
    def test_taxonomy_empty(self):
        engine = AnalyticsEngine()
        tax = engine.get_question_taxonomy()
        assert tax["total_queries"] == 0

    def test_taxonomy_by_intent(self):
        engine = AnalyticsEngine()
        engine.record("q1", "spl_generation", 0.8, 0.9, "u1", 100, 3)
        engine.record("q2", "spl_generation", 0.7, 0.8, "u1", 100, 2)
        engine.record("q3", "config_lookup", 0.6, 0.7, "u1", 100, 1)
        tax = engine.get_question_taxonomy()
        assert tax["by_intent"]["spl_generation"] == 2
        assert tax["by_intent"]["config_lookup"] == 1

    def test_taxonomy_confidence_buckets(self):
        engine = AnalyticsEngine()
        engine.record("q1", "a", 0.9, 0.9, "u1", 100, 3)  # high
        engine.record("q2", "a", 0.5, 0.5, "u1", 100, 2)  # medium
        engine.record("q3", "a", 0.2, 0.2, "u1", 100, 1)  # low
        tax = engine.get_question_taxonomy()
        assert tax["by_confidence"]["high"] == 1
        assert tax["by_confidence"]["medium"] == 1
        assert tax["by_confidence"]["low"] == 1


# ---------------------------------------------------------------------------
# Knowledge gap detection
# ---------------------------------------------------------------------------

class TestKnowledgeGaps:
    def test_no_gaps_when_confident(self):
        engine = AnalyticsEngine()
        engine.record("q1", "general_qa", 0.9, 0.9, "u1", 100, 5)
        gaps = engine.get_knowledge_gaps()
        assert len(gaps) == 0

    def test_gaps_detected_low_confidence(self):
        engine = AnalyticsEngine()
        for _ in range(3):
            engine.record("what is quantum splunk", "general_qa", 0.1, 0.2,
                          "u1", 100, 0)
        gaps = engine.get_knowledge_gaps()
        assert len(gaps) >= 1


# ---------------------------------------------------------------------------
# Adoption metrics
# ---------------------------------------------------------------------------

class TestAdoptionMetrics:
    def test_adoption_empty(self):
        engine = AnalyticsEngine()
        m = engine.get_adoption_metrics()
        assert m["total_queries"] == 0

    def test_adoption_active_users(self):
        engine = AnalyticsEngine()
        engine.record("q1", "a", 0.8, 0.8, "user1", 100, 3)
        engine.record("q2", "a", 0.8, 0.8, "user2", 100, 3)
        engine.record("q3", "a", 0.8, 0.8, "user1", 100, 3)
        m = engine.get_adoption_metrics()
        assert m["total_queries"] == 3
        assert m["today_active"] == 2

    def test_feature_heatmap(self):
        engine = AnalyticsEngine()
        engine.record("q1", "spl_generation", 0.8, 0.8, "u1", 100, 3)
        engine.record("q2", "spl_generation", 0.7, 0.7, "u1", 100, 2)
        engine.record("q3", "config_lookup", 0.6, 0.6, "u1", 100, 1)
        m = engine.get_adoption_metrics()
        assert m["feature_heatmap"]["spl_generation"] == 2


# ---------------------------------------------------------------------------
# ROI estimate
# ---------------------------------------------------------------------------

class TestROIEstimate:
    def test_roi_empty(self):
        engine = AnalyticsEngine()
        roi = engine.get_roi_estimate()
        assert roi["total_queries"] == 0
        assert roi["estimated_time_saved_hours"] == 0.0

    def test_roi_with_automated_queries(self):
        engine = AnalyticsEngine()
        for _ in range(10):
            engine.record("q", "a", 0.8, 0.9, "u1", 100, 3)
        roi = engine.get_roi_estimate()
        assert roi["automated_queries"] == 10
        assert roi["automation_rate"] == 1.0
        assert roi["estimated_time_saved_hours"] > 0

    def test_roi_mixed_confidence(self):
        engine = AnalyticsEngine()
        for _ in range(5):
            engine.record("q", "a", 0.8, 0.9, "u1", 100, 3)  # automated
        for _ in range(5):
            engine.record("q", "a", 0.3, 0.4, "u1", 100, 1)  # not automated
        roi = engine.get_roi_estimate()
        assert roi["automated_queries"] == 5
        assert roi["automation_rate"] == 0.5


# ---------------------------------------------------------------------------
# Feature usage tracking
# ---------------------------------------------------------------------------

class TestFeatureUsage:
    def test_feature_usage_tracks_intents(self):
        engine = AnalyticsEngine()
        engine.record("q1", "spl_generation", 0.8, 0.8, "u1", 100, 3)
        engine.record("q2", "config_lookup", 0.7, 0.7, "u1", 100, 2)
        usage = engine._feature_usage
        assert usage["spl_generation"] == 1
        assert usage["config_lookup"] == 1


# ---------------------------------------------------------------------------
# Daily active users
# ---------------------------------------------------------------------------

class TestDailyActiveUsers:
    def test_daily_active_today(self):
        engine = AnalyticsEngine()
        engine.record("q1", "a", 0.8, 0.8, "user1", 100, 3)
        engine.record("q2", "a", 0.8, 0.8, "user2", 100, 3)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert len(engine._daily_active[today]) == 2

    def test_daily_active_unique(self):
        engine = AnalyticsEngine()
        engine.record("q1", "a", 0.8, 0.8, "user1", 100, 3)
        engine.record("q2", "a", 0.8, 0.8, "user1", 100, 3)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert len(engine._daily_active[today]) == 1


# ---------------------------------------------------------------------------
# Feedback recording
# ---------------------------------------------------------------------------

class TestFeedback:
    def test_record_feedback(self):
        engine = AnalyticsEngine()
        engine.record("test query", "general_qa", 0.8, 0.8, "u1", 100, 3)
        engine.record_feedback("test query", "positive")
        assert engine._records[-1].feedback == "positive"

    def test_record_feedback_no_match(self):
        engine = AnalyticsEngine()
        engine.record("q1", "a", 0.8, 0.8, "u1", 100, 3)
        engine.record_feedback("nonexistent query", "negative")
        assert engine._records[-1].feedback is None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_analytics_engine_singleton(self):
        import chat_app.analytics as mod
        mod._engine = None
        e1 = get_analytics_engine()
        e2 = get_analytics_engine()
        assert e1 is e2
        mod._engine = None
