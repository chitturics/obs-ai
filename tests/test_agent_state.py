"""Tests for chat_app/agent_state.py — multi-turn goal tracking."""
import pytest
from chat_app.agent_state import (
    AgentState,
    AgentGoal,
    SubGoal,
    GoalStatus,
    detect_multi_step_goal,
)


class TestGoalStatusEnum:
    """Test GoalStatus enum values."""

    def test_all_statuses_present(self):
        assert GoalStatus.PENDING == "pending"
        assert GoalStatus.IN_PROGRESS == "in_progress"
        assert GoalStatus.BLOCKED == "blocked"
        assert GoalStatus.COMPLETED == "completed"
        assert GoalStatus.FAILED == "failed"


class TestSubGoalDataclass:
    """Test SubGoal data structure."""

    def test_default_construction(self):
        sg = SubGoal(description="step one")
        assert sg.description == "step one"
        assert sg.status == GoalStatus.PENDING
        assert sg.result is None
        assert sg.depends_on is None
        assert sg.attempts == 0
        assert sg.max_attempts == 3


class TestAgentGoalDataclass:
    """Test AgentGoal data structure."""

    def test_default_construction(self):
        goal = AgentGoal(description="my goal")
        assert goal.description == "my goal"
        assert goal.status == GoalStatus.PENDING
        assert isinstance(goal.sub_goals, list)
        assert isinstance(goal.context, dict)


