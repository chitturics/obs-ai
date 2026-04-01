"""
Pydantic schemas for structured, validated results throughout the pipeline.

These mirror the existing dataclass-based results but add:
- Field validation (ranges, constraints)
- JSON serialization with .model_dump() / .model_dump_json()
- JSON Schema generation for admin API docs
- .from_dataclass() converters for gradual migration

New schemas (ResearchFinding, PipelineStageResult, PipelineTrace) support
the SupervisorAgent pattern and pipeline lineage tracking.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskStatusEnum(str, Enum):
    """Workflow task status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    PAUSED = "paused"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"


class Priority(IntEnum):
    """Execution priority for skills/agents/tasks."""
    CRITICAL = 0   # Security, approval-gated
    HIGH = 1       # User-facing responses
    NORMAL = 2     # Standard dispatch
    LOW = 3        # Background tasks
    BACKGROUND = 4 # Idle-worker tasks


class PipelineStage(str, Enum):
    """Named stages in the request processing pipeline."""
    ROUTING = "routing"
    RETRIEVAL = "retrieval"
    ORCHESTRATION = "orchestration"
    CONTEXT_BUILD = "context_build"
    LLM_INFERENCE = "llm_inference"
    POST_PROCESS = "post_process"


# ---------------------------------------------------------------------------
# Skill Execution
# ---------------------------------------------------------------------------

class SkillExecResultSchema(BaseModel):
    """Validated result from executing any skill."""
    success: bool
    output: str = ""
    skill_name: str = ""
    handler_key: str = ""
    data: Any = None
    error: Optional[str] = None
    duration_ms: float = Field(default=0.0, ge=0.0)
    approval_required: bool = False
    approval_message: str = ""
    source: str = ""  # "tool_registry", "skills_manager", "internal", "react_loop"

    def format_for_context(self) -> str:
        if not self.success:
            return f"[Skill Error: {self.skill_name}] {self.error or 'Unknown error'}"
        return self.output

    @classmethod
    def from_dataclass(cls, dc: Any) -> "SkillExecResultSchema":
        return cls(
            success=dc.success,
            output=dc.output,
            skill_name=dc.skill_name,
            handler_key=dc.handler_key,
            data=dc.data,
            error=dc.error,
            duration_ms=dc.duration_ms,
            approval_required=dc.approval_required,
            approval_message=dc.approval_message,
            source=dc.source,
        )


# ---------------------------------------------------------------------------
# Agent Dispatch
# ---------------------------------------------------------------------------

class AgentDispatchResultSchema(BaseModel):
    """Validated result of an agent dispatch operation."""
    agent_name: str
    agent_role: str = ""
    department: str = ""
    skills_executed: List[str] = Field(default_factory=list)
    skill_results: List[SkillExecResultSchema] = Field(default_factory=list)
    enriched_context: str = ""
    system_prompt_fragment: str = ""
    success: bool = True
    error: Optional[str] = None
    duration_ms: float = Field(default=0.0, ge=0.0)

    def get_combined_output(self) -> str:
        parts = []
        for result in self.skill_results:
            if result.success and result.output:
                parts.append(result.output)
        return "\n\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "department": self.department,
            "skills_executed": self.skills_executed,
            "success": self.success,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }

    @classmethod
    def from_dataclass(cls, dc: Any) -> "AgentDispatchResultSchema":
        return cls(
            agent_name=dc.agent_name,
            agent_role=dc.agent_role,
            department=dc.department,
            skills_executed=dc.skills_executed,
            skill_results=[SkillExecResultSchema.from_dataclass(r) for r in dc.skill_results],
            enriched_context=dc.enriched_context,
            system_prompt_fragment=dc.system_prompt_fragment,
            success=dc.success,
            error=dc.error,
            duration_ms=dc.duration_ms,
        )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

