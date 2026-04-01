"""Comprehensive unit tests for chat_app.human_loop."""
import time
from unittest.mock import MagicMock

import pytest

from chat_app.human_loop import (
    ActionSeverity,
    AgentInsight,
    ApprovalRequest,
    ApprovalStatus,
    HumanLoopManager,
    UserFeedback,
)


# ---------------------------------------------------------------------------
# ApprovalRequest
# ---------------------------------------------------------------------------

class TestApprovalRequest:
    def test_creation_defaults(self):
        req = ApprovalRequest(
            request_id="r1",
            action_name="do_thing",
            description="desc",
            severity=ActionSeverity.MEDIUM,
        )
        assert req.request_id == "r1"
        assert req.status == ApprovalStatus.PENDING
        assert req.resolved_at is None
        assert req.resolved_by is None
        assert req.expires_at is None

    def test_is_expired_false_when_no_expiry(self):
        req = ApprovalRequest(
            request_id="r2",
            action_name="a",
            description="d",
            severity=ActionSeverity.LOW,
        )
        assert req.is_expired is False

    def test_is_expired_false_when_future(self):
        req = ApprovalRequest(
            request_id="r3",
            action_name="a",
            description="d",
            severity=ActionSeverity.HIGH,
            expires_at=time.time() + 9999,
        )
        assert req.is_expired is False

    def test_is_expired_true_when_past(self):
        req = ApprovalRequest(
            request_id="r4",
            action_name="a",
            description="d",
            severity=ActionSeverity.CRITICAL,
            expires_at=time.time() - 1,
        )
        assert req.is_expired is True


# ---------------------------------------------------------------------------
# UserFeedback
# ---------------------------------------------------------------------------

class TestUserFeedback:
    def test_creation(self):
        fb = UserFeedback(
            feedback_id="fb1",
            query="how to search",
            response_summary="use index=main",
            rating=4,
        )
        assert fb.rating == 4
        assert fb.correction is None
        assert fb.tags == []
        assert fb.timestamp > 0

    def test_creation_full(self):
        fb = UserFeedback(
            feedback_id="fb2",
            query="q",
            response_summary="r",
            rating=2,
            correction="should use tstats",
            tags=["spl", "performance"],
        )
        assert fb.correction == "should use tstats"
        assert len(fb.tags) == 2


# ---------------------------------------------------------------------------
# AgentInsight
# ---------------------------------------------------------------------------

class TestAgentInsight:
    def test_creation_defaults(self):
        insight = AgentInsight(insight_type="anomaly", message="spike detected")
        assert insight.severity == ActionSeverity.LOW
        assert insight.acknowledged is False
        assert insight.data == {}

    def test_creation_full(self):
        insight = AgentInsight(
            insight_type="drift",
            message="model drift",
            severity=ActionSeverity.HIGH,
            data={"metric": 0.95},
        )
        assert insight.severity == ActionSeverity.HIGH
        assert insight.data["metric"] == 0.95


# ---------------------------------------------------------------------------
# HumanLoopManager — request_approval
# ---------------------------------------------------------------------------

class TestRequestApproval:
    def test_auto_approve_low_severity(self):
        mgr = HumanLoopManager(auto_approve_low=True)
        req = mgr.request_approval("read_data", "reading data", ActionSeverity.LOW)
        assert req.status == ApprovalStatus.AUTO_APPROVED
        assert req.resolved_at is not None
        assert mgr._total_auto_approvals == 1
        # Should NOT be in pending
        assert len(mgr.get_pending_approvals()) == 0

    def test_low_not_auto_approved_when_disabled(self):
        mgr = HumanLoopManager(auto_approve_low=False)
        req = mgr.request_approval("read_data", "reading data", ActionSeverity.LOW)
        assert req.status == ApprovalStatus.PENDING

    def test_medium_requires_approval(self):
        mgr = HumanLoopManager()
        req = mgr.request_approval("modify", "modify data", ActionSeverity.MEDIUM)
        assert req.status == ApprovalStatus.PENDING
        assert req.expires_at is not None
        pending = mgr.get_pending_approvals()
        assert len(pending) == 1

    def test_high_requires_approval(self):
        mgr = HumanLoopManager()
        req = mgr.request_approval("deploy", "deploy change", ActionSeverity.HIGH)
        assert req.status == ApprovalStatus.PENDING

    def test_critical_requires_approval(self):
        mgr = HumanLoopManager()
        req = mgr.request_approval("delete", "delete all", ActionSeverity.CRITICAL)
        assert req.status == ApprovalStatus.PENDING

    def test_callback_stored(self):
        mgr = HumanLoopManager()
        cb = MagicMock()
        req = mgr.request_approval("act", "desc", ActionSeverity.MEDIUM, callback=cb)
        assert req.request_id in mgr._approval_callbacks

    def test_parameters_stored(self):
        mgr = HumanLoopManager()
        params = {"target": "server1"}
        req = mgr.request_approval("act", "desc", ActionSeverity.MEDIUM, parameters=params)
        pending = mgr.get_pending_approvals()
        assert pending[0]["parameters"] == params


