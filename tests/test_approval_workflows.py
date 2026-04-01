"""Tests for multi-step approval workflows."""

import pytest


@pytest.fixture
def mgr():
    from chat_app.approval_workflows import ApprovalManager
    return ApprovalManager()


def _steps():
    from chat_app.approval_workflows import ApprovalStep
    return [
        ApprovalStep(role="ANALYST", label="Technical review"),
        ApprovalStep(role="ADMIN", label="Production approval"),
    ]


class TestWorkflowCreation:

    def test_create_workflow(self, mgr):
        wf = mgr.create_workflow(
            action="deploy_pipeline",
            description="Deploy v2 pipeline",
            steps=_steps(),
            requester="analyst@test.com",
        )
        assert wf.workflow_id.startswith("wf_")
        assert wf.status.value == "pending"
        assert len(wf.steps) == 2

    def test_workflow_to_dict(self, mgr):
        wf = mgr.create_workflow("test", "test desc", _steps(), "user@test.com")
        d = wf.to_dict()
        assert d["action"] == "test"
        assert d["total_steps"] == 2
        assert d["current_step"] == 0


class TestMultiStepApproval:

    def test_approve_first_step(self, mgr):
        wf = mgr.create_workflow("test", "desc", _steps(), "user@test.com")
        result = mgr.approve_step(wf.workflow_id, "analyst1", "ANALYST", "LGTM")
        assert result is not None
        assert result.status.value == "in_progress"
        assert result.steps[0].status.value == "approved"
        assert result.steps[1].status.value == "pending"

    def test_approve_all_steps(self, mgr):
        wf = mgr.create_workflow("test", "desc", _steps(), "user@test.com")
        mgr.approve_step(wf.workflow_id, "analyst1", "ANALYST")
        result = mgr.approve_step(wf.workflow_id, "admin1", "ADMIN")
        assert result.status.value == "approved"
        assert all(s.status.value == "approved" for s in result.steps)

    def test_admin_can_approve_any_step(self, mgr):
        wf = mgr.create_workflow("test", "desc", _steps(), "user@test.com")
        # ADMIN can approve ANALYST step
        result = mgr.approve_step(wf.workflow_id, "admin1", "ADMIN")
        assert result is not None
        assert result.steps[0].status.value == "approved"

    def test_wrong_role_denied(self, mgr):
        wf = mgr.create_workflow("test", "desc", _steps(), "user@test.com")
        # USER cannot approve ANALYST step
        result = mgr.approve_step(wf.workflow_id, "user1", "USER")
        assert result is None


class TestWorkflowDenial:

    def test_deny_step(self, mgr):
        wf = mgr.create_workflow("test", "desc", _steps(), "user@test.com")
        result = mgr.deny_step(wf.workflow_id, "analyst1", "Not safe")
        assert result.status.value == "denied"
        assert result.steps[0].status.value == "denied"
        assert result.steps[1].status.value == "skipped"

    def test_deny_nonexistent(self, mgr):
        result = mgr.deny_step("nonexistent", "user")
        assert result is None


class TestWorkflowCancellation:

    def test_cancel_pending(self, mgr):
        wf = mgr.create_workflow("test", "desc", _steps(), "user@test.com")
        result = mgr.cancel_workflow(wf.workflow_id, "user@test.com")
        assert result.status.value == "cancelled"

    def test_cannot_cancel_approved(self, mgr):
        wf = mgr.create_workflow("test", "desc", _steps(), "user@test.com")
        mgr.approve_step(wf.workflow_id, "analyst1", "ANALYST")
        mgr.approve_step(wf.workflow_id, "admin1", "ADMIN")
        result = mgr.cancel_workflow(wf.workflow_id, "user@test.com")
        assert result is None  # Already approved


class TestWorkflowQueries:

    def test_get_pending(self, mgr):
        mgr.create_workflow("test1", "desc", _steps(), "user@test.com")
        mgr.create_workflow("test2", "desc", _steps(), "user@test.com")
        pending = mgr.get_pending()
        assert len(pending) == 2

    def test_get_pending_by_role(self, mgr):
        mgr.create_workflow("test1", "desc", _steps(), "user@test.com")
        pending_analyst = mgr.get_pending(role="ANALYST")
        pending_admin = mgr.get_pending(role="ADMIN")
        assert len(pending_analyst) == 1  # First step needs ANALYST
        assert len(pending_admin) == 0    # ADMIN step not active yet

    def test_get_history(self, mgr):
        wf = mgr.create_workflow("test", "desc", _steps(), "user@test.com")
        mgr.deny_step(wf.workflow_id, "analyst1", "rejected")
        history = mgr.get_history()
        assert len(history) == 1


class TestChangeWindows:

    def test_list_change_windows(self, mgr):
        windows = mgr.get_change_windows()
        assert len(windows) >= 4
        assert any(w["name"] == "business_hours" for w in windows)
        assert any(w["name"] == "always_open" for w in windows)

    def test_always_open_window(self, mgr):
        windows = mgr.get_change_windows()
        always_open = next(w for w in windows if w["name"] == "always_open")
        assert always_open["currently_open"] is True  # Disabled = always open


class TestStats:

    def test_stats_structure(self, mgr):
        mgr.create_workflow("test", "desc", _steps(), "user@test.com")
        stats = mgr.get_stats()
        assert stats["total_workflows"] == 1
        assert stats["pending_count"] == 1
        assert "by_status" in stats
