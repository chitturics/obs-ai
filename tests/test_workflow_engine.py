"""Tests for the workflow engine — definitions, runs, simulation."""

import pytest


@pytest.fixture
def engine():
    from chat_app.workflow_engine import WorkflowEngine
    return WorkflowEngine()


class TestWorkflowDefinitions:

    def test_builtin_definitions_exist(self, engine):
        defs = engine.get_all_definitions()
        assert len(defs) >= 10
        names = [d.name for d in defs]
        assert "splunk_search" in names
        assert "general_qa" in names
        assert "cmd_doc" in names
        assert "cmd_health" in names
        assert "agent_dispatch" in names
        assert "mcp_tool_call" in names
        assert "config_change" in names

    def test_definition_has_steps(self, engine):
        defn = engine.get_definition("splunk_search")
        assert defn is not None
        assert len(defn.steps) >= 5
        step_names = [s.name for s in defn.steps]
        assert "classify" in step_names
        assert "retrieve" in step_names
        assert "respond" in step_names

    def test_definition_to_dict(self, engine):
        defn = engine.get_definition("splunk_search")
        d = defn.to_dict()
        assert d["name"] == "splunk_search"
        assert d["step_count"] >= 5
        assert d["total_estimated_ms"] > 0
        assert all("name" in s and "type" in s for s in d["steps"])

    def test_every_step_has_handler(self, engine):
        for defn in engine.get_all_definitions():
            for step in defn.steps:
                assert step.handler, f"Step '{step.name}' in workflow '{defn.name}' has no handler"

    def test_every_definition_has_trigger(self, engine):
        for defn in engine.get_all_definitions():
            assert defn.trigger, f"Workflow '{defn.name}' has no trigger"


class TestWorkflowRuns:

    def test_start_and_finish_run(self, engine):
        run = engine.start_run("splunk_search", actor="admin", input_preview="index=main errors")
        assert run.run_id
        assert run.started_at

        step1 = run.add_step("classify", "classify")
        step1.start()
        step1.complete(output="intent=splunk_search", confidence=0.95)

        step2 = run.add_step("retrieve", "retrieve")
        step2.start()
        step2.complete(output="15 chunks", collections=3)

        engine.finish_run(run, success=True)
        assert run.success
        assert run.total_latency_ms >= 0
        assert len(run.steps) == 2

    def test_run_to_dict(self, engine):
        run = engine.start_run("general_qa", actor="user1")
        step = run.add_step("classify", "classify")
        step.start()
        step.complete(output="intent=general_qa")
        engine.finish_run(run)

        d = run.to_dict()
        assert d["workflow"] == "general_qa"
        assert d["success"] is True
        assert len(d["steps"]) == 1

    def test_get_recent_runs(self, engine):
        for i in range(5):
            run = engine.start_run("splunk_search", input_preview=f"query {i}")
            engine.finish_run(run)

        runs = engine.get_recent_runs()
        assert len(runs) == 5

    def test_filter_runs_by_workflow(self, engine):
        engine.finish_run(engine.start_run("splunk_search"))
        engine.finish_run(engine.start_run("general_qa"))
        engine.finish_run(engine.start_run("splunk_search"))

        runs = engine.get_recent_runs(workflow_name="splunk_search")
        assert len(runs) == 2

    def test_get_run_by_id(self, engine):
        run = engine.start_run("cmd_health")
        engine.finish_run(run)

        found = engine.get_run(run.run_id)
        assert found is not None
        assert found["run_id"] == run.run_id

    def test_failed_step(self, engine):
        run = engine.start_run("splunk_search")
        step = run.add_step("execute_search", "skill_execute")
        step.start()
        step.fail("Splunk connection timeout")
        engine.finish_run(run, success=False)

        d = run.to_dict()
        assert d["success"] is False
        assert d["steps"][0]["status"] == "failed"
        assert "timeout" in d["steps"][0]["error"]


class TestSimulation:

    def test_simulate_splunk_search(self, engine):
        sim = engine.simulate("splunk_search")
        assert sim.workflow_name == "splunk_search"
        assert sim.total_estimated_ms > 0
        assert len(sim.steps) >= 5

        # Steps should have cumulative timing
        for i, step in enumerate(sim.steps):
            assert "estimated_ms" in step
            assert "cumulative_ms" in step
            if i > 0:
                assert step["cumulative_ms"] > sim.steps[i-1]["cumulative_ms"]

    def test_simulate_identifies_bottleneck(self, engine):
        sim = engine.simulate("splunk_search")
        # execute_search at 3000ms should be flagged
        assert any("bottleneck" in n for n in sim.notes)

    def test_simulate_identifies_optional_steps(self, engine):
        sim = engine.simulate("splunk_search")
        assert any("optional" in n for n in sim.notes)

    def test_simulate_unknown_workflow(self, engine):
        sim = engine.simulate("nonexistent")
        assert "Unknown" in sim.notes[0]

    def test_simulate_all_workflows(self, engine):
        """Every defined workflow should be simulatable."""
        for defn in engine.get_all_definitions():
            sim = engine.simulate(defn.name)
            assert sim.total_estimated_ms > 0, f"Workflow '{defn.name}' has zero estimated time"
            assert len(sim.steps) > 0, f"Workflow '{defn.name}' has no steps"


class TestStats:

    def test_stats_structure(self, engine):
        engine.finish_run(engine.start_run("splunk_search"))
        engine.finish_run(engine.start_run("general_qa"))
        stats = engine.get_stats()
        assert stats["definitions"] >= 10
        assert stats["total_runs"] == 2
        assert "splunk_search" in stats["by_workflow"]


class TestStepResult:

    def test_step_lifecycle(self):
        from chat_app.workflow_engine import StepResult
        step = StepResult(name="test", step_type="classify")
        assert step.status.value == "pending"

        step.start()
        assert step.status.value == "running"

        step.complete(output="done", confidence=0.9)
        assert step.status.value == "completed"
        assert step.latency_ms >= 0
        assert step.metadata["confidence"] == 0.9

    def test_step_failure(self):
        from chat_app.workflow_engine import StepResult
        step = StepResult(name="test", step_type="skill_execute")
        step.start()
        step.fail("Connection refused")
        assert step.status.value == "failed"
        assert "refused" in step.error

    def test_step_skip(self):
        from chat_app.workflow_engine import StepResult
        step = StepResult(name="optional", step_type="evaluate")
        step.skip("Not needed for this query")
        assert step.status.value == "skipped"
