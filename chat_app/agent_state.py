"""
Multi-Turn Agent State — Persistent goal tracking across conversation turns.

Enables the agent to:
- Set goals and sub-goals from user requests
- Track completion across multiple turns
- Resume interrupted plans
- Chain actions toward a goal
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import chainlit as cl

logger = logging.getLogger(__name__)


class GoalStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SubGoal:
    """A single sub-goal within a larger plan."""
    description: str
    status: GoalStatus = GoalStatus.PENDING
    result: Optional[str] = None
    depends_on: Optional[int] = None  # Index of prerequisite sub-goal
    attempts: int = 0
    max_attempts: int = 3


@dataclass
class AgentGoal:
    """A top-level goal with sub-goals."""
    description: str
    sub_goals: List[SubGoal] = field(default_factory=list)
    status: GoalStatus = GoalStatus.PENDING
    created_at: float = field(default_factory=time.time)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    """
    Persistent agent state for multi-turn planning.

    Stored in cl.user_session for persistence across turns.
    """
    current_goal: Optional[AgentGoal] = None
    completed_goals: List[str] = field(default_factory=list)
    turn_count: int = 0
    last_action: str = ""
    last_confidence: float = 0.0
    accumulated_context: List[str] = field(default_factory=list)
    tool_trace: List[Dict[str, Any]] = field(default_factory=list)

    def has_active_goal(self) -> bool:
        """Check if there's an active goal in progress."""
        return (
            self.current_goal is not None
            and self.current_goal.status in (GoalStatus.PENDING, GoalStatus.IN_PROGRESS)
        )

    def get_next_subgoal(self) -> Optional[SubGoal]:
        """Get the next actionable sub-goal."""
        if not self.current_goal:
            return None

        for i, sg in enumerate(self.current_goal.sub_goals):
            if sg.status != GoalStatus.PENDING:
                continue
            # Check dependencies
            if sg.depends_on is not None:
                dep = self.current_goal.sub_goals[sg.depends_on]
                if dep.status != GoalStatus.COMPLETED:
                    continue
            return sg
        return None

    def mark_subgoal_complete(self, index: int, result: str = ""):
        """Mark a sub-goal as completed."""
        if self.current_goal and index < len(self.current_goal.sub_goals):
            sg = self.current_goal.sub_goals[index]
            sg.status = GoalStatus.COMPLETED
            sg.result = result

            # Check if all sub-goals are done
            if all(s.status == GoalStatus.COMPLETED for s in self.current_goal.sub_goals):
                self.current_goal.status = GoalStatus.COMPLETED
                self.completed_goals.append(self.current_goal.description)
                logger.info(f"[AGENT] Goal completed: {self.current_goal.description}")

    def mark_subgoal_failed(self, index: int, reason: str = ""):
        """Mark a sub-goal as failed."""
        if self.current_goal and index < len(self.current_goal.sub_goals):
            sg = self.current_goal.sub_goals[index]
            sg.attempts += 1
            if sg.attempts >= sg.max_attempts:
                sg.status = GoalStatus.FAILED
                logger.warning(f"[AGENT] Sub-goal failed after {sg.attempts} attempts: {sg.description}")
            else:
                sg.status = GoalStatus.PENDING  # Allow retry

    def set_goal(self, description: str, sub_goals: List[str] = None):
        """Set a new goal with optional sub-goals."""
        self.current_goal = AgentGoal(
            description=description,
            status=GoalStatus.IN_PROGRESS,
            sub_goals=[
                SubGoal(description=sg, depends_on=i - 1 if i > 0 else None)
                for i, sg in enumerate(sub_goals or [])
            ],
        )
        logger.info(f"[AGENT] New goal: {description} ({len(self.current_goal.sub_goals)} steps)")

    def get_progress_summary(self) -> str:
        """Get a human-readable progress summary."""
        if not self.current_goal:
            return "No active goal."

        total = len(self.current_goal.sub_goals)
        completed = sum(1 for s in self.current_goal.sub_goals if s.status == GoalStatus.COMPLETED)
        failed = sum(1 for s in self.current_goal.sub_goals if s.status == GoalStatus.FAILED)

        parts = [f"Goal: {self.current_goal.description}"]
        if total > 0:
            parts.append(f"Progress: {completed}/{total} steps")
            if failed:
                parts.append(f"({failed} failed)")
        return " | ".join(parts)

    def add_context(self, context: str):
        """Accumulate context across turns (for sequential plans)."""
        self.accumulated_context.append(context)
        # Keep last 5 context entries to avoid bloat
        if len(self.accumulated_context) > 5:
            self.accumulated_context = self.accumulated_context[-5:]

    def record_tool_use(self, tool_name: str, args: Dict, result: str):
        """Record a tool execution for the trace."""
        self.tool_trace.append({
            "tool": tool_name,
            "args": args,
            "result": result[:500],
            "turn": self.turn_count,
        })
        # Keep last 10 tool uses
        if len(self.tool_trace) > 10:
            self.tool_trace = self.tool_trace[-10:]


def get_agent_state() -> AgentState:
    """Get or create the agent state from the session."""
    state = cl.user_session.get("agent_state")
    if state is None:
        state = AgentState()
        cl.user_session.set("agent_state", state)
    return state


def save_agent_state(state: AgentState):
    """Save agent state back to the session."""
    cl.user_session.set("agent_state", state)


def detect_multi_step_goal(user_input: str) -> Optional[List[str]]:
    """
    Detect if the user's request implies a multi-step goal.

    Returns a list of sub-goal descriptions, or None if single-step.
    """
    import re

    lower = user_input.lower()

    # Patterns that suggest multi-step workflows
    multi_step_patterns = [
        (r'analyze.*(?:and|then).*(?:fix|optimize|improve)', [
            "Analyze the current state",
            "Identify issues and improvements",
            "Apply fixes/optimizations",
        ]),
        (r'(?:find|search).*(?:and|then).*(?:explain|show|correlate)', [
            "Search for matching results",
            "Analyze and explain findings",
        ]),
        (r'(?:create|build|set up).*(?:alert|dashboard|report).*(?:for|that)', [
            "Understand the requirements",
            "Generate the configuration",
            "Validate and provide the result",
        ]),
        (r'(?:troubleshoot|debug|diagnose).*(?:why|not working|failing)', [
            "Identify the problem area",
            "Analyze potential causes",
            "Suggest resolution steps",
        ]),
        (r'(?:compare|diff).*(?:with|against|between)', [
            "Retrieve the first item",
            "Retrieve the second item",
            "Compare and highlight differences",
        ]),
    ]

    for pattern, sub_goals in multi_step_patterns:
        if re.search(pattern, lower):
            return sub_goals

    return None
