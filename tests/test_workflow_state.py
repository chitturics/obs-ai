"""Tests for workflow state persistence."""
import pytest
from chat_app.workflow_state import WorkflowSnapshot, save_workflow_state, load_workflow_state, list_workflow_states


class TestWorkflowSnapshot:
    def test_create_snapshot(self):
        snap = WorkflowSnapshot(
            workflow_id="wf-001",
            workflow_name="test_workflow",
            status="running",
            current_step=2,
            total_steps=5,
        )
        assert snap.workflow_id == "wf-001"
        assert snap.status == "running"

    def test_to_dict(self):
        snap = WorkflowSnapshot(
            workflow_id="wf-002",
            workflow_name="test",
        )
        d = snap.to_dict()
        assert d["workflow_id"] == "wf-002"
        assert "status" in d
        assert "context" in d

    def test_defaults(self):
        snap = WorkflowSnapshot(
            workflow_id="wf-003",
            workflow_name="test",
        )
        assert snap.status == "running"
        assert snap.current_step == 0
        assert snap.steps_completed == []
        assert snap.context == {}


class TestPersistenceNoEngine:
    @pytest.mark.asyncio
    async def test_save_no_engine(self):
        snap = WorkflowSnapshot(workflow_id="wf-test", workflow_name="test")
        result = await save_workflow_state(None, snap)
        assert result is False

    @pytest.mark.asyncio
    async def test_load_no_engine(self):
        result = await load_workflow_state(None, "wf-test")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_no_engine(self):
        result = await list_workflow_states(None)
        assert result == []