class TestAgentState:
    """Test AgentState methods (all pure, no cl.user_session needed)."""

    def test_default_construction(self):
        state = AgentState()
        assert state.current_goal is None
        assert state.turn_count == 0
        assert state.last_action == ""

    def test_has_active_goal_false_when_none(self):
        state = AgentState()
        assert state.has_active_goal() is False

    def test_has_active_goal_true_when_in_progress(self):
        state = AgentState()
        state.set_goal("test goal", ["step 1"])
        assert state.has_active_goal() is True

    def test_has_active_goal_false_when_completed(self):
        state = AgentState()
        state.set_goal("test goal", ["step 1"])
        state.mark_subgoal_complete(0, "done")
        assert state.has_active_goal() is False

    def test_set_goal_creates_subgoals(self):
        state = AgentState()
        state.set_goal("big goal", ["step 1", "step 2", "step 3"])
        assert len(state.current_goal.sub_goals) == 3
        assert state.current_goal.status == GoalStatus.IN_PROGRESS

    def test_set_goal_dependencies(self):
        state = AgentState()
        state.set_goal("goal", ["a", "b", "c"])
        # First subgoal has no dependency
        assert state.current_goal.sub_goals[0].depends_on is None
        # Second depends on first
        assert state.current_goal.sub_goals[1].depends_on == 0
        # Third depends on second
        assert state.current_goal.sub_goals[2].depends_on == 1

    def test_get_next_subgoal_returns_first_pending(self):
        state = AgentState()
        state.set_goal("goal", ["a", "b"])
        sg = state.get_next_subgoal()
        assert sg is not None
        assert sg.description == "a"

    def test_get_next_subgoal_respects_dependencies(self):
        state = AgentState()
        state.set_goal("goal", ["a", "b"])
        # "b" depends on "a", so next should be "a"
        sg = state.get_next_subgoal()
        assert sg.description == "a"

    def test_get_next_subgoal_after_completion(self):
        state = AgentState()
        state.set_goal("goal", ["a", "b"])
        state.mark_subgoal_complete(0, "done")
        sg = state.get_next_subgoal()
        assert sg is not None
        assert sg.description == "b"

    def test_get_next_subgoal_none_when_all_done(self):
        state = AgentState()
        state.set_goal("goal", ["a"])
        state.mark_subgoal_complete(0, "done")
        assert state.get_next_subgoal() is None

    def test_get_next_subgoal_none_when_no_goal(self):
        state = AgentState()
        assert state.get_next_subgoal() is None

    def test_mark_subgoal_complete(self):
        state = AgentState()
        state.set_goal("goal", ["a", "b"])
        state.mark_subgoal_complete(0, "result")
        assert state.current_goal.sub_goals[0].status == GoalStatus.COMPLETED
        assert state.current_goal.sub_goals[0].result == "result"

    def test_all_subgoals_complete_marks_goal_complete(self):
        state = AgentState()
        state.set_goal("goal", ["a"])
        state.mark_subgoal_complete(0, "done")
        assert state.current_goal.status == GoalStatus.COMPLETED
        assert "goal" in state.completed_goals

    def test_mark_subgoal_failed_retries(self):
        state = AgentState()
        state.set_goal("goal", ["a"])
        state.mark_subgoal_failed(0, "error")
        # First failure allows retry (status back to PENDING)
        assert state.current_goal.sub_goals[0].status == GoalStatus.PENDING
        assert state.current_goal.sub_goals[0].attempts == 1

    def test_mark_subgoal_failed_max_attempts(self):
        state = AgentState()
        state.set_goal("goal", ["a"])
        for _ in range(3):
            state.mark_subgoal_failed(0, "error")
        assert state.current_goal.sub_goals[0].status == GoalStatus.FAILED

    def test_get_progress_summary_no_goal(self):
        state = AgentState()
        assert state.get_progress_summary() == "No active goal."

    def test_get_progress_summary_with_goal(self):
        state = AgentState()
        state.set_goal("test goal", ["step 1", "step 2"])
        summary = state.get_progress_summary()
        assert "test goal" in summary
        assert "0/2" in summary

    def test_get_progress_summary_partial(self):
        state = AgentState()
        state.set_goal("test goal", ["step 1", "step 2"])
        state.mark_subgoal_complete(0, "done")
        summary = state.get_progress_summary()
        assert "1/2" in summary

    def test_add_context(self):
        state = AgentState()
        state.add_context("context 1")
        state.add_context("context 2")
        assert len(state.accumulated_context) == 2

    def test_add_context_limits_to_5(self):
        state = AgentState()
        for i in range(10):
            state.add_context(f"context {i}")
        assert len(state.accumulated_context) == 5

    def test_record_tool_use(self):
        state = AgentState()
        state.record_tool_use("search", {"query": "test"}, "results")
        assert len(state.tool_trace) == 1
        assert state.tool_trace[0]["tool"] == "search"

    def test_record_tool_use_limits_to_10(self):
        state = AgentState()
        for i in range(15):
            state.record_tool_use(f"tool_{i}", {}, "result")
        assert len(state.tool_trace) == 10

    def test_record_tool_use_truncates_result(self):
        state = AgentState()
        long_result = "x" * 1000
        state.record_tool_use("tool", {}, long_result)
        assert len(state.tool_trace[0]["result"]) <= 500


class TestDetectMultiStepGoal:
    """Test multi-step goal detection from user input."""

    def test_analyze_and_fix(self):
        goals = detect_multi_step_goal("analyze this search and then fix it")
        assert goals is not None
        assert len(goals) >= 2

    def test_find_and_explain(self):
        goals = detect_multi_step_goal("find failed logins and then explain them")
        assert goals is not None
        assert len(goals) >= 2

    def test_create_alert(self):
        goals = detect_multi_step_goal("create an alert for failed logins that triggers every hour")
        assert goals is not None
        assert len(goals) >= 2

    def test_troubleshoot_not_working(self):
        goals = detect_multi_step_goal("troubleshoot why my search is not working")
        assert goals is not None
        assert len(goals) >= 2

    def test_compare_between(self):
        goals = detect_multi_step_goal("compare props.conf with transforms.conf")
        assert goals is not None
        assert len(goals) >= 2

    def test_simple_query_no_goals(self):
        goals = detect_multi_step_goal("what is the stats command?")
        assert goals is None

    def test_short_query_no_goals(self):
        goals = detect_multi_step_goal("help")
        assert goals is None
