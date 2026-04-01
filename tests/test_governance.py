"""Tests for enterprise governance — DORA metrics, provenance, learning governance."""

import pytest


class TestReleaseGovernance:
    def test_record_deployment(self):
        from chat_app.release_governance import ReleaseTracker
        t = ReleaseTracker()
        r = t.record_deployment("3.5.1", success=True)
        assert r.version == "3.5.1"
        assert r.success is True

    def test_dora_metrics(self):
        from chat_app.release_governance import ReleaseTracker
        t = ReleaseTracker()
        t.record_deployment("3.5.0", success=True)
        t.record_deployment("3.5.1", success=True)
        t.record_deployment("3.5.2", success=False, recovery_minutes=15)
        m = t.get_dora_metrics()
        assert m["releases"] == 3
        assert m["change_failure_rate"] > 0
        assert m["mean_time_to_recovery_minutes"] == 15.0

    def test_release_history(self):
        from chat_app.release_governance import ReleaseTracker
        t = ReleaseTracker()
        t.record_deployment("1.0")
        t.record_deployment("2.0")
        h = t.get_release_history()
        assert len(h) == 2
        assert h[0]["version"] == "2.0"  # Most recent first


class TestProvenance:
    def test_record_provenance(self):
        from chat_app.provenance import ProvenanceTracker
        t = ProvenanceTracker()
        p = t.record("What is HEC?",
                     sources=[{"collection": "spl_docs", "score": 0.9}],
                     grounding="high", confidence=0.87)
        assert p.is_grounded is True
        assert p.source_diversity == 1
        assert p.collections_used == ["spl_docs"]

    def test_ungrounded_response(self):
        from chat_app.provenance import ProvenanceTracker
        t = ProvenanceTracker()
        p = t.record("Hello", sources=[], grounding="ungrounded", confidence=0.5)
        assert p.is_grounded is False

    def test_provenance_stats(self):
        from chat_app.provenance import ProvenanceTracker
        t = ProvenanceTracker()
        t.record("q1", [{"collection": "docs"}], "high", 0.9)
        t.record("q2", [], "ungrounded", 0.3)
        s = t.get_stats()
        assert s["total"] == 2
        assert s["grounded_rate"] == 0.5
        assert "grounding_distribution" in s


class TestLearningGovernance:
    def test_successful_session(self):
        from chat_app.learning_governance import LearningGovernor
        g = LearningGovernor()
        with g.learning_session("qa_generation") as session:
            session.record_quality(before=0.85, after=0.87)
            session.items_processed = 100
        h = g.get_history()
        assert len(h) == 1
        assert h[0]["rolled_back"] is False
        assert h[0]["quality_delta"] > 0

    def test_auto_rollback_on_degradation(self):
        from chat_app.learning_governance import LearningGovernor
        g = LearningGovernor(min_quality_delta=-0.05)
        with g.learning_session("reassessment") as session:
            session.record_quality(before=0.85, after=0.70)  # -0.15 degradation
        h = g.get_history()
        assert h[0]["rolled_back"] is True

    def test_approval_required_for_model_customization(self):
        from chat_app.learning_governance import LearningGovernor
        g = LearningGovernor()
        with g.learning_session("model_customization") as session:
            session.record_quality(before=0.8, after=0.85)
        h = g.get_history()
        assert h[0]["approved"] is False  # Needs explicit approval

    def test_stats(self):
        from chat_app.learning_governance import LearningGovernor
        g = LearningGovernor()
        with g.learning_session("qa_generation") as s:
            s.record_quality(0.8, 0.82)
        with g.learning_session("qa_generation") as s:
            s.record_quality(0.82, 0.70)  # Will rollback
        stats = g.get_stats()
        assert stats["total_sessions"] == 2
        assert stats["rollback_rate"] > 0
