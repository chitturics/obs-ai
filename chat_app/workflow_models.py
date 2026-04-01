"""
Workflow Models — Data classes, enums, and Pydantic validation for workflow orchestration.

Extracted from workflow_orchestrator.py for size management.
WorkflowOrchestrator imports from this module.

Provides:
- TaskStatus enum
- WorkflowTask, WorkflowPlan, WorkflowResult dataclasses
- ValidatedWorkflowStep, ValidatedWorkflowPlan Pydantic models
- validate_plan_capabilities(), _validated_plan_to_workflow() helpers
- APPROVAL_REQUIRED_INTENTS, TASK_MAX_RETRIES, TASK_RETRY_DELAY_SECONDS, WORKFLOW_TIMEOUT_SECONDS constants
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from chat_app.agent_catalog import Department
from chat_app.registry import Intent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intents that require user approval before execution
# ---------------------------------------------------------------------------

APPROVAL_REQUIRED_INTENTS: set = {
    "run_search",
    "create_alert",
    "ansible",
    "shell_script",
    "python_script",
}


# ---------------------------------------------------------------------------
# Runtime constants
# ---------------------------------------------------------------------------

TASK_MAX_RETRIES = 2
TASK_RETRY_DELAY_SECONDS = 1.0
WORKFLOW_TIMEOUT_SECONDS = 300.0  # 5 min max per workflow


# ---------------------------------------------------------------------------
# Pydantic plan validation models
# ---------------------------------------------------------------------------

class ValidatedWorkflowStep(BaseModel):
    """Schema-validated workflow step for LLM-generated plans."""

    description: str
    intent: str
    agent_name: str = ""
    preferred_department: Optional[str] = None
    requires_approval: bool = False
    depends_on: List[int] = Field(default_factory=list)
    estimated_duration_seconds: int = 30

    @field_validator("intent")
    @classmethod
    def intent_must_be_valid(cls, v: str) -> str:
        valid_intents = {i.value for i in Intent}
        if v not in valid_intents:
            raise ValueError(
                f"Invalid intent: {v}. Valid: {sorted(valid_intents)}"
            )
        return v

    @field_validator("depends_on")
    @classmethod
    def deps_must_be_non_negative(cls, v: List[int]) -> List[int]:
        for dep in v:
            if dep < 0:
                raise ValueError(f"Dependency index must be >= 0, got {dep}")
        return v

    @field_validator("estimated_duration_seconds")
    @classmethod
    def duration_must_be_positive(cls, v: int) -> int:
        if v < 1:
            return 30
        return v


class ValidatedWorkflowPlan(BaseModel):
    """Schema-validated workflow plan for LLM-generated plans."""

    goal: str = ""
    description: str = ""
    steps: List[ValidatedWorkflowStep] = Field(default_factory=list)
    max_duration_seconds: int = 300
    requires_user_approval: bool = False

    @field_validator("steps")
    @classmethod
    def must_have_steps(cls, v: list) -> list:
        if not v:
            raise ValueError("Plan must have at least one step")
        if len(v) > 10:
            raise ValueError(f"Plan has {len(v)} steps; maximum is 10")
        return v


def validate_plan_capabilities(
    plan: ValidatedWorkflowPlan,
    _catalog_factory=None,
) -> Tuple[bool, List[str]]:
    """Validate that a plan is executable against available capabilities.

    Checks:
    - Each step's intent has at least one agent that can handle it
    - Each step's agent (if specified) exists in the catalog
    - Dependencies form a valid DAG (no cycles, valid indices)
    - Total estimated duration is within budget
    - Steps requiring approval are flagged

    Returns ``(valid, errors)`` where *errors* is empty when valid.

    ``_catalog_factory`` is injectable for testing; defaults to
    ``chat_app.agent_catalog.get_agent_catalog``.
    """
    if _catalog_factory is None:
        from chat_app.agent_catalog import get_agent_catalog as _catalog_factory
    errors: List[str] = []
    catalog = _catalog_factory()

    # 1. Check intents are handleable and agents exist
    for i, step in enumerate(plan.steps):
        agents = catalog.get_for_intent(step.intent)
        if not agents:
            errors.append(
                f"Step {i + 1}: No agent available for intent '{step.intent}'"
            )
        if step.agent_name:
            agent = catalog.get(step.agent_name)
            if agent is None:
                errors.append(
                    f"Step {i + 1}: Agent '{step.agent_name}' not found in catalog"
                )

    # 2. Check dependency indices are valid and form a DAG
    num_steps = len(plan.steps)
    for i, step in enumerate(plan.steps):
        for dep in step.depends_on:
            if dep >= num_steps:
                errors.append(
                    f"Step {i + 1}: depends_on index {dep} out of range "
                    f"(plan has {num_steps} steps)"
                )
            elif dep >= i:
                errors.append(
                    f"Step {i + 1}: depends_on index {dep} is not a "
                    f"preceding step (would create a cycle)"
                )

    # 3. Detect cycles via topological sort (belt-and-suspenders)
    if not errors:
        adj: Dict[int, List[int]] = {i: [] for i in range(num_steps)}
        in_degree: Dict[int, int] = {i: 0 for i in range(num_steps)}
        for i, step in enumerate(plan.steps):
            for dep in step.depends_on:
                adj[dep].append(i)
                in_degree[i] += 1
        queue = [n for n in range(num_steps) if in_degree[n] == 0]
        visited = 0
        while queue:
            node = queue.pop(0)
            visited += 1
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        if visited != num_steps:
            errors.append(
                "Dependency graph contains a cycle — plan is not executable"
            )

    # 4. Check total estimated duration against budget
    total_duration = sum(s.estimated_duration_seconds for s in plan.steps)
    if total_duration > plan.max_duration_seconds:
        errors.append(
            f"Total estimated duration ({total_duration}s) exceeds budget "
            f"({plan.max_duration_seconds}s)"
        )

    # 5. Mark approval-required steps
    for i, step in enumerate(plan.steps):
        if step.intent in APPROVAL_REQUIRED_INTENTS:
            step.requires_approval = True

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Workflow models
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    PAUSED = "paused"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"


@dataclass
class WorkflowTask:
    """A single sub-task within a workflow."""
    id: int
    description: str
    intent: str
    agent_name: str = ""          # Assigned agent (resolved at runtime)
    preferred_department: Optional[Department] = None
    depends_on: List[int] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None   # AgentDispatchResult at runtime
    error: Optional[str] = None
    duration_ms: float = 0.0
    retry_count: int = 0

    @property
    def output(self) -> str:
        """Get the task output text."""
        if self.result and self.result.enriched_context:
            return self.result.enriched_context
        return ""


@dataclass
class WorkflowPlan:
    """A plan consisting of ordered sub-tasks."""
    description: str
    tasks: List[WorkflowTask] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    requires_approval: bool = False

    @property
    def total_tasks(self) -> int:
        return len(self.tasks)

    @property
    def completed_tasks(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)

    @property
    def failed_tasks(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)

    @property
    def progress_pct(self) -> float:
        if not self.tasks:
            return 100.0
        done = sum(1 for t in self.tasks if t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED))
        return round(done / len(self.tasks) * 100, 1)

    def get_ready_tasks(self) -> List[WorkflowTask]:
        """Get tasks whose dependencies are all met."""
        valid_ids = {t.id for t in self.tasks}
        completed_ids = {t.id for t in self.tasks if t.status == TaskStatus.COMPLETED}
        failed_ids = {t.id for t in self.tasks if t.status == TaskStatus.FAILED}
        ready = []
        for task in self.tasks:
            if task.status != TaskStatus.PENDING:
                continue
            # Skip tasks with invalid dependency references
            invalid_deps = [d for d in task.depends_on if d not in valid_ids]
            if invalid_deps:
                logger.warning(
                    f"[ORCHESTRATOR] Task {task.id} has invalid dependencies: {invalid_deps}, marking failed"
                )
                task.status = TaskStatus.FAILED
                task.error = f"Invalid dependency IDs: {invalid_deps}"
                continue
            # Skip tasks whose dependencies failed
            failed_deps = [d for d in task.depends_on if d in failed_ids]
            if failed_deps:
                task.status = TaskStatus.FAILED
                task.error = f"Dependency tasks failed: {failed_deps}"
                continue
            if all(dep_id in completed_ids for dep_id in task.depends_on):
                ready.append(task)
        return ready


@dataclass
class WorkflowResult:
    """Result of executing a complete workflow."""
    plan_description: str
    tasks_completed: int
    tasks_failed: int
    tasks_total: int
    combined_output: str
    agent_trace: List[Dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.plan_description,
            "completed": self.tasks_completed,
            "failed": self.tasks_failed,
            "total": self.tasks_total,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
            "agent_trace": self.agent_trace,
        }


def _validated_plan_to_workflow(
    vplan: ValidatedWorkflowPlan,
    user_input: str,
) -> WorkflowPlan:
    """Convert a ValidatedWorkflowPlan into the runtime WorkflowPlan."""
    DEPT_MAP = {d.value: d for d in Department}
    tasks: List[WorkflowTask] = []
    for i, step in enumerate(vplan.steps):
        dept = DEPT_MAP.get(step.preferred_department or "", None)
        tasks.append(
            WorkflowTask(
                id=i,
                description=step.description,
                intent=step.intent,
                agent_name=step.agent_name,
                preferred_department=dept,
                depends_on=list(step.depends_on),
                params={"user_input": user_input},
            )
        )
    return WorkflowPlan(
        description=vplan.goal or vplan.description or "Validated plan",
        tasks=tasks,
        requires_approval=vplan.requires_user_approval,
    )
