"""
Tests for WorkflowOrchestrator -- multi-agent coordination for complex tasks.

Covers:
- TaskStatus enum
- WorkflowTask dataclass
- WorkflowPlan dataclass
- WorkflowResult dataclass
- Workflow templates
- detect_workflow()
- WorkflowOrchestrator methods (create_plan, execute_workflow, _execute_task, etc.)
- Singleton get_workflow_orchestrator()
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat_app.workflow_orchestrator import (
    APPROVAL_REQUIRED_INTENTS,
    WORKFLOW_TEMPLATES,
    TaskStatus,
    ValidatedWorkflowPlan,
    ValidatedWorkflowStep,
    WorkflowOrchestrator,
    WorkflowPlan,
    WorkflowResult,
    WorkflowTask,
    _build_validated_plan,
    _parse_llm_plan_response,
    _template_analyze_and_optimize,
    _template_build_and_deploy,
    _template_investigate,
    _template_security_audit,
    _template_troubleshoot,
    _validated_plan_to_workflow,
    detect_workflow,
    get_workflow_orchestrator,
    validate_plan_capabilities,
)
from chat_app.agent_catalog import Department
from chat_app.agent_dispatcher import AgentDispatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dispatch_result(
    success: bool = True,
    enriched_context: str = "mock output",
    agent_name: str = "mock_agent",
    error: str = None,
) -> AgentDispatchResult:
    return AgentDispatchResult(
        agent_name=agent_name,
        agent_role="test_role",
        department="engineering",
        skills_executed=["skill_a"],
        enriched_context=enriched_context,
        success=success,
        error=error,
    )


def _make_dispatcher_mock(
    results=None,
    default_success=True,
    default_output="mock output",
) -> MagicMock:
    """Create a mock dispatcher with an async dispatch method."""
    dispatcher = MagicMock()
    if results:
        dispatcher.dispatch = AsyncMock(side_effect=results)
    else:
        dispatcher.dispatch = AsyncMock(
            return_value=_make_dispatch_result(
                success=default_success,
                enriched_context=default_output,
            )
        )
    return dispatcher


# ---------------------------------------------------------------------------
# 1. TaskStatus enum
# ---------------------------------------------------------------------------

class TestTaskStatus:
    def test_all_values_present(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.SKIPPED == "skipped"

    def test_enum_count(self):
        assert len(TaskStatus) == 8  # 5 original + 3 pause/resume states

    def test_is_str_enum(self):
        assert isinstance(TaskStatus.PENDING, str)

    def test_values_from_string(self):
        assert TaskStatus("pending") is TaskStatus.PENDING
        assert TaskStatus("completed") is TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# 2. WorkflowTask dataclass
# ---------------------------------------------------------------------------

class TestWorkflowTask:
    def test_defaults(self):
        task = WorkflowTask(id=0, description="Test", intent="general_qa")
        assert task.agent_name == ""
        assert task.preferred_department is None
        assert task.depends_on == []
        assert task.params == {}
        assert task.status == TaskStatus.PENDING
        assert task.result is None
        assert task.error is None
        assert task.duration_ms == 0.0

    def test_output_with_result(self):
        result = _make_dispatch_result(enriched_context="hello world")
        task = WorkflowTask(id=0, description="T", intent="x", result=result)
        assert task.output == "hello world"

    def test_output_without_result(self):
        task = WorkflowTask(id=0, description="T", intent="x")
        assert task.output == ""

    def test_output_result_no_enriched_context(self):
        result = _make_dispatch_result(enriched_context="")
        task = WorkflowTask(id=0, description="T", intent="x", result=result)
        assert task.output == ""

    def test_status_transitions(self):
        task = WorkflowTask(id=0, description="T", intent="x")
        assert task.status == TaskStatus.PENDING
        task.status = TaskStatus.RUNNING
        assert task.status == TaskStatus.RUNNING
        task.status = TaskStatus.COMPLETED
        assert task.status == TaskStatus.COMPLETED

    def test_status_to_failed(self):
        task = WorkflowTask(id=0, description="T", intent="x")
        task.status = TaskStatus.FAILED
        task.error = "something broke"
        assert task.status == TaskStatus.FAILED
        assert task.error == "something broke"

    def test_depends_on_list(self):
        task = WorkflowTask(id=2, description="T", intent="x", depends_on=[0, 1])
        assert task.depends_on == [0, 1]

    def test_params_dict(self):
        task = WorkflowTask(
            id=0, description="T", intent="x",
            params={"user_input": "hello", "key": "val"},
        )
        assert task.params["user_input"] == "hello"

    def test_preferred_department(self):
        task = WorkflowTask(
            id=0, description="T", intent="x",
            preferred_department=Department.SECURITY,
        )
        assert task.preferred_department == Department.SECURITY


# ---------------------------------------------------------------------------
# 3. WorkflowPlan dataclass
# ---------------------------------------------------------------------------

class TestWorkflowPlan:
    def test_empty_plan(self):
        plan = WorkflowPlan(description="empty")
        assert plan.total_tasks == 0
        assert plan.completed_tasks == 0
        assert plan.failed_tasks == 0
        assert plan.progress_pct == 100.0

    def test_total_tasks(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x"),
            WorkflowTask(id=1, description="B", intent="x"),
            WorkflowTask(id=2, description="C", intent="x"),
        ])
        assert plan.total_tasks == 3

    def test_completed_tasks(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x", status=TaskStatus.COMPLETED),
            WorkflowTask(id=1, description="B", intent="x", status=TaskStatus.PENDING),
            WorkflowTask(id=2, description="C", intent="x", status=TaskStatus.COMPLETED),
        ])
        assert plan.completed_tasks == 2

    def test_failed_tasks(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x", status=TaskStatus.FAILED),
            WorkflowTask(id=1, description="B", intent="x", status=TaskStatus.COMPLETED),
            WorkflowTask(id=2, description="C", intent="x", status=TaskStatus.FAILED),
        ])
        assert plan.failed_tasks == 2

    def test_progress_pct_none_done(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x"),
            WorkflowTask(id=1, description="B", intent="x"),
        ])
        assert plan.progress_pct == 0.0

    def test_progress_pct_partial(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x", status=TaskStatus.COMPLETED),
            WorkflowTask(id=1, description="B", intent="x"),
            WorkflowTask(id=2, description="C", intent="x"),
        ])
        assert plan.progress_pct == pytest.approx(33.3, abs=0.1)

    def test_progress_pct_all_done(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x", status=TaskStatus.COMPLETED),
            WorkflowTask(id=1, description="B", intent="x", status=TaskStatus.COMPLETED),
        ])
        assert plan.progress_pct == 100.0

    def test_progress_pct_includes_skipped(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x", status=TaskStatus.SKIPPED),
            WorkflowTask(id=1, description="B", intent="x", status=TaskStatus.PENDING),
        ])
        assert plan.progress_pct == 50.0

    def test_get_ready_tasks_no_deps(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x"),
            WorkflowTask(id=1, description="B", intent="x"),
        ])
        ready = plan.get_ready_tasks()
        assert len(ready) == 2

    def test_get_ready_tasks_with_deps(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x", status=TaskStatus.COMPLETED),
            WorkflowTask(id=1, description="B", intent="x", depends_on=[0]),
            WorkflowTask(id=2, description="C", intent="x", depends_on=[0, 1]),
        ])
        ready = plan.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == 1

    def test_get_ready_tasks_dep_not_met(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x"),
            WorkflowTask(id=1, description="B", intent="x", depends_on=[0]),
        ])
        ready = plan.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == 0

    def test_get_ready_tasks_none_pending(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x", status=TaskStatus.COMPLETED),
            WorkflowTask(id=1, description="B", intent="x", status=TaskStatus.COMPLETED),
        ])
        ready = plan.get_ready_tasks()
        assert len(ready) == 0

    def test_get_ready_tasks_running_excluded(self):
        plan = WorkflowPlan(description="test", tasks=[
            WorkflowTask(id=0, description="A", intent="x", status=TaskStatus.RUNNING),
            WorkflowTask(id=1, description="B", intent="x", depends_on=[0]),
        ])
        ready = plan.get_ready_tasks()
        assert len(ready) == 0

    def test_created_at_is_populated(self):
        before = time.time()
        plan = WorkflowPlan(description="test")
        after = time.time()
        assert before <= plan.created_at <= after


# ---------------------------------------------------------------------------
# 4. WorkflowResult dataclass
# ---------------------------------------------------------------------------

class TestWorkflowResult:
    def test_to_dict_keys(self):
        result = WorkflowResult(
            plan_description="test",
            tasks_completed=2,
            tasks_failed=1,
            tasks_total=3,
            combined_output="output",
            duration_ms=123.456,
            success=False,
        )
        d = result.to_dict()
        assert d["description"] == "test"
        assert d["completed"] == 2
        assert d["failed"] == 1
        assert d["total"] == 3
        assert d["success"] is False
        assert d["duration_ms"] == 123.46
        assert "agent_trace" in d

    def test_to_dict_rounds_duration(self):
        result = WorkflowResult(
            plan_description="t", tasks_completed=0, tasks_failed=0,
            tasks_total=0, combined_output="", duration_ms=99.999,
        )
        assert result.to_dict()["duration_ms"] == 100.0

    def test_success_default_true(self):
        result = WorkflowResult(
            plan_description="t", tasks_completed=1, tasks_failed=0,
            tasks_total=1, combined_output="",
        )
        assert result.success is True

    def test_agent_trace_default_empty(self):
        result = WorkflowResult(
            plan_description="t", tasks_completed=0, tasks_failed=0,
            tasks_total=0, combined_output="",
        )
        assert result.agent_trace == []

    def test_to_dict_includes_agent_trace(self):
        trace = [{"task_id": 0, "agent": "a", "success": True}]
        result = WorkflowResult(
            plan_description="t", tasks_completed=1, tasks_failed=0,
            tasks_total=1, combined_output="", agent_trace=trace,
        )
        assert result.to_dict()["agent_trace"] == trace


# ---------------------------------------------------------------------------
# 5. Workflow templates
# ---------------------------------------------------------------------------

class TestWorkflowTemplates:
    def test_all_five_templates_registered(self):
        expected = {
            "analyze_and_optimize", "troubleshoot", "build_and_deploy",
            "investigate", "security_audit",
        }
        assert set(WORKFLOW_TEMPLATES.keys()) == expected

    def test_analyze_and_optimize_plan(self):
        plan = _template_analyze_and_optimize("test input")
        assert plan.description == "Analyze and optimize"
        assert plan.total_tasks == 3
        assert plan.tasks[0].depends_on == []
        assert plan.tasks[1].depends_on == [0]
        assert plan.tasks[2].depends_on == [1]
        assert plan.tasks[0].preferred_department == Department.ENGINEERING

    def test_troubleshoot_plan(self):
        plan = _template_troubleshoot("test input")
        assert plan.description == "Troubleshoot and diagnose"
        assert plan.total_tasks == 3
        assert plan.tasks[0].depends_on == []
        assert plan.tasks[1].depends_on == [0]
        assert plan.tasks[2].depends_on == [0, 1]
        assert plan.tasks[0].preferred_department == Department.SUPPORT

    def test_build_and_deploy_plan(self):
        plan = _template_build_and_deploy("test input")
        assert plan.description == "Build, validate, and deploy"
        assert plan.total_tasks == 3
        assert plan.tasks[0].depends_on == []
        assert plan.tasks[1].depends_on == [0]
        assert plan.tasks[2].depends_on == [1]
        assert plan.tasks[0].preferred_department == Department.ENGINEERING

    def test_investigate_plan(self):
        plan = _template_investigate("test input")
        assert plan.description == "Investigate and report"
        assert plan.total_tasks == 3
        assert plan.tasks[0].depends_on == []
        assert plan.tasks[1].depends_on == [0]
        assert plan.tasks[2].depends_on == [0, 1]
        assert plan.tasks[0].preferred_department == Department.KNOWLEDGE
        assert plan.tasks[1].preferred_department == Department.DATA

    def test_security_audit_plan(self):
        plan = _template_security_audit("test input")
        assert plan.description == "Security audit"
        assert plan.total_tasks == 3
        assert plan.tasks[0].depends_on == []
        assert plan.tasks[1].depends_on == [0]
        assert plan.tasks[2].depends_on == [0, 1]
        assert plan.tasks[0].preferred_department == Department.SECURITY

    def test_templates_pass_user_input_to_params(self):
        for name, tmpl_fn in WORKFLOW_TEMPLATES.items():
            plan = tmpl_fn("my custom input")
            for task in plan.tasks:
                assert task.params.get("user_input") == "my custom input", \
                    f"Template '{name}' task {task.id} missing user_input param"

    def test_templates_all_have_three_tasks(self):
        for name, tmpl_fn in WORKFLOW_TEMPLATES.items():
            plan = tmpl_fn("x")
            assert plan.total_tasks == 3, f"Template '{name}' should have 3 tasks"

    def test_templates_task_ids_sequential(self):
        for name, tmpl_fn in WORKFLOW_TEMPLATES.items():
            plan = tmpl_fn("x")
            ids = [t.id for t in plan.tasks]
            assert ids == [0, 1, 2], f"Template '{name}' task IDs should be [0,1,2]"

    def test_templates_first_task_has_no_deps(self):
        for name, tmpl_fn in WORKFLOW_TEMPLATES.items():
            plan = tmpl_fn("x")
            assert plan.tasks[0].depends_on == [], \
                f"Template '{name}' first task should have no dependencies"


# ---------------------------------------------------------------------------
# 6. detect_workflow()
# ---------------------------------------------------------------------------

class TestDetectWorkflow:
    def test_analyze_and_optimize_pattern(self):
        assert detect_workflow("analyze my searches and optimize them", "general_qa") == "analyze_and_optimize"

    def test_optimize_and_validate_pattern(self):
        assert detect_workflow("optimize my query and then validate it", "general_qa") == "analyze_and_optimize"

    def test_troubleshoot_pattern(self):
        assert detect_workflow("troubleshoot why my search is not working", "general_qa") == "troubleshoot"

    def test_debug_pattern(self):
        assert detect_workflow("debug why my forwarder is failing", "general_qa") == "troubleshoot"

    def test_diagnose_pattern(self):
        assert detect_workflow("diagnose the problem with my index", "general_qa") == "troubleshoot"

    def test_build_and_deploy_pattern(self):
        assert detect_workflow("create a dashboard and then deploy it", "general_qa") == "build_and_deploy"

    def test_investigate_pattern(self):
        assert detect_workflow("investigate the log volume increase", "general_qa") == "investigate"

    def test_research_pattern(self):
        assert detect_workflow("research how tstats works", "general_qa") == "investigate"

    def test_security_audit_pattern(self):
        assert detect_workflow("run a security audit on my deployment", "general_qa") == "security_audit"

    def test_vulnerability_pattern(self):
        assert detect_workflow("check for vulnerability in config", "general_qa") == "security_audit"

    def test_compare_and_fix_pattern(self):
        assert detect_workflow("compare my queries and then fix them", "general_qa") == "analyze_and_optimize"

    def test_simple_query_returns_none(self):
        assert detect_workflow("hello", "general_qa") is None

    def test_short_query_no_match(self):
        assert detect_workflow("show me stats", "general_qa") is None

    def test_intent_fallback_troubleshooting_long_query(self):
        long_query = "x" * 51
        assert detect_workflow(long_query, "troubleshooting") == "troubleshoot"

    def test_intent_fallback_security_long_query(self):
        long_query = "x" * 51
        # "security" is a RoutingTag, not an Intent; config_health_check is the
        # closest valid Intent for security audit workflows
        assert detect_workflow(long_query, "config_health_check") == "security_audit"

    def test_intent_fallback_short_query_ignored(self):
        short_query = "x" * 50
        assert detect_workflow(short_query, "troubleshooting") is None

    def test_intent_fallback_unknown_intent(self):
        long_query = "x" * 60
        assert detect_workflow(long_query, "general_qa") is None

    def test_case_insensitivity(self):
        assert detect_workflow("INVESTIGATE the logs", "general_qa") == "investigate"

    def test_analyze_then_improve(self):
        assert detect_workflow("analyze the config then improve it", "general_qa") == "analyze_and_optimize"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_dispatcher():
    return _make_dispatcher_mock()


@pytest.fixture
def orchestrator(mock_dispatcher):
    return WorkflowOrchestrator(dispatcher=mock_dispatcher)


# ---------------------------------------------------------------------------
# 7. WorkflowOrchestrator.create_plan()
# ---------------------------------------------------------------------------

class TestCreatePlan:
    def test_create_plan_with_template(self, orchestrator):
        plan = orchestrator.create_plan("test", "general_qa", template_name="troubleshoot")
        assert plan is not None
        assert plan.description == "Troubleshoot and diagnose"

    def test_create_plan_auto_detect(self, orchestrator):
        plan = orchestrator.create_plan(
            "investigate the data loss", "general_qa",
        )
        assert plan is not None
        assert plan.description == "Investigate and report"

    def test_create_plan_returns_none_simple_query(self, orchestrator):
        plan = orchestrator.create_plan("hello", "general_qa")
        assert plan is None

    def test_create_plan_invalid_template_falls_back_to_auto(self, orchestrator):
        plan = orchestrator.create_plan(
            "investigate the log issue", "general_qa",
            template_name="nonexistent_template",
        )
        # Auto-detect should still match "investigate"
        assert plan is not None

    def test_create_plan_invalid_template_no_auto_match(self, orchestrator):
        plan = orchestrator.create_plan("hello", "general_qa", template_name="bad")
        assert plan is None

    def test_create_plan_each_template_by_name(self, orchestrator):
        for tname in WORKFLOW_TEMPLATES:
            plan = orchestrator.create_plan("test", "x", template_name=tname)
            assert plan is not None, f"Template '{tname}' should create a plan"
            assert plan.total_tasks == 3


# ---------------------------------------------------------------------------
# 8. WorkflowOrchestrator.execute_workflow()
# ---------------------------------------------------------------------------

class TestExecuteWorkflow:
    @pytest.mark.asyncio
    async def test_execute_all_tasks_sequentially(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        plan = _template_analyze_and_optimize("test")
        result = await orch.execute_workflow(plan, "test")
        assert result.tasks_completed == 3
        assert result.tasks_failed == 0
        assert result.success is True
        assert mock_dispatcher.dispatch.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_handles_failure(self):
        dispatcher = _make_dispatcher_mock(
            results=[
                _make_dispatch_result(success=True, enriched_context="step1"),
                _make_dispatch_result(success=False, error="step2 error"),
                _make_dispatch_result(success=True, enriched_context="step3"),
            ]
        )
        orch = WorkflowOrchestrator(dispatcher=dispatcher)
        plan = _template_analyze_and_optimize("test")
        result = await orch.execute_workflow(plan, "test")
        assert result.tasks_failed >= 1
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_records_agent_trace(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        plan = _template_analyze_and_optimize("test")
        result = await orch.execute_workflow(plan, "test")
        assert len(result.agent_trace) == 3
        for entry in result.agent_trace:
            assert "task_id" in entry
            assert "agent" in entry
            assert "success" in entry
            assert "duration_ms" in entry

    @pytest.mark.asyncio
    async def test_execute_combined_output_contains_steps(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        plan = _template_analyze_and_optimize("test")
        result = await orch.execute_workflow(plan, "test")
        assert "Step 1" in result.combined_output
        assert "Step 2" in result.combined_output
        assert "Step 3" in result.combined_output

    @pytest.mark.asyncio
    async def test_execute_stores_in_completed(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        plan = _template_analyze_and_optimize("test")
        await orch.execute_workflow(plan, "test")
        assert len(orch._completed_workflows) == 1

    @pytest.mark.asyncio
    async def test_execute_removes_active_workflow_after(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        plan = _template_analyze_and_optimize("test")
        await orch.execute_workflow(plan, "test")
        assert len(orch._active_workflows) == 0

    @pytest.mark.asyncio
    async def test_execute_parallel_tasks(self, mock_dispatcher):
        """Tasks with all deps met should run in parallel."""
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        plan = WorkflowPlan(description="parallel test", tasks=[
            WorkflowTask(id=0, description="A", intent="x"),
            WorkflowTask(id=1, description="B", intent="x"),
            WorkflowTask(id=2, description="C", intent="x", depends_on=[0, 1]),
        ])
        result = await orch.execute_workflow(plan, "test")
        assert result.tasks_completed == 3
        assert result.success is True

    @pytest.mark.asyncio
    @patch("chat_app.workflow_orchestrator.TASK_MAX_RETRIES", 0)
    async def test_execute_failed_output_in_combined(self):
        dispatcher = _make_dispatcher_mock(
            results=[
                _make_dispatch_result(success=False, error="boom"),
            ]
        )
        orch = WorkflowOrchestrator(dispatcher=dispatcher)
        plan = WorkflowPlan(description="fail test", tasks=[
            WorkflowTask(id=0, description="FailTask", intent="x"),
        ])
        result = await orch.execute_workflow(plan, "test")
        assert "Failed" in result.combined_output
        assert "boom" in result.combined_output

    @pytest.mark.asyncio
    async def test_execute_duration_ms_is_positive(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        plan = _template_investigate("test")
        result = await orch.execute_workflow(plan, "test")
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_execute_caps_completed_history_at_50(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        for i in range(55):
            plan = WorkflowPlan(description=f"wf_{i}", tasks=[
                WorkflowTask(id=0, description="T", intent="x"),
            ])
            await orch.execute_workflow(plan, "test")
        assert len(orch._completed_workflows) == 50

    @pytest.mark.asyncio
    async def test_execute_exception_in_dispatch(self):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("dispatcher exploded"))
        orch = WorkflowOrchestrator(dispatcher=dispatcher)
        plan = WorkflowPlan(description="boom", tasks=[
            WorkflowTask(id=0, description="T", intent="x"),
        ])
        result = await orch.execute_workflow(plan, "test")
        assert result.tasks_failed == 1
        assert result.success is False
        assert plan.tasks[0].error == "dispatcher exploded"


# ---------------------------------------------------------------------------
# 9. WorkflowOrchestrator._execute_task()
# ---------------------------------------------------------------------------

class TestExecuteTask:
    @pytest.mark.asyncio
    async def test_task_set_to_running_then_completed(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        task = WorkflowTask(id=0, description="T", intent="x", params={"user_input": "hi"})
        trace = []
        # We need the task to be in an active workflow for dependency context
        plan = WorkflowPlan(description="test", tasks=[task])
        orch._active_workflows["test_wf"] = plan
        await orch._execute_task(task, "hi", trace)
        assert task.status == TaskStatus.COMPLETED
        assert task.agent_name == "mock_agent"
        assert len(trace) == 1

    @pytest.mark.asyncio
    @patch("chat_app.workflow_orchestrator.TASK_MAX_RETRIES", 0)
    async def test_task_failed_on_dispatch_failure(self):
        dispatcher = _make_dispatcher_mock(
            results=[_make_dispatch_result(success=False, error="nope")]
        )
        orch = WorkflowOrchestrator(dispatcher=dispatcher)
        task = WorkflowTask(id=0, description="T", intent="x")
        trace = []
        await orch._execute_task(task, "hi", trace)
        assert task.status == TaskStatus.FAILED
        assert task.error == "nope"

    @pytest.mark.asyncio
    @patch("chat_app.workflow_orchestrator.TASK_MAX_RETRIES", 0)
    async def test_task_exception_records_error(self):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(side_effect=ValueError("bad value"))
        orch = WorkflowOrchestrator(dispatcher=dispatcher)
        task = WorkflowTask(id=0, description="T", intent="x")
        trace = []
        await orch._execute_task(task, "hi", trace)
        assert task.status == TaskStatus.FAILED
        assert "bad value" in task.error
        assert task.duration_ms > 0

    @pytest.mark.asyncio
    async def test_task_passes_prior_context_from_deps(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        dep_task = WorkflowTask(
            id=0, description="dep", intent="x",
            status=TaskStatus.COMPLETED,
            result=_make_dispatch_result(enriched_context="dep output"),
        )
        main_task = WorkflowTask(
            id=1, description="main", intent="x",
            depends_on=[0], params={"user_input": "q"},
        )
        plan = WorkflowPlan(description="test", tasks=[dep_task, main_task])
        orch._active_workflows["wf1"] = plan
        trace = []
        await orch._execute_task(main_task, "q", trace)
        call_kwargs = mock_dispatcher.dispatch.call_args
        assert "prior_context" in call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {})) or \
               "prior_context" in (call_kwargs[1].get("params") or {})

    @pytest.mark.asyncio
    async def test_task_trace_entry_structure(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        task = WorkflowTask(id=7, description="do stuff", intent="x")
        trace = []
        await orch._execute_task(task, "q", trace)
        entry = trace[0]
        assert entry["task_id"] == 7
        assert entry["description"] == "do stuff"
        assert entry["agent"] == "mock_agent"
        assert entry["skills"] == ["skill_a"]
        assert entry["success"] is True
        assert isinstance(entry["duration_ms"], float)

    @pytest.mark.asyncio
    async def test_task_duration_recorded(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        task = WorkflowTask(id=0, description="T", intent="x")
        trace = []
        await orch._execute_task(task, "q", trace)
        assert task.duration_ms >= 0


# ---------------------------------------------------------------------------
# 10. WorkflowOrchestrator._get_dependency_context()
# ---------------------------------------------------------------------------

class TestGetDependencyContext:
    def test_no_active_workflow_returns_empty(self, orchestrator):
        task = WorkflowTask(id=1, description="T", intent="x", depends_on=[0])
        result = orchestrator._get_dependency_context(task)
        assert result == ""

    def test_combines_dependency_outputs(self, orchestrator):
        dep0 = WorkflowTask(
            id=0, description="dep0", intent="x",
            status=TaskStatus.COMPLETED,
            result=_make_dispatch_result(enriched_context="output A"),
        )
        dep1 = WorkflowTask(
            id=1, description="dep1", intent="x",
            status=TaskStatus.COMPLETED,
            result=_make_dispatch_result(enriched_context="output B"),
        )
        main = WorkflowTask(id=2, description="main", intent="x", depends_on=[0, 1])
        plan = WorkflowPlan(description="test", tasks=[dep0, dep1, main])
        orchestrator._active_workflows["wf_test"] = plan
        ctx = orchestrator._get_dependency_context(main)
        assert "output A" in ctx
        assert "output B" in ctx

    def test_skips_incomplete_dep(self, orchestrator):
        dep0 = WorkflowTask(
            id=0, description="dep0", intent="x",
            status=TaskStatus.COMPLETED,
            result=_make_dispatch_result(enriched_context="yes"),
        )
        dep1 = WorkflowTask(
            id=1, description="dep1", intent="x",
            status=TaskStatus.PENDING,
        )
        main = WorkflowTask(id=2, description="main", intent="x", depends_on=[0, 1])
        plan = WorkflowPlan(description="test", tasks=[dep0, dep1, main])
        orchestrator._active_workflows["wf_test"] = plan
        ctx = orchestrator._get_dependency_context(main)
        assert "yes" in ctx
        assert ctx.count("\n\n") == 0  # Only one part, no double-newline joiner

    def test_no_deps_returns_empty(self, orchestrator):
        task = WorkflowTask(id=0, description="T", intent="x")
        plan = WorkflowPlan(description="test", tasks=[task])
        orchestrator._active_workflows["wf_test"] = plan
        ctx = orchestrator._get_dependency_context(task)
        assert ctx == ""

    def test_dep_completed_but_no_output(self, orchestrator):
        dep0 = WorkflowTask(
            id=0, description="dep0", intent="x",
            status=TaskStatus.COMPLETED,
            result=_make_dispatch_result(enriched_context=""),
        )
        main = WorkflowTask(id=1, description="main", intent="x", depends_on=[0])
        plan = WorkflowPlan(description="test", tasks=[dep0, main])
        orchestrator._active_workflows["wf_test"] = plan
        ctx = orchestrator._get_dependency_context(main)
        assert ctx == ""


# ---------------------------------------------------------------------------
# 11. WorkflowOrchestrator.run()
# ---------------------------------------------------------------------------

class TestRun:
    @pytest.mark.asyncio
    async def test_run_with_template(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        result = await orch.run("test", "general_qa", template_name="investigate")
        assert result is not None
        assert result.tasks_completed == 3

    @pytest.mark.asyncio
    async def test_run_auto_detect(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        result = await orch.run("investigate the data loss", "general_qa")
        assert result is not None

    @pytest.mark.asyncio
    async def test_run_returns_none_no_workflow(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        result = await orch.run("hello", "general_qa")
        assert result is None

    @pytest.mark.asyncio
    async def test_run_returns_workflow_result_type(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        result = await orch.run("security audit my configs", "general_qa")
        assert isinstance(result, WorkflowResult)


# ---------------------------------------------------------------------------
# 12. WorkflowOrchestrator.get_summary()
# ---------------------------------------------------------------------------

class TestGetSummary:
    def test_summary_initial(self, orchestrator):
        summary = orchestrator.get_summary()
        assert summary["active_workflows"] == 0
        assert summary["completed_workflows"] == 0
        assert summary["success_rate"] == 0.0
        assert "templates_available" in summary

    def test_summary_templates_list(self, orchestrator):
        summary = orchestrator.get_summary()
        templates = summary["templates_available"]
        assert "analyze_and_optimize" in templates
        assert "troubleshoot" in templates
        assert len(templates) == 5

    @pytest.mark.asyncio
    async def test_summary_after_workflow(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        await orch.run("investigate the issue", "general_qa")
        summary = orch.get_summary()
        assert summary["completed_workflows"] == 1
        assert summary["success_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_summary_success_rate_partial(self):
        dispatcher = _make_dispatcher_mock()
        orch = WorkflowOrchestrator(dispatcher=dispatcher)
        # Successful workflow
        await orch.run("investigate the issue", "general_qa")

        # Failed workflow
        fail_dispatcher = _make_dispatcher_mock(
            results=[
                _make_dispatch_result(success=False, error="fail"),
                _make_dispatch_result(success=True),
                _make_dispatch_result(success=True),
            ]
        )
        orch._dispatcher = fail_dispatcher
        await orch.run("security audit check", "general_qa")

        summary = orch.get_summary()
        assert summary["completed_workflows"] == 2
        assert summary["success_rate"] == 0.5

    def test_get_active_workflows_empty(self, orchestrator):
        active = orchestrator.get_active_workflows()
        assert active == []

    def test_get_completed_workflows_empty(self, orchestrator):
        completed = orchestrator.get_completed_workflows()
        assert completed == []

    @pytest.mark.asyncio
    async def test_get_completed_workflows_limit(self, mock_dispatcher):
        orch = WorkflowOrchestrator(dispatcher=mock_dispatcher)
        for _ in range(5):
            await orch.run("investigate something", "general_qa")
        completed = orch.get_completed_workflows(limit=3)
        assert len(completed) == 3


# ---------------------------------------------------------------------------
# 13. Singleton get_workflow_orchestrator()
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_returns_same_instance(self):
        import chat_app.workflow_orchestrator as mod
        mod._orchestrator = None
        inst1 = get_workflow_orchestrator()
        inst2 = get_workflow_orchestrator()
        assert inst1 is inst2
        # Cleanup
        mod._orchestrator = None

    def test_creates_instance_when_none(self):
        import chat_app.workflow_orchestrator as mod
        mod._orchestrator = None
        inst = get_workflow_orchestrator()
        assert isinstance(inst, WorkflowOrchestrator)
        # Cleanup
        mod._orchestrator = None

    def test_reset_singleton(self):
        import chat_app.workflow_orchestrator as mod
        mod._orchestrator = None
        inst1 = get_workflow_orchestrator()
        mod._orchestrator = None
        inst2 = get_workflow_orchestrator()
        assert inst1 is not inst2
        # Cleanup
        mod._orchestrator = None


# ---------------------------------------------------------------------------
# Pydantic plan validation models
# ---------------------------------------------------------------------------


class TestValidatedWorkflowStep:
    """Tests for the ValidatedWorkflowStep Pydantic model."""

    def test_valid_step(self):
        step = ValidatedWorkflowStep(
            description="Generate a search",
            intent="spl_generation",
        )
        assert step.intent == "spl_generation"
        assert step.depends_on == []
        assert step.estimated_duration_seconds == 30
        assert step.requires_approval is False

    def test_invalid_intent_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="Invalid intent"):
            ValidatedWorkflowStep(
                description="Bad step",
                intent="nonexistent_intent",
            )

    def test_negative_dependency_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ValidatedWorkflowStep(
                description="Bad deps",
                intent="general_qa",
                depends_on=[-1],
            )

    def test_zero_duration_gets_default(self):
        step = ValidatedWorkflowStep(
            description="Quick step",
            intent="general_qa",
            estimated_duration_seconds=0,
        )
        assert step.estimated_duration_seconds == 30

    def test_all_fields_populated(self):
        step = ValidatedWorkflowStep(
            description="Full step",
            intent="troubleshooting",
            agent_name="troubleshooter",
            preferred_department="support",
            requires_approval=True,
            depends_on=[0, 1],
            estimated_duration_seconds=60,
        )
        assert step.agent_name == "troubleshooter"
        assert step.preferred_department == "support"
        assert step.requires_approval is True
        assert step.depends_on == [0, 1]
        assert step.estimated_duration_seconds == 60


class TestValidatedWorkflowPlan:
    """Tests for the ValidatedWorkflowPlan Pydantic model."""

    def test_valid_plan(self):
        plan = ValidatedWorkflowPlan(
            goal="Test goal",
            steps=[
                ValidatedWorkflowStep(description="Step 1", intent="general_qa"),
            ],
        )
        assert plan.goal == "Test goal"
        assert len(plan.steps) == 1

    def test_empty_steps_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="at least one step"):
            ValidatedWorkflowPlan(goal="Empty", steps=[])

    def test_too_many_steps_rejected(self):
        from pydantic import ValidationError
        steps = [
            ValidatedWorkflowStep(description=f"Step {i}", intent="general_qa")
            for i in range(11)
        ]
        with pytest.raises(ValidationError, match="maximum is 10"):
            ValidatedWorkflowPlan(goal="Huge", steps=steps)

    def test_max_duration_default(self):
        plan = ValidatedWorkflowPlan(
            goal="Test",
            steps=[ValidatedWorkflowStep(description="S", intent="general_qa")],
        )
        assert plan.max_duration_seconds == 300


class TestValidatePlanCapabilities:
    """Tests for validate_plan_capabilities()."""

    def test_valid_plan_passes(self):
        plan = ValidatedWorkflowPlan(
            goal="Simple plan",
            steps=[
                ValidatedWorkflowStep(description="Q&A", intent="general_qa"),
            ],
        )
        valid, errors = validate_plan_capabilities(plan)
        assert valid is True
        assert errors == []

    def test_unhandleable_intent_fails(self):
        """A plan with an intent no agent handles should fail.

        We patch the catalog to return empty for 'general_qa'.
        """
        plan = ValidatedWorkflowPlan(
            goal="Bad plan",
            steps=[
                ValidatedWorkflowStep(description="Q&A", intent="general_qa"),
            ],
        )
        with patch("chat_app.workflow_orchestrator.get_agent_catalog") as mock_cat:
            catalog = MagicMock()
            catalog.get_for_intent.return_value = []
            catalog.get.return_value = None
            mock_cat.return_value = catalog
            valid, errors = validate_plan_capabilities(plan)
        assert valid is False
        assert any("No agent available" in e for e in errors)

    def test_nonexistent_agent_fails(self):
        plan = ValidatedWorkflowPlan(
            goal="Named agent plan",
            steps=[
                ValidatedWorkflowStep(
                    description="Step",
                    intent="general_qa",
                    agent_name="totally_fake_agent_xyz",
                ),
            ],
        )
        with patch("chat_app.workflow_orchestrator.get_agent_catalog") as mock_cat:
            catalog = MagicMock()
            catalog.get_for_intent.return_value = [MagicMock()]
            catalog.get.return_value = None  # agent not found
            mock_cat.return_value = catalog
            valid, errors = validate_plan_capabilities(plan)
        assert valid is False
        assert any("not found in catalog" in e for e in errors)

    def test_cycle_detection(self):
        """Steps that depend on later steps (forward refs) are flagged."""
        plan = ValidatedWorkflowPlan(
            goal="Cyclic plan",
            steps=[
                ValidatedWorkflowStep(description="A", intent="general_qa", depends_on=[1]),
                ValidatedWorkflowStep(description="B", intent="general_qa", depends_on=[0]),
            ],
        )
        valid, errors = validate_plan_capabilities(plan)
        assert valid is False
        assert any("cycle" in e.lower() or "not a preceding step" in e.lower() for e in errors)

    def test_out_of_range_dependency(self):
        plan = ValidatedWorkflowPlan(
            goal="OOB dep",
            steps=[
                ValidatedWorkflowStep(description="A", intent="general_qa", depends_on=[5]),
            ],
        )
        valid, errors = validate_plan_capabilities(plan)
        assert valid is False
        assert any("out of range" in e for e in errors)

    def test_duration_budget_exceeded(self):
        plan = ValidatedWorkflowPlan(
            goal="Slow plan",
            max_duration_seconds=50,
            steps=[
                ValidatedWorkflowStep(description="A", intent="general_qa", estimated_duration_seconds=30),
                ValidatedWorkflowStep(description="B", intent="general_qa", estimated_duration_seconds=30),
            ],
        )
        valid, errors = validate_plan_capabilities(plan)
        assert valid is False
        assert any("exceeds budget" in e for e in errors)

    def test_approval_intents_flagged(self):
        plan = ValidatedWorkflowPlan(
            goal="Dangerous plan",
            steps=[
                ValidatedWorkflowStep(description="Run", intent="run_search"),
                ValidatedWorkflowStep(description="QA", intent="general_qa"),
            ],
        )
        validate_plan_capabilities(plan)
        assert plan.steps[0].requires_approval is True
        assert plan.steps[1].requires_approval is False


class TestParseLlmPlanResponse:
    """Tests for _parse_llm_plan_response()."""

    def test_json_block(self):
        text = 'Here is the plan:\n{"description": "Test", "tasks": [{"description": "Step 1", "intent": "general_qa", "department": "knowledge", "depends_on": []}]}'
        result = _parse_llm_plan_response(text)
        assert result is not None
        assert result["description"] == "Test"
        assert len(result["tasks"]) == 1

    def test_dash_fallback(self):
        text = "Steps:\n- Analyze the data\n- Generate report"
        result = _parse_llm_plan_response(text)
        assert result is not None
        assert len(result["tasks"]) == 2
        assert result["tasks"][0]["intent"] == "general_qa"

    def test_no_parseable_content(self):
        result = _parse_llm_plan_response("I cannot create a plan for this.")
        assert result is None

    def test_malformed_json_falls_back(self):
        text = '{"description": "broken", tasks: [oops]}'
        # Invalid JSON, but has dashes? No. Should return None.
        result = _parse_llm_plan_response(text)
        assert result is None


class TestBuildValidatedPlan:
    """Tests for _build_validated_plan()."""

    def test_valid_plan_data(self):
        plan_data = {
            "description": "Test plan",
            "tasks": [
                {"description": "Step 1", "intent": "general_qa", "department": "knowledge", "depends_on": []},
                {"description": "Step 2", "intent": "troubleshooting", "department": "support", "depends_on": [0]},
            ],
        }
        plan = _build_validated_plan(plan_data, "test input")
        assert plan is not None
        assert len(plan.tasks) == 2
        assert plan.tasks[0].intent == "general_qa"
        assert plan.tasks[1].depends_on == [0]

    def test_invalid_intent_step_skipped(self):
        plan_data = {
            "description": "Mixed plan",
            "tasks": [
                {"description": "Good", "intent": "general_qa", "depends_on": []},
                {"description": "Bad", "intent": "invalid_fake_intent", "depends_on": []},
            ],
        }
        plan = _build_validated_plan(plan_data, "test")
        # The bad step is skipped; only the good one remains
        assert plan is not None
        assert len(plan.tasks) == 1

    def test_all_invalid_returns_none(self):
        plan_data = {
            "description": "All bad",
            "tasks": [
                {"description": "Bad", "intent": "totally_bogus"},
            ],
        }
        plan = _build_validated_plan(plan_data, "test")
        assert plan is None

    def test_empty_tasks_returns_none(self):
        plan_data = {"description": "Empty", "tasks": []}
        assert _build_validated_plan(plan_data, "test") is None

    def test_approval_flag_propagated(self):
        plan_data = {
            "description": "Dangerous",
            "tasks": [
                {"description": "Run", "intent": "run_search", "depends_on": []},
            ],
        }
        with patch("chat_app.workflow_orchestrator.get_agent_catalog") as mock_cat:
            catalog = MagicMock()
            catalog.get_for_intent.return_value = [MagicMock()]
            catalog.get.return_value = None
            mock_cat.return_value = catalog
            plan = _build_validated_plan(plan_data, "test")
        assert plan is not None
        assert plan.requires_approval is True

    def test_accepts_steps_key_alias(self):
        """Plan data with 'steps' key instead of 'tasks'."""
        plan_data = {
            "description": "Aliased",
            "steps": [
                {"description": "S1", "intent": "general_qa", "depends_on": []},
            ],
        }
        plan = _build_validated_plan(plan_data, "test")
        assert plan is not None
        assert len(plan.tasks) == 1


class TestApprovalGateInExecuteWorkflow:
    """Tests that execute_workflow blocks plans requiring approval."""

    @pytest.mark.asyncio
    async def test_approval_required_blocks_execution(self):
        dispatcher = _make_dispatcher_mock()
        orch = WorkflowOrchestrator(dispatcher=dispatcher)
        plan = WorkflowPlan(
            description="Dangerous plan",
            tasks=[
                WorkflowTask(id=0, description="Run search", intent="run_search",
                             params={"user_input": "test"}),
            ],
            requires_approval=True,
        )

        with patch.object(orch, "_save_state", new_callable=AsyncMock):
            result = await orch.execute_workflow(plan, "test", user_approved=False)

        assert result.success is False
        assert "approval" in result.combined_output.lower()
        # Dispatcher should NOT have been called
        dispatcher.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_approval_granted_allows_execution(self):
        dispatcher = _make_dispatcher_mock()
        orch = WorkflowOrchestrator(dispatcher=dispatcher)
        plan = WorkflowPlan(
            description="Approved plan",
            tasks=[
                WorkflowTask(id=0, description="Run search", intent="run_search",
                             params={"user_input": "test"}),
            ],
            requires_approval=True,
        )

        with patch.object(orch, "_save_state", new_callable=AsyncMock):
            result = await orch.execute_workflow(plan, "test", user_approved=True)

        assert result.success is True
        dispatcher.dispatch.assert_called_once()


class TestCreatePlanApprovalFlag:
    """Tests that create_plan flags approval-required intents."""

    def test_template_with_safe_intents(self):
        orch = WorkflowOrchestrator(dispatcher=MagicMock())
        plan = orch.create_plan("investigate the issue thoroughly", "troubleshooting")
        # troubleshoot template uses troubleshooting + general_qa — none in APPROVAL set
        assert plan is not None
        assert plan.requires_approval is False

    def test_custom_plan_with_dangerous_intent(self):
        """Manually constructed plan with run_search gets flagged."""
        orch = WorkflowOrchestrator(dispatcher=MagicMock())
        plan = WorkflowPlan(
            description="Manual",
            tasks=[WorkflowTask(id=0, description="X", intent="run_search")],
        )
        flagged = orch._flag_approval_on_plan(plan)
        assert flagged.requires_approval is True