class OrchestrationResultSchema(BaseModel):
    """Validated output from any orchestration strategy."""
    strategy_used: str
    context: str = ""
    system_prompt_fragment: str = ""
    agent_trace: List[Dict[str, Any]] = Field(default_factory=list)
    iterations: int = Field(default=1, ge=0)
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    duration_ms: float = Field(default=0.0, ge=0.0)
    success: bool = True
    fallback_used: bool = False
    fallback_from: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "strategy_used": self.strategy_used,
            "iterations": self.iterations,
            "quality_score": round(self.quality_score, 4),
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "fallback_used": self.fallback_used,
            "fallback_from": self.fallback_from,
            "trace_steps": len(self.agent_trace),
        }
        if self.error:
            d["error"] = self.error
        return d

    @classmethod
    def from_dataclass(cls, dc: Any) -> "OrchestrationResultSchema":
        return cls(
            strategy_used=dc.strategy_used,
            context=dc.context,
            system_prompt_fragment=dc.system_prompt_fragment,
            agent_trace=dc.agent_trace,
            iterations=dc.iterations,
            quality_score=max(0.0, min(1.0, dc.quality_score)),
            duration_ms=dc.duration_ms,
            success=dc.success,
            fallback_used=dc.fallback_used,
            fallback_from=dc.fallback_from,
            error=dc.error,
        )


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

class WorkflowTaskSchema(BaseModel):
    """Validated single sub-task within a workflow."""
    id: int
    description: str
    intent: str
    agent_name: str = ""
    preferred_department: Optional[str] = None
    depends_on: List[int] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    status: TaskStatusEnum = TaskStatusEnum.PENDING
    result: Optional[AgentDispatchResultSchema] = None
    error: Optional[str] = None
    duration_ms: float = Field(default=0.0, ge=0.0)
    retry_count: int = Field(default=0, ge=0)
    priority: Priority = Priority.NORMAL

    @property
    def output(self) -> str:
        if self.result and self.result.enriched_context:
            return self.result.enriched_context
        return ""

    @classmethod
    def from_dataclass(cls, dc: Any) -> "WorkflowTaskSchema":
        result = None
        if dc.result is not None:
            result = AgentDispatchResultSchema.from_dataclass(dc.result)
        dept = None
        if dc.preferred_department is not None:
            dept = dc.preferred_department.value if hasattr(dc.preferred_department, "value") else str(dc.preferred_department)
        return cls(
            id=dc.id,
            description=dc.description,
            intent=dc.intent,
            agent_name=dc.agent_name,
            preferred_department=dept,
            depends_on=dc.depends_on,
            params=dc.params,
            status=TaskStatusEnum(dc.status.value) if hasattr(dc.status, "value") else TaskStatusEnum.PENDING,
            result=result,
            error=dc.error,
            duration_ms=dc.duration_ms,
            retry_count=dc.retry_count,
        )


class WorkflowPlanSchema(BaseModel):
    """Validated plan consisting of ordered sub-tasks."""
    description: str
    tasks: List[WorkflowTaskSchema] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)

    @property
    def total_tasks(self) -> int:
        return len(self.tasks)

    @property
    def completed_tasks(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatusEnum.COMPLETED)

    @property
    def failed_tasks(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatusEnum.FAILED)

    @property
    def progress_pct(self) -> float:
        if not self.tasks:
            return 100.0
        done = sum(1 for t in self.tasks if t.status in (TaskStatusEnum.COMPLETED, TaskStatusEnum.SKIPPED))
        return round(done / len(self.tasks) * 100, 1)

    def get_ready_tasks(self) -> List[WorkflowTaskSchema]:
        completed_ids = {t.id for t in self.tasks if t.status == TaskStatusEnum.COMPLETED}
        ready = []
        for task in self.tasks:
            if task.status != TaskStatusEnum.PENDING:
                continue
            if all(dep_id in completed_ids for dep_id in task.depends_on):
                ready.append(task)
        return ready

    @classmethod
    def from_dataclass(cls, dc: Any) -> "WorkflowPlanSchema":
        return cls(
            description=dc.description,
            tasks=[WorkflowTaskSchema.from_dataclass(t) for t in dc.tasks],
            created_at=dc.created_at,
        )