# ---------------------------------------------------------------------------
# HumanLoopManager — approve / deny
# ---------------------------------------------------------------------------

class TestApproveDeny:
    def test_approve_success(self):
        mgr = HumanLoopManager()
        req = mgr.request_approval("act", "desc", ActionSeverity.MEDIUM)
        result = mgr.approve(req.request_id, approved_by="admin")
        assert result is True
        assert mgr._total_approvals == 1
        assert len(mgr._approval_history) == 1
        assert mgr._approval_history[0].status == ApprovalStatus.APPROVED
        assert mgr._approval_history[0].resolved_by == "admin"

    def test_approve_nonexistent(self):
        mgr = HumanLoopManager()
        assert mgr.approve("nonexistent_id") is False

    def test_approve_with_callback(self):
        mgr = HumanLoopManager()
        cb = MagicMock()
        req = mgr.request_approval("act", "desc", ActionSeverity.MEDIUM, callback=cb)
        mgr.approve(req.request_id)
        cb.assert_called_once()

    def test_approve_callback_exception_handled(self):
        mgr = HumanLoopManager()
        cb = MagicMock(side_effect=RuntimeError("callback error"))
        req = mgr.request_approval("act", "desc", ActionSeverity.MEDIUM, callback=cb)
        # Should not raise even though callback fails
        result = mgr.approve(req.request_id)
        assert result is True

    def test_deny_success(self):
        mgr = HumanLoopManager()
        req = mgr.request_approval("act", "desc", ActionSeverity.MEDIUM)
        result = mgr.deny(req.request_id, denied_by="admin")
        assert result is True
        assert mgr._total_denials == 1
        assert mgr._approval_history[0].status == ApprovalStatus.DENIED

    def test_deny_nonexistent(self):
        mgr = HumanLoopManager()
        assert mgr.deny("ghost_id") is False

    def test_deny_removes_callback(self):
        mgr = HumanLoopManager()
        cb = MagicMock()
        req = mgr.request_approval("act", "desc", ActionSeverity.HIGH, callback=cb)
        mgr.deny(req.request_id)
        assert req.request_id not in mgr._approval_callbacks
        cb.assert_not_called()


# ---------------------------------------------------------------------------
# Expired approval handling
# ---------------------------------------------------------------------------

class TestExpiredApprovals:
    def test_approve_expired_request(self):
        mgr = HumanLoopManager(approval_timeout_seconds=0)
        req = mgr.request_approval("act", "desc", ActionSeverity.MEDIUM)
        # Force expiry
        req.expires_at = time.time() - 10
        mgr._pending_approvals[req.request_id] = req
        result = mgr.approve(req.request_id)
        assert result is False
        assert mgr._approval_history[-1].status == ApprovalStatus.EXPIRED

    def test_get_pending_cleans_expired(self):
        mgr = HumanLoopManager()
        req = mgr.request_approval("act", "desc", ActionSeverity.MEDIUM)
        req.expires_at = time.time() - 10
        pending = mgr.get_pending_approvals()
        assert len(pending) == 0
        # The expired request should be in history
        assert len(mgr._approval_history) == 1
        assert mgr._approval_history[0].status == ApprovalStatus.EXPIRED


# ---------------------------------------------------------------------------
# record_feedback
# ---------------------------------------------------------------------------

