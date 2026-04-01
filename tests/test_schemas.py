"""Tests for chat_app.schemas — Pydantic validated result types."""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest
from pydantic import ValidationError

from chat_app.schemas import (
    AgentDispatchEvent,
    AgentDispatchResultSchema,
    OrchestrationEvent,
    OrchestrationResultSchema,
    PipelineStage,
    PipelineStageResult,
    PipelineTrace,
    Priority,
    ResearchFinding,
    SkillExecResultSchema,
    SkillExecutionEvent,
    TaskStatusEnum,
    WorkflowPlanSchema,
    WorkflowResultSchema,
    WorkflowTaskSchema,
)


# ── SkillExecResultSchema ──────────────────────────────────────────────

class TestSkillExecResultSchema:
    def test_create_minimal(self):
        r = SkillExecResultSchema(success=True)
        assert r.success is True
        assert r.output == ""
        assert r.duration_ms == 0.0

    def test_create_full(self):
        r = SkillExecResultSchema(
            success=False,
            output="some output",
            skill_name="analyze_spl",
            handler_key="analyze_spl",
            error="timeout",
            duration_ms=123.4,
            source="internal",
        )
        assert r.skill_name == "analyze_spl"
        assert r.error == "timeout"

    def test_duration_ms_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            SkillExecResultSchema(success=True, duration_ms=-1.0)

    def test_format_for_context_success(self):
        r = SkillExecResultSchema(success=True, output="hello")
        assert r.format_for_context() == "hello"

    def test_format_for_context_error(self):
        r = SkillExecResultSchema(success=False, skill_name="test", error="fail")
        assert "[Skill Error: test]" in r.format_for_context()

    def test_json_round_trip(self):
        r = SkillExecResultSchema(success=True, output="x", duration_ms=5.5)
        data = r.model_dump()
        r2 = SkillExecResultSchema(**data)
        assert r2 == r

    def test_json_serialization(self):
        r = SkillExecResultSchema(success=True, output="x")
        j = r.model_dump_json()
        assert isinstance(j, str)
        parsed = json.loads(j)
        assert parsed["success"] is True

    def test_from_dataclass(self):
        @dataclass
        class FakeSkillResult:
            success: bool = True
            output: str = "hi"
            skill_name: str = "test"
            handler_key: str = "test"
            data: Any = None
            error: Optional[str] = None
            duration_ms: float = 10.0
            approval_required: bool = False
            approval_message: str = ""
            source: str = "internal"

        dc = FakeSkillResult()
        schema = SkillExecResultSchema.from_dataclass(dc)
        assert schema.success is True
        assert schema.output == "hi"
        assert schema.duration_ms == 10.0


# ── AgentDispatchResultSchema ──────────────────────────────────────────

class TestAgentDispatchResultSchema:
    def test_create(self):
        r = AgentDispatchResultSchema(agent_name="spl_expert")
        assert r.agent_name == "spl_expert"
        assert r.success is True
        assert r.skill_results == []

    def test_combined_output(self):
        r = AgentDispatchResultSchema(
            agent_name="test",
            skill_results=[
                SkillExecResultSchema(success=True, output="a"),
                SkillExecResultSchema(success=False, output="b", error="err"),
                SkillExecResultSchema(success=True, output="c"),
            ],
        )
        assert r.get_combined_output() == "a\n\nc"

    def test_to_dict(self):
        r = AgentDispatchResultSchema(
            agent_name="test", agent_role="expert", department="engineering",
            duration_ms=50.123,
        )
        d = r.to_dict()
        assert d["agent_name"] == "test"
        assert d["duration_ms"] == 50.12

    def test_from_dataclass(self):
        @dataclass
        class FakeSkillResult:
            success: bool = True
            output: str = "out"
            skill_name: str = ""
            handler_key: str = ""
            data: Any = None
            error: Optional[str] = None
            duration_ms: float = 0.0
            approval_required: bool = False
            approval_message: str = ""
            source: str = ""

        @dataclass
        class FakeDispatch:
            agent_name: str = "agent1"
            agent_role: str = "role1"
            department: str = "eng"
            skills_executed: List[str] = field(default_factory=list)
            skill_results: List[Any] = field(default_factory=list)
            enriched_context: str = ""
            system_prompt_fragment: str = ""
            success: bool = True
            error: Optional[str] = None
            duration_ms: float = 5.0

        dc = FakeDispatch(skill_results=[FakeSkillResult()])
        schema = AgentDispatchResultSchema.from_dataclass(dc)
        assert schema.agent_name == "agent1"
        assert len(schema.skill_results) == 1


