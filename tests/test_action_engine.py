"""Tests for chat_app.action_engine — typed action execution with state machine."""

import asyncio
import pytest

from chat_app.action_engine import (
    ActionType,
    ActionState,
    Action,
    ActionPlan,
    ActionEngine,
    ACTION_SKILL_MAP,
    build_plan_from_steps,
    can_transition,
    make_action,
)


# ---------------------------------------------------------------------------
# ActionType tests
# ---------------------------------------------------------------------------

class TestActionType:
    def test_all_types_have_values(self):
        """Every ActionType member should have a non-empty string value."""
        for t in ActionType:
            assert isinstance(t.value, str)
            assert len(t.value) > 0

    def test_str_comparison(self):
        assert ActionType.RETRIEVE == "retrieve"
        assert ActionType.GENERATE_SPL == "generate_spl"

    def test_total_count(self):
        assert len(ActionType) == 12

    def test_skill_map_covers_all_types(self):
        """Every action type should have a skill mapping."""
        for t in ActionType:
            assert t in ACTION_SKILL_MAP, f"ActionType.{t.name} missing from ACTION_SKILL_MAP"


# ---------------------------------------------------------------------------
# ActionState tests
# ---------------------------------------------------------------------------

class TestActionState:
    def test_all_states(self):
        expected = {"pending", "running", "paused", "completed", "failed", "cancelled"}
        assert {s.value for s in ActionState} == expected

    def test_valid_transitions(self):
        assert can_transition(ActionState.PENDING, ActionState.RUNNING)
        assert can_transition(ActionState.PENDING, ActionState.CANCELLED)
        assert can_transition(ActionState.RUNNING, ActionState.COMPLETED)
        assert can_transition(ActionState.RUNNING, ActionState.FAILED)
        assert can_transition(ActionState.PAUSED, ActionState.RUNNING)

    def test_invalid_transitions(self):
        assert not can_transition(ActionState.COMPLETED, ActionState.RUNNING)
        assert not can_transition(ActionState.FAILED, ActionState.RUNNING)
        assert not can_transition(ActionState.PENDING, ActionState.COMPLETED)


# ---------------------------------------------------------------------------
# Action tests
# ---------------------------------------------------------------------------

class TestAction:
    def test_make_action(self):
        a = make_action(ActionType.ANALYZE, "Test analysis")
        assert a.action_type == ActionType.ANALYZE
        assert a.description == "Test analysis"
        assert a.state == ActionState.PENDING
        assert a.id.startswith("act_")

    def test_to_dict(self):
        a = make_action(ActionType.RETRIEVE, "Search KB")
        d = a.to_dict()
        assert d["action_type"] == "retrieve"
        assert d["state"] == "pending"
        assert d["description"] == "Search KB"


# ---------------------------------------------------------------------------
# ActionPlan tests
# ---------------------------------------------------------------------------

class TestActionPlan:
    def test_next_runnable(self):
        plan = ActionPlan(actions=[
            make_action(ActionType.RETRIEVE, "step 1"),
            make_action(ActionType.ANALYZE, "step 2"),
        ])
        first = plan.next_runnable()
        assert first is not None
        assert first.action_type == ActionType.RETRIEVE

    def test_next_runnable_skips_completed(self):
        a1 = make_action(ActionType.RETRIEVE, "step 1")
        a1.state = ActionState.COMPLETED
        a2 = make_action(ActionType.ANALYZE, "step 2")
        plan = ActionPlan(actions=[a1, a2])
        nxt = plan.next_runnable()
        assert nxt is not None
        assert nxt.action_type == ActionType.ANALYZE

    def test_next_runnable_empty(self):
        a1 = make_action(ActionType.RETRIEVE, "step 1")
        a1.state = ActionState.COMPLETED
        plan = ActionPlan(actions=[a1])
        assert plan.next_runnable() is None

    def test_is_complete(self):
        a1 = make_action(ActionType.RETRIEVE, "step 1")
        a1.state = ActionState.COMPLETED
        a2 = make_action(ActionType.ANALYZE, "step 2")
        a2.state = ActionState.CANCELLED
        plan = ActionPlan(actions=[a1, a2])
        assert plan.is_complete()

    def test_not_complete(self):
        plan = ActionPlan(actions=[make_action(ActionType.RETRIEVE, "step 1")])
        assert not plan.is_complete()

    def test_success_count(self):
        a1 = make_action(ActionType.RETRIEVE, "s1")
        a1.state = ActionState.COMPLETED
        a2 = make_action(ActionType.ANALYZE, "s2")
        a2.state = ActionState.FAILED
        plan = ActionPlan(actions=[a1, a2])
        assert plan.success_count() == 1
        assert plan.failure_count() == 1

    def test_to_dict(self):
        plan = ActionPlan(actions=[make_action(ActionType.RETRIEVE, "s1")])
        d = plan.to_dict()
        assert d["total_actions"] == 1
        assert d["state"] == "pending"


# ---------------------------------------------------------------------------
# build_plan_from_steps
# ---------------------------------------------------------------------------

class TestBuildPlan:
    def test_basic(self):
        steps = [
            {"action_type": "retrieve", "description": "Search"},
            {"action_type": "analyze", "description": "Analyze results"},
        ]
        plan = build_plan_from_steps(steps)
        assert len(plan.actions) == 2
        assert plan.actions[0].action_type == ActionType.RETRIEVE
        assert plan.actions[1].action_type == ActionType.ANALYZE

    def test_unknown_type_defaults_to_analyze(self):
        steps = [{"action_type": "unknown_action", "description": "Test"}]
        plan = build_plan_from_steps(steps)
        assert plan.actions[0].action_type == ActionType.ANALYZE

    def test_empty(self):
        plan = build_plan_from_steps([])
        assert len(plan.actions) == 0


# ---------------------------------------------------------------------------
# ActionEngine tests
# ---------------------------------------------------------------------------

class TestActionEngine:
    def test_execute_empty_plan(self):
        engine = ActionEngine()
        plan = ActionPlan(actions=[])
        result = asyncio.new_event_loop().run_until_complete(engine.execute_plan(plan))
        assert result.state == "completed"

    def test_max_actions_cap(self):
        engine = ActionEngine(max_actions=2)
        actions = [make_action(ActionType.ANALYZE, f"step {i}") for i in range(5)]
        plan = ActionPlan(actions=actions)
        # After execute_plan, actions beyond max_actions should be cancelled
        result = asyncio.new_event_loop().run_until_complete(engine.execute_plan(plan))
        cancelled = [a for a in result.actions if a.state == ActionState.CANCELLED]
        assert len(cancelled) == 3

    def test_get_accumulated_output(self):
        engine = ActionEngine()
        a1 = make_action(ActionType.RETRIEVE, "s1")
        a1.state = ActionState.COMPLETED
        a1.output_data = "Found 5 results"
        a2 = make_action(ActionType.ANALYZE, "s2")
        a2.state = ActionState.FAILED
        plan = ActionPlan(actions=[a1, a2])
        output = engine.get_accumulated_output(plan)
        assert "retrieve" in output
        assert "Found 5 results" in output