class TestRecordFeedback:
    def test_basic_feedback(self):
        mgr = HumanLoopManager()
        fb = mgr.record_feedback("query", "response", 4)
        assert fb.rating == 4
        assert fb.query == "query"
        assert len(mgr._feedback_history) == 1

    def test_rating_clamped_below(self):
        mgr = HumanLoopManager()
        fb = mgr.record_feedback("q", "r", -5)
        assert fb.rating == 1

    def test_rating_clamped_above(self):
        mgr = HumanLoopManager()
        fb = mgr.record_feedback("q", "r", 100)
        assert fb.rating == 5

    def test_rating_boundary_1(self):
        mgr = HumanLoopManager()
        fb = mgr.record_feedback("q", "r", 1)
        assert fb.rating == 1

    def test_rating_boundary_5(self):
        mgr = HumanLoopManager()
        fb = mgr.record_feedback("q", "r", 5)
        assert fb.rating == 5

    def test_response_truncated_to_500(self):
        mgr = HumanLoopManager()
        long_response = "x" * 1000
        fb = mgr.record_feedback("q", long_response, 3)
        assert len(fb.response_summary) == 500

    def test_feedback_with_correction_and_tags(self):
        mgr = HumanLoopManager()
        fb = mgr.record_feedback("q", "r", 3, correction="fix this", tags=["spl"])
        assert fb.correction == "fix this"
        assert fb.tags == ["spl"]

    def test_feedback_history_truncation(self):
        mgr = HumanLoopManager()
        for i in range(1050):
            mgr.record_feedback(f"q{i}", "r", 3)
        assert len(mgr._feedback_history) == 1000


# ---------------------------------------------------------------------------
# add_insight
# ---------------------------------------------------------------------------

class TestAddInsight:
    def test_basic_insight(self):
        mgr = HumanLoopManager()
        insight = mgr.add_insight("anomaly", "unusual spike")
        assert insight.insight_type == "anomaly"
        assert insight.severity == ActionSeverity.LOW
        assert insight.acknowledged is False

    def test_insight_with_data(self):
        mgr = HumanLoopManager()
        insight = mgr.add_insight("drift", "model drift", ActionSeverity.HIGH, data={"score": 0.3})
        assert insight.data["score"] == 0.3

    def test_insight_history_truncation(self):
        mgr = HumanLoopManager()
        for i in range(550):
            mgr.add_insight("info", f"msg{i}")
        assert len(mgr._insights) == 500


# ---------------------------------------------------------------------------
# get_pending_approvals (with expired cleanup)
# ---------------------------------------------------------------------------

class TestGetPendingApprovals:
    def test_returns_pending_only(self):
        mgr = HumanLoopManager()
        mgr.request_approval("a1", "d1", ActionSeverity.MEDIUM)
        mgr.request_approval("a2", "d2", ActionSeverity.HIGH)
        pending = mgr.get_pending_approvals()
        assert len(pending) == 2

    def test_expired_cleaned_up(self):
        mgr = HumanLoopManager()
        req1 = mgr.request_approval("live", "still valid", ActionSeverity.MEDIUM)
        req2 = mgr.request_approval("dead", "expired", ActionSeverity.HIGH)
        req2.expires_at = time.time() - 100
        pending = mgr.get_pending_approvals()
        assert len(pending) == 1
        assert pending[0]["action"] == "live"


# ---------------------------------------------------------------------------
# get_recent_feedback
# ---------------------------------------------------------------------------

class TestGetRecentFeedback:
    def test_empty(self):
        mgr = HumanLoopManager()
        assert mgr.get_recent_feedback() == []

    def test_with_data(self):
        mgr = HumanLoopManager()
        mgr.record_feedback("q1", "r1", 5)
        mgr.record_feedback("q2", "r2", 3, correction="fix")
        recent = mgr.get_recent_feedback()
        assert len(recent) == 2
        assert recent[1]["has_correction"] is True

    def test_limit(self):
        mgr = HumanLoopManager()
        for i in range(10):
            mgr.record_feedback(f"q{i}", "r", 3)
        assert len(mgr.get_recent_feedback(limit=5)) == 5


# ---------------------------------------------------------------------------
# get_insights (with unacknowledged_only)
# ---------------------------------------------------------------------------

