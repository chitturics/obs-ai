"""
Action Engine — Typed action execution with state machine tracking.

Adapted from OpenMAIC's Action Engine pattern. Provides:
- 12 typed actions (retrieve, generate_spl, analyze, validate, etc.)
- State machine per action (pending → running → completed/failed/cancelled)
- ActionPlan: ordered list of actions with sequential execution
- ActionEngine: executes plans by mapping action types to skill execution

Used by ActionEngineStrategy in orchestration_strategies.py.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action types — the 12 typed actions the system can perform
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    """Typed actions the system can perform."""
    RETRIEVE = "retrieve"
    GENERATE_SPL = "generate_spl"
    ANALYZE = "analyze"
    VALIDATE = "validate"
    TRANSFORM = "transform"
    EXPLAIN = "explain"
    OPTIMIZE = "optimize"
    EXECUTE_SEARCH = "execute_search"
    COMPARE = "compare"
    SUMMARIZE = "summarize"
    DELEGATE = "delegate"
    ESCALATE = "escalate"


# Mapping from ActionType → skill name in skill_catalog.py
ACTION_SKILL_MAP: Dict[ActionType, str] = {
    ActionType.RETRIEVE: "retrieve_chunks",
    ActionType.GENERATE_SPL: "generate_spl",
    ActionType.ANALYZE: "analyze_spl",
    ActionType.VALIDATE: "validate_spl",
    ActionType.TRANSFORM: "translate_query",
    ActionType.EXPLAIN: "explain_spl",
    ActionType.OPTIMIZE: "optimize_spl",
    ActionType.EXECUTE_SEARCH: "execute_search",
    ActionType.COMPARE: "compare_configs",
    ActionType.SUMMARIZE: "summarize_results",
    ActionType.DELEGATE: "assign_to_agent",
    ActionType.ESCALATE: "escalate_issue",
}


# ---------------------------------------------------------------------------
# Action state machine
# ---------------------------------------------------------------------------

class ActionState(str, Enum):
    """State of an individual action."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid state transitions
_VALID_TRANSITIONS: Dict[ActionState, List[ActionState]] = {
    ActionState.PENDING: [ActionState.RUNNING, ActionState.CANCELLED],
    ActionState.RUNNING: [ActionState.COMPLETED, ActionState.FAILED, ActionState.PAUSED],
    ActionState.PAUSED: [ActionState.RUNNING, ActionState.CANCELLED],
    ActionState.COMPLETED: [],
    ActionState.FAILED: [],
    ActionState.CANCELLED: [],
}


def can_transition(from_state: ActionState, to_state: ActionState) -> bool:
    """Check if a state transition is valid."""
    return to_state in _VALID_TRANSITIONS.get(from_state, [])


# ---------------------------------------------------------------------------
# Action and ActionPlan dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Action:
    """A single typed action with state tracking."""
    id: str
    action_type: ActionType
    description: str
    state: ActionState = ActionState.PENDING
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    agent_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type.value,
            "description": self.description,
            "state": self.state.value,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 1),
            "agent_name": self.agent_name,
        }


@dataclass
class ActionPlan:
    """Ordered list of actions with state tracking."""
    actions: List[Action] = field(default_factory=list)
    state: str = "pending"  # pending, running, completed, failed
    created_at: float = field(default_factory=time.time)

    def next_runnable(self) -> Optional[Action]:
        """Get next action in PENDING state."""
        for a in self.actions:
            if a.state == ActionState.PENDING:
                return a
        return None

    def is_complete(self) -> bool:
        """True if all actions are in terminal states."""
        terminal = {ActionState.COMPLETED, ActionState.FAILED, ActionState.CANCELLED}
        return all(a.state in terminal for a in self.actions)

    def success_count(self) -> int:
        return sum(1 for a in self.actions if a.state == ActionState.COMPLETED)

    def failure_count(self) -> int:
        return sum(1 for a in self.actions if a.state == ActionState.FAILED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "total_actions": len(self.actions),
            "completed": self.success_count(),
            "failed": self.failure_count(),
            "actions": [a.to_dict() for a in self.actions],
        }