class WorkflowResultSchema(BaseModel):
    """Result of executing a complete workflow."""
    plan_description: str
    tasks_completed: int = Field(ge=0)
    tasks_failed: int = Field(ge=0)
    tasks_total: int = Field(ge=0)
    combined_output: str = ""
    agent_trace: List[Dict[str, Any]] = Field(default_factory=list)
    duration_ms: float = Field(default=0.0, ge=0.0)
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


# ---------------------------------------------------------------------------
# NEW: ResearchFinding (SupervisorAgent output)
# ---------------------------------------------------------------------------

class ResearchFinding(BaseModel):
    """Structured output from a supervised research task.

    Used by SupervisorAgent to collect typed results from worker agents,
    enabling synthesis with provenance tracking.
    """
    topic: str
    summary: str
    evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sources: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    agent_name: str = ""
    skill_name: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# NEW: Pipeline Lineage
# ---------------------------------------------------------------------------

class PipelineStageResult(BaseModel):
    """Result from a single pipeline stage, for lineage tracking."""
    stage: PipelineStage
    duration_ms: float = Field(default=0.0, ge=0.0)
    success: bool = True
    input_summary: str = ""
    output_summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class PipelineTrace(BaseModel):
    """Full trace of a request through the pipeline.

    Captures stage-level metrics, chunk provenance, agent contributions,
    and quality scores for observability and debugging.
    """
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_input: str = ""
    intent: str = ""
    profile: str = ""
    stages: List[PipelineStageResult] = Field(default_factory=list)
    total_duration_ms: float = Field(default=0.0, ge=0.0)
    strategy_used: str = ""
    agent_name: str = ""
    quality_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    chunk_ids: List[str] = Field(default_factory=list)
    collections_searched: List[str] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)

    def add_stage(self, stage: PipelineStageResult) -> None:
        """Append a stage and update total duration."""
        self.stages.append(stage)
        self.total_duration_ms = sum(s.duration_ms for s in self.stages)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "intent": self.intent,
            "profile": self.profile,
            "strategy": self.strategy_used,
            "agent": self.agent_name,
            "quality_score": self.quality_score,
            "total_ms": round(self.total_duration_ms, 1),
            "stages": len(self.stages),
            "collections": self.collections_searched,
            "chunks": len(self.chunk_ids),
        }


# ---------------------------------------------------------------------------
# Execution Journal Events
# ---------------------------------------------------------------------------

class SkillExecutionEvent(BaseModel):
    """Event logged when a skill is executed."""
    request_id: str = ""
    skill_name: str = ""
    handler_key: str = ""
    source: str = ""
    success: bool = True
    duration_ms: float = Field(default=0.0, ge=0.0)
    agent_name: str = ""
    error: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    event_type: str = "skill_execution"


class AgentDispatchEvent(BaseModel):
    """Event logged when an agent is dispatched."""
    request_id: str = ""
    agent_name: str = ""
    department: str = ""
    skills_executed: List[str] = Field(default_factory=list)
    intent: str = ""
    duration_ms: float = Field(default=0.0, ge=0.0)
    success: bool = True
    error: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    event_type: str = "agent_dispatch"


class OrchestrationEvent(BaseModel):
    """Event logged when an orchestration strategy runs."""
    request_id: str = ""
    strategy_used: str = ""
    intent: str = ""
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    duration_ms: float = Field(default=0.0, ge=0.0)
    fallback_used: bool = False
    iterations: int = 1
    success: bool = True
    error: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    event_type: str = "orchestration"


class QueryEvent(BaseModel):
    """Event logged for every user query processed through the pipeline."""
    request_id: str = ""
    query: str = ""
    intent: str = ""
    profile: str = ""
    strategy_used: str = ""
    agent_name: str = ""
    chunks_found: int = 0
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    gci_score: float = Field(default=0.0, ge=0.0, le=10.0)
    duration_ms: float = Field(default=0.0, ge=0.0)
    success: bool = True
    error: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    event_type: str = "query"