# ── OrchestrationResultSchema ─────────────────────────────────────────

class TestOrchestrationResultSchema:
    def test_create(self):
        r = OrchestrationResultSchema(strategy_used="adaptive")
        assert r.strategy_used == "adaptive"
        assert r.quality_score == 0.0

    def test_quality_score_bounded(self):
        with pytest.raises(ValidationError):
            OrchestrationResultSchema(strategy_used="x", quality_score=1.5)
        with pytest.raises(ValidationError):
            OrchestrationResultSchema(strategy_used="x", quality_score=-0.1)

    def test_to_dict(self):
        r = OrchestrationResultSchema(
            strategy_used="parallel", quality_score=0.85, duration_ms=200.567,
            fallback_used=True, fallback_from="adaptive",
        )
        d = r.to_dict()
        assert d["quality_score"] == 0.85
        assert d["duration_ms"] == 200.57
        assert d["fallback_used"] is True

    def test_from_dataclass_clamps_quality(self):
        @dataclass
        class FakeOrch:
            strategy_used: str = "test"
            context: str = ""
            system_prompt_fragment: str = ""
            agent_trace: List[Dict[str, Any]] = field(default_factory=list)
            iterations: int = 1
            quality_score: float = 5.0  # out of range
            duration_ms: float = 0.0
            success: bool = True
            fallback_used: bool = False
            fallback_from: str = ""
            error: Optional[str] = None

        dc = FakeOrch()
        schema = OrchestrationResultSchema.from_dataclass(dc)
        assert schema.quality_score == 1.0  # clamped


# ── WorkflowTaskSchema ────────────────────────────────────────────────

class TestWorkflowTaskSchema:
    def test_create(self):
        t = WorkflowTaskSchema(id=1, description="do stuff", intent="spl_help")
        assert t.id == 1
        assert t.status == TaskStatusEnum.PENDING
        assert t.priority == Priority.NORMAL

    def test_output_property(self):
        t = WorkflowTaskSchema(id=1, description="x", intent="y")
        assert t.output == ""

        t2 = WorkflowTaskSchema(
            id=2, description="x", intent="y",
            result=AgentDispatchResultSchema(agent_name="a", enriched_context="ctx"),
        )
        assert t2.output == "ctx"


# ── WorkflowPlanSchema ────────────────────────────────────────────────

class TestWorkflowPlanSchema:
    def test_progress(self):
        p = WorkflowPlanSchema(
            description="test plan",
            tasks=[
                WorkflowTaskSchema(id=1, description="a", intent="x", status=TaskStatusEnum.COMPLETED),
                WorkflowTaskSchema(id=2, description="b", intent="x", status=TaskStatusEnum.PENDING),
                WorkflowTaskSchema(id=3, description="c", intent="x", status=TaskStatusEnum.FAILED),
            ],
        )
        assert p.total_tasks == 3
        assert p.completed_tasks == 1
        assert p.failed_tasks == 1
        assert p.progress_pct == 33.3

    def test_get_ready_tasks(self):
        p = WorkflowPlanSchema(
            description="test",
            tasks=[
                WorkflowTaskSchema(id=1, description="a", intent="x", status=TaskStatusEnum.COMPLETED),
                WorkflowTaskSchema(id=2, description="b", intent="x", depends_on=[1]),
                WorkflowTaskSchema(id=3, description="c", intent="x", depends_on=[2]),
            ],
        )
        ready = p.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == 2

    def test_empty_plan(self):
        p = WorkflowPlanSchema(description="empty")
        assert p.progress_pct == 100.0
        assert p.get_ready_tasks() == []


# ── WorkflowResultSchema ──────────────────────────────────────────────

class TestWorkflowResultSchema:
    def test_to_dict(self):
        r = WorkflowResultSchema(
            plan_description="test", tasks_completed=2, tasks_failed=1,
            tasks_total=3, duration_ms=500.0,
        )
        d = r.to_dict()
        assert d["completed"] == 2
        assert d["total"] == 3


# ── ResearchFinding ───────────────────────────────────────────────────

class TestResearchFinding:
    def test_create(self):
        f = ResearchFinding(topic="SPL optimization", summary="Use tstats")
        assert f.confidence == 0.5
        assert f.topic == "SPL optimization"

    def test_confidence_bounded(self):
        with pytest.raises(ValidationError):
            ResearchFinding(topic="x", summary="y", confidence=2.0)
        with pytest.raises(ValidationError):
            ResearchFinding(topic="x", summary="y", confidence=-0.1)

    def test_full_finding(self):
        f = ResearchFinding(
            topic="props.conf tuning",
            summary="Use INDEXED_EXTRACTIONS for structured data",
            evidence=["Splunk docs section 4.2", "benchmark test results"],
            confidence=0.9,
            sources=["docs/props.conf.spec"],
            recommendations=["Set INDEXED_EXTRACTIONS=json"],
            agent_name="config_builder",
            skill_name="analyze_conf",
        )
        d = f.model_dump()
        assert d["confidence"] == 0.9
        assert len(d["evidence"]) == 2


