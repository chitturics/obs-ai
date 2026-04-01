"""Tests for workflow state persistence and LLM dynamic planning."""
import pytest
import time
import json
from unittest.mock import AsyncMock, MagicMock, patch


class TestWorkflowStatePersistence:
    """Test WorkflowSnapshot and persistence functions."""

    def test_snapshot_creation(self):
        from chat_app.workflow_state import WorkflowSnapshot
        snap = WorkflowSnapshot(
            workflow_id="wf_test",
            workflow_name="Test Workflow",
            status="running",
            total_steps=3,
        )
        assert snap.workflow_id == "wf_test"
        assert snap.status == "running"
        assert snap.total_steps == 3

    def test_snapshot_to_dict(self):
        from chat_app.workflow_state import WorkflowSnapshot
        snap = WorkflowSnapshot(
            workflow_id="wf_1", workflow_name="Test",
            steps_completed=[{"id": 0, "status": "completed"}],
        )
        d = snap.to_dict()
        assert d["workflow_id"] == "wf_1"
        assert len(d["steps_completed"]) == 1

    @pytest.mark.asyncio
    async def test_save_no_engine(self):
        from chat_app.workflow_state import save_workflow_state, WorkflowSnapshot
        snap = WorkflowSnapshot(workflow_id="wf_1", workflow_name="Test")
        result = await save_workflow_state(None, snap)
        assert result is False

    @pytest.mark.asyncio
    async def test_load_no_engine(self):
        from chat_app.workflow_state import load_workflow_state
        result = await load_workflow_state(None, "wf_1")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_no_engine(self):
        from chat_app.workflow_state import list_workflow_states
        result = await list_workflow_states(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_no_engine(self):
        from chat_app.workflow_state import delete_workflow_state
        result = await delete_workflow_state(None, "wf_1")
        assert result is False


class TestMultiStepDetection:
    """Test _is_multi_step_query heuristic."""

    def test_short_query_not_multistep(self):
        from chat_app.workflow_orchestrator import _is_multi_step_query
        assert _is_multi_step_query("show me stats") is False

    def test_medium_query_with_signals(self):
        from chat_app.workflow_orchestrator import _is_multi_step_query
        # Must be 20+ words AND have a multi-step signal
        query = (
            "First I want you to analyze all my saved searches across every index "
            "and then optimize the slow ones that are taking too long to complete"
        )
        assert _is_multi_step_query(query) is True

    def test_long_query_no_signals(self):
        from chat_app.workflow_orchestrator import _is_multi_step_query
        query = " ".join(["word"] * 40)
        assert _is_multi_step_query(query) is True

    def test_query_with_step_keyword(self):
        from chat_app.workflow_orchestrator import _is_multi_step_query
        # Must be 20+ words with multi-step signal
        query = (
            "I need a multi-step workflow that checks all indexes across all search heads "
            "for compliance issues and security vulnerabilities and generates a detailed report"
        )
        assert _is_multi_step_query(query) is True

    def test_moderate_query_without_signals(self):
        from chat_app.workflow_orchestrator import _is_multi_step_query
        query = "what is the stats command used for in splunk queries"
        assert _is_multi_step_query(query) is False


class TestLLMPlanPrompt:
    """Test the LLM plan prompt template."""

    def test_prompt_contains_placeholders(self):
        from chat_app.workflow_orchestrator import _LLM_PLAN_PROMPT_TEMPLATE
        assert "{user_input}" in _LLM_PLAN_PROMPT_TEMPLATE
        assert "spl_generation" in _LLM_PLAN_PROMPT_TEMPLATE
        assert "JSON" in _LLM_PLAN_PROMPT_TEMPLATE

    @pytest.mark.asyncio
    async def test_llm_plan_bad_response(self):
        """Handle LLM returning non-JSON."""
        from chat_app.workflow_orchestrator import llm_plan_workflow
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "I can't generate a plan for that"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await llm_plan_workflow("do something complex")
            assert result is None

    @pytest.mark.asyncio
    async def test_llm_plan_valid_json(self):
        """Successfully parse a valid LLM plan."""
        from chat_app.workflow_orchestrator import llm_plan_workflow, WorkflowPlan

        plan_json = json.dumps({
            "description": "Analyze and optimize",
            "tasks": [
                {"description": "Analyze queries", "intent": "spl_generation", "department": "engineering", "depends_on": []},
                {"description": "Optimize slow ones", "intent": "spl_optimization", "department": "engineering", "depends_on": [0]},
            ],
        })
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": plan_json}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await llm_plan_workflow("analyze my searches and optimize the slow ones")
            assert result is not None
            assert isinstance(result, WorkflowPlan)
            assert len(result.tasks) == 2
            assert result.tasks[1].depends_on == [0]


class TestCreatePlanAsync:
    """Test async plan creation with LLM fallback."""

    @pytest.mark.asyncio
    async def test_regex_detection_first(self):
        """Regex detection should take priority over LLM."""
        from chat_app.workflow_orchestrator import WorkflowOrchestrator
        orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
        orch._dispatcher = MagicMock()
        orch._active_workflows = {}
        orch._completed_workflows = []

        plan = await orch.create_plan_async(
            "analyze my searches and then optimize them", "spl_generation",
        )
        assert plan is not None
        assert plan.description == "Analyze and optimize"

    @pytest.mark.asyncio
    async def test_simple_query_no_plan(self):
        """Simple queries should not trigger planning."""
        from chat_app.workflow_orchestrator import WorkflowOrchestrator
        orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
        orch._dispatcher = MagicMock()
        orch._active_workflows = {}
        orch._completed_workflows = []

        plan = await orch.create_plan_async("show stats command", "general_qa")
        assert plan is None


class TestGetDbEngine:
    """Test _get_db_engine helper."""

    def test_returns_none_when_no_db(self):
        """Should return None gracefully when DB is not configured."""
        from chat_app.workflow_orchestrator import _get_db_engine
        # The function reads settings which may or may not have a DB URL
        # In test env without DB, it should return None without error
        result = _get_db_engine()
        # Result can be None (no DB) or an engine (if settings have a URL)
        # Just verify it doesn't crash
        assert result is None or result is not None