def make_action(action_type: ActionType, description: str, **kwargs) -> Action:
    """Factory for creating actions with auto-generated IDs."""
    return Action(
        id=f"act_{uuid.uuid4().hex[:8]}",
        action_type=action_type,
        description=description,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Action Engine
# ---------------------------------------------------------------------------

class ActionEngine:
    """Executes action plans by mapping action types to skill execution."""

    def __init__(self, max_actions: int = 15, timeout_per_action: float = 10.0):
        self.max_actions = max_actions
        self.timeout_per_action = timeout_per_action

    async def execute_plan(self, plan: ActionPlan, context: Any = None) -> ActionPlan:
        """Execute all actions in sequence, tracking state transitions."""
        if len(plan.actions) > self.max_actions:
            logger.warning("[ACTION_ENGINE] Plan has %d actions, capping at %d",
                           len(plan.actions), self.max_actions)
            for a in plan.actions[self.max_actions:]:
                a.state = ActionState.CANCELLED
                a.error = "Exceeded max actions limit"

        plan.state = "running"
        accumulated_context = ""

        while not plan.is_complete():
            action = plan.next_runnable()
            if action is None:
                break

            action.state = ActionState.RUNNING
            start = time.monotonic()

            try:
                import asyncio
                result = await asyncio.wait_for(
                    self._execute_action(action, context, accumulated_context),
                    timeout=self.timeout_per_action,
                )
                action.output_data = result
                action.state = ActionState.COMPLETED
                action.duration_ms = (time.monotonic() - start) * 1000

                # Accumulate context from successful actions
                if result:
                    accumulated_context += f"\n[{action.action_type.value}] {result}"

                logger.info("[ACTION_ENGINE] Action %s (%s) completed in %.0fms",
                            action.id, action.action_type.value, action.duration_ms)

            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                action.error = str(exc)
                action.state = ActionState.FAILED
                action.duration_ms = (time.monotonic() - start) * 1000
                logger.warning("[ACTION_ENGINE] Action %s (%s) failed: %s",
                               action.id, action.action_type.value, exc)
                # Continue with remaining actions (don't break on failure)

        plan.state = "completed" if plan.is_complete() else "failed"
        return plan

    async def _execute_action(
        self, action: Action, context: Any, accumulated: str
    ) -> Optional[str]:
        """Map action type to skill execution via SkillExecutor."""
        skill_name = ACTION_SKILL_MAP.get(action.action_type)
        if not skill_name:
            logger.debug("[ACTION_ENGINE] No skill mapping for %s", action.action_type)
            return None

        try:
            from chat_app.skill_executor import get_skill_executor
            executor = get_skill_executor()
            params = {
                **(action.input_data or {}),
                "user_input": action.description,
                "accumulated_context": accumulated,
            }
            result = await executor.execute(skill_name=skill_name, params=params)
            action.agent_name = result.source
            if result.success:
                return result.output
            else:
                action.error = result.error
                return None
        except ImportError:
            logger.debug("[ACTION_ENGINE] SkillExecutor not available")
            return f"[{action.action_type.value}] {action.description}"
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            raise exc

    def get_accumulated_output(self, plan: ActionPlan) -> str:
        """Combine all successful action outputs into a context string."""
        parts = []
        for action in plan.actions:
            if action.state == ActionState.COMPLETED and action.output_data:
                parts.append(f"**{action.action_type.value}**: {action.output_data}")
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Plan builder helpers
# ---------------------------------------------------------------------------

def build_plan_from_steps(steps: List[Dict[str, Any]]) -> ActionPlan:
    """Build an ActionPlan from a list of step dicts.

    Each step dict should have:
        - action_type: str (ActionType value)
        - description: str
        - input_data: dict (optional)
    """
    actions = []
    for step in steps:
        try:
            atype = ActionType(step.get("action_type", "analyze"))
        except ValueError:
            atype = ActionType.ANALYZE
        actions.append(make_action(
            action_type=atype,
            description=step.get("description", ""),
            input_data=step.get("input_data", {}),
        ))
    return ActionPlan(actions=actions)


# ---------------------------------------------------------------------------
# Singleton engine with execution stats
# ---------------------------------------------------------------------------

_engine: Optional[ActionEngine] = None
_execution_stats: Dict[str, Any] = {
    "plans_executed": 0,
    "actions_executed": 0,
    "actions_succeeded": 0,
    "actions_failed": 0,
    "last_plan_time": None,
    "recent_plans": [],  # last 20 plan summaries
}


def get_action_engine(
    max_actions: int = 15, timeout_per_action: float = 10.0
) -> ActionEngine:
    """Get or create the singleton ActionEngine."""
    global _engine
    if _engine is None:
        _engine = ActionEngine(max_actions=max_actions, timeout_per_action=timeout_per_action)
    return _engine


def record_plan_execution(plan: ActionPlan) -> None:
    """Record stats from a completed plan execution."""
    _execution_stats["plans_executed"] += 1
    _execution_stats["actions_executed"] += len(plan.actions)
    _execution_stats["actions_succeeded"] += plan.success_count()
    _execution_stats["actions_failed"] += plan.failure_count()
    _execution_stats["last_plan_time"] = time.time()
    summary = plan.to_dict()
    summary["executed_at"] = time.time()
    _execution_stats["recent_plans"] = (_execution_stats["recent_plans"] + [summary])[-20:]


def get_engine_status() -> Dict[str, Any]:
    """Return full engine status including stats and configuration."""
    engine = get_action_engine()
    return {
        "initialized": True,
        "max_actions": engine.max_actions,
        "timeout_per_action_sec": engine.timeout_per_action,
        "stats": {
            "plans_executed": _execution_stats["plans_executed"],
            "actions_executed": _execution_stats["actions_executed"],
            "actions_succeeded": _execution_stats["actions_succeeded"],
            "actions_failed": _execution_stats["actions_failed"],
            "success_rate": (
                round(_execution_stats["actions_succeeded"] / _execution_stats["actions_executed"], 3)
                if _execution_stats["actions_executed"] > 0 else None
            ),
            "last_plan_time": _execution_stats["last_plan_time"],
        },
        "recent_plans": _execution_stats["recent_plans"][-5:],
    }