# ── PipelineTrace ─────────────────────────────────────────────────────

class TestPipelineTrace:
    def test_create_with_defaults(self):
        t = PipelineTrace()
        assert len(t.request_id) == 16
        assert t.stages == []
        assert t.total_duration_ms == 0.0

    def test_add_stage(self):
        t = PipelineTrace(user_input="test query")
        t.add_stage(PipelineStageResult(
            stage=PipelineStage.ROUTING, duration_ms=5.0,
        ))
        t.add_stage(PipelineStageResult(
            stage=PipelineStage.RETRIEVAL, duration_ms=50.0,
        ))
        assert len(t.stages) == 2
        assert t.total_duration_ms == 55.0

    def test_to_summary(self):
        t = PipelineTrace(
            intent="spl_help", profile="default", strategy_used="adaptive",
            agent_name="spl_expert", quality_score=0.8,
            collections_searched=["spl_commands_mxbai"],
            chunk_ids=["c1", "c2"],
        )
        s = t.to_summary()
        assert s["intent"] == "spl_help"
        assert s["chunks"] == 2

    def test_quality_score_optional(self):
        t = PipelineTrace()
        assert t.quality_score is None

    def test_quality_score_validated(self):
        with pytest.raises(ValidationError):
            PipelineTrace(quality_score=5.0)


# ── Priority Enum ─────────────────────────────────────────────────────

class TestPriority:
    def test_ordering(self):
        assert Priority.CRITICAL < Priority.HIGH
        assert Priority.HIGH < Priority.NORMAL
        assert Priority.NORMAL < Priority.LOW
        assert Priority.LOW < Priority.BACKGROUND

    def test_values(self):
        assert Priority.CRITICAL == 0
        assert Priority.BACKGROUND == 4


# ── Journal Events ────────────────────────────────────────────────────

class TestJournalEvents:
    def test_skill_event(self):
        e = SkillExecutionEvent(
            request_id="abc", skill_name="analyze_spl",
            handler_key="analyze_spl", source="internal",
            success=True, duration_ms=10.0, agent_name="spl_expert",
        )
        assert e.event_type == "skill_execution"
        d = e.model_dump()
        assert d["request_id"] == "abc"

    def test_dispatch_event(self):
        e = AgentDispatchEvent(
            agent_name="spl_expert", department="engineering",
            skills_executed=["analyze_spl"], intent="spl_help",
        )
        assert e.event_type == "agent_dispatch"

    def test_orchestration_event(self):
        e = OrchestrationEvent(
            strategy_used="adaptive", intent="spl_help",
            quality_score=0.8, duration_ms=200.0,
        )
        assert e.event_type == "orchestration"
        assert e.quality_score == 0.8

    def test_event_timestamp_auto(self):
        before = time.time()
        e = SkillExecutionEvent()
        after = time.time()
        assert before <= e.timestamp <= after


# ── TaskStatusEnum ────────────────────────────────────────────────────

class TestTaskStatusEnum:
    def test_extended_statuses(self):
        assert TaskStatusEnum.PAUSED == "paused"
        assert TaskStatusEnum.WAITING_INPUT == "waiting_input"
        assert TaskStatusEnum.WAITING_APPROVAL == "waiting_approval"

    def test_original_statuses(self):
        assert TaskStatusEnum.PENDING == "pending"
        assert TaskStatusEnum.RUNNING == "running"
        assert TaskStatusEnum.COMPLETED == "completed"
        assert TaskStatusEnum.FAILED == "failed"
        assert TaskStatusEnum.SKIPPED == "skipped"


# ── JSON Schema Generation ────────────────────────────────────────────

class TestJsonSchema:
    def test_skill_schema(self):
        schema = SkillExecResultSchema.model_json_schema()
        assert "properties" in schema
        assert "success" in schema["properties"]

    def test_pipeline_trace_schema(self):
        schema = PipelineTrace.model_json_schema()
        assert "properties" in schema
        assert "request_id" in schema["properties"]

    def test_research_finding_schema(self):
        schema = ResearchFinding.model_json_schema()
        props = schema["properties"]
        assert "confidence" in props
