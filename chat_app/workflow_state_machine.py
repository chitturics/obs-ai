"""Workflow State Machine — formal state transitions with validation (ADR-007).

Defines valid workflow states and transitions. Invalid transitions raise errors
instead of silently succeeding. All transitions are logged for debugging.

Usage:
    from chat_app.workflow_state_machine import WorkflowState, StateMachine

    sm = StateMachine()
    sm.transition("wf_123", WorkflowState.CREATED, WorkflowState.RUNNING)
    sm.transition("wf_123", WorkflowState.RUNNING, WorkflowState.WAITING_INPUT)
    sm.transition("wf_123", WorkflowState.WAITING_INPUT, WorkflowState.RUNNING)
    sm.transition("wf_123", WorkflowState.RUNNING, WorkflowState.COMPLETED)
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class WorkflowState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_INPUT = "waiting_input"        # Agent asked user a question
    WAITING_APPROVAL = "waiting_approval"  # Action needs admin approval
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid transitions: from_state → set of allowed to_states
TRANSITIONS: Dict[WorkflowState, Set[WorkflowState]] = {
    WorkflowState.CREATED: {WorkflowState.RUNNING, WorkflowState.CANCELLED},
    WorkflowState.RUNNING: {
        WorkflowState.PAUSED,
        WorkflowState.WAITING_INPUT,
        WorkflowState.WAITING_APPROVAL,
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
    },
    WorkflowState.PAUSED: {WorkflowState.RUNNING, WorkflowState.CANCELLED, WorkflowState.FAILED},
    WorkflowState.WAITING_INPUT: {WorkflowState.RUNNING, WorkflowState.CANCELLED, WorkflowState.FAILED},
    WorkflowState.WAITING_APPROVAL: {WorkflowState.RUNNING, WorkflowState.CANCELLED, WorkflowState.FAILED},
    WorkflowState.COMPLETED: set(),   # Terminal
    WorkflowState.FAILED: set(),      # Terminal
    WorkflowState.CANCELLED: set(),   # Terminal
}


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    def __init__(self, workflow_id: str, from_state: WorkflowState, to_state: WorkflowState):
        self.workflow_id = workflow_id
        self.from_state = from_state
        self.to_state = to_state
        allowed = TRANSITIONS.get(from_state, set())
        super().__init__(
            f"Invalid transition for workflow '{workflow_id}': "
            f"{from_state.value} → {to_state.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )


@dataclass
class TransitionRecord:
    workflow_id: str
    from_state: str
    to_state: str
    timestamp: str = ""
    reason: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class StateMachine:
    """Validates and records workflow state transitions."""

    def __init__(self):
        self._history: deque = deque(maxlen=1000)

    def transition(self, workflow_id: str, from_state: WorkflowState,
                   to_state: WorkflowState, reason: str = "") -> TransitionRecord:
        """Validate and record a state transition.

        Raises InvalidTransitionError if the transition is not allowed.
        """
        allowed = TRANSITIONS.get(from_state, set())
        if to_state not in allowed:
            raise InvalidTransitionError(workflow_id, from_state, to_state)

        record = TransitionRecord(
            workflow_id=workflow_id,
            from_state=from_state.value,
            to_state=to_state.value,
            reason=reason,
        )
        self._history.append(record)
        logger.debug("[STATE] %s: %s → %s (%s)",
                     workflow_id, from_state.value, to_state.value, reason or "no reason")
        return record

    def is_terminal(self, state: WorkflowState) -> bool:
        return len(TRANSITIONS.get(state, set())) == 0

    def get_allowed_transitions(self, state: WorkflowState) -> List[str]:
        return [s.value for s in TRANSITIONS.get(state, set())]

    def get_history(self, workflow_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        records = list(self._history)
        if workflow_id:
            records = [r for r in records if r.workflow_id == workflow_id]
        records.reverse()
        return [
            {"workflow_id": r.workflow_id, "from": r.from_state,
             "to": r.to_state, "timestamp": r.timestamp, "reason": r.reason}
            for r in records[:limit]
        ]