class TestGetInsights:
    def test_all_insights(self):
        mgr = HumanLoopManager()
        mgr.add_insight("a", "msg1")
        mgr.add_insight("b", "msg2")
        insights = mgr.get_insights()
        assert len(insights) == 2

    def test_unacknowledged_only(self):
        mgr = HumanLoopManager()
        mgr.add_insight("a", "msg1")
        mgr.add_insight("b", "msg2")
        mgr.acknowledge_insight(0)
        unack = mgr.get_insights(unacknowledged_only=True)
        assert len(unack) == 1
        assert unack[0]["message"] == "msg2"

    def test_insights_limited_to_50(self):
        mgr = HumanLoopManager()
        for i in range(60):
            mgr.add_insight("info", f"msg{i}")
        # get_insights returns last 50
        result = mgr.get_insights()
        assert len(result) == 50


# ---------------------------------------------------------------------------
# acknowledge_insight
# ---------------------------------------------------------------------------

class TestAcknowledgeInsight:
    def test_acknowledge_valid(self):
        mgr = HumanLoopManager()
        mgr.add_insight("a", "msg")
        assert mgr.acknowledge_insight(0) is True
        assert mgr._insights[0].acknowledged is True

    def test_acknowledge_invalid_index(self):
        mgr = HumanLoopManager()
        assert mgr.acknowledge_insight(0) is False
        assert mgr.acknowledge_insight(-1) is False

    def test_acknowledge_out_of_range(self):
        mgr = HumanLoopManager()
        mgr.add_insight("a", "msg")
        assert mgr.acknowledge_insight(5) is False


# ---------------------------------------------------------------------------
# get_satisfaction_score
# ---------------------------------------------------------------------------

class TestSatisfactionScore:
    def test_no_feedback(self):
        mgr = HumanLoopManager()
        assert mgr.get_satisfaction_score() == 0.0

    def test_perfect_score(self):
        mgr = HumanLoopManager()
        for _ in range(10):
            mgr.record_feedback("q", "r", 5)
        assert mgr.get_satisfaction_score() == pytest.approx(1.0)

    def test_worst_score(self):
        mgr = HumanLoopManager()
        for _ in range(10):
            mgr.record_feedback("q", "r", 1)
        assert mgr.get_satisfaction_score() == pytest.approx(0.2)

    def test_mixed_score(self):
        mgr = HumanLoopManager()
        mgr.record_feedback("q", "r", 5)
        mgr.record_feedback("q", "r", 1)
        # average = 3, score = 3 / 5 = 0.6 but method uses sum/len*5
        # sum = 6, len = 2, score = 6 / (2*5) = 0.6
        assert mgr.get_satisfaction_score() == pytest.approx(0.6)

    def test_uses_last_50(self):
        mgr = HumanLoopManager()
        # First 50 with rating 1
        for _ in range(50):
            mgr.record_feedback("q", "r", 1)
        # Last 50 with rating 5
        for _ in range(50):
            mgr.record_feedback("q", "r", 5)
        # Satisfaction should be based on last 50 (all 5s)
        assert mgr.get_satisfaction_score() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# get_metrics
# ---------------------------------------------------------------------------

class TestGetMetrics:
    def test_empty_metrics(self):
        mgr = HumanLoopManager()
        m = mgr.get_metrics()
        assert m["pending_approvals"] == 0
        assert m["total_approvals"] == 0
        assert m["total_denials"] == 0
        assert m["total_auto_approvals"] == 0
        assert m["total_feedback"] == 0
        assert m["satisfaction_score"] == 0.0
        assert m["unacknowledged_insights"] == 0

    def test_metrics_after_activity(self):
        mgr = HumanLoopManager()
        # Auto-approve
        mgr.request_approval("a", "d", ActionSeverity.LOW)
        # Manual approve
        req = mgr.request_approval("b", "d", ActionSeverity.MEDIUM)
        mgr.approve(req.request_id)
        # Deny
        req2 = mgr.request_approval("c", "d", ActionSeverity.HIGH)
        mgr.deny(req2.request_id)
        # Feedback
        mgr.record_feedback("q", "r", 4)
        # Insight
        mgr.add_insight("info", "msg")

        m = mgr.get_metrics()
        assert m["total_auto_approvals"] == 1
        assert m["total_approvals"] == 1
        assert m["total_denials"] == 1
        assert m["total_feedback"] == 1
        assert m["unacknowledged_insights"] == 1
        assert m["avg_feedback_rating"] == 4.0
