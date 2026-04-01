"""Tests for chat_app.pipeline_lineage — Pipeline trace and provenance tracking."""

import pytest

from chat_app.pipeline_lineage import (
    finalize_trace,
    get_recent_traces,
    get_stage_stats,
    get_trace,
    get_trace_by_id,
    init_trace,
    record_stage,
    _current_trace,
    _recent_traces,
    _stage_stats,
)
from chat_app.schemas import PipelineStage, PipelineTrace


@pytest.fixture(autouse=True)
def clean_state():
    """Reset trace state between tests."""
    _current_trace.set(None)
    _recent_traces.clear()
    _stage_stats.clear()
    yield
    _current_trace.set(None)


class TestInitTrace:
    def test_basic(self):
        trace = init_trace(user_input="test query", intent="spl_help", profile="default")
        assert trace.user_input == "test query"
        assert trace.intent == "spl_help"
        assert len(trace.request_id) == 16

    def test_custom_request_id(self):
        trace = init_trace(request_id="custom123")
        assert trace.request_id == "custom123"

    def test_sets_contextvar(self):
        trace = init_trace()
        assert get_trace() is trace


class TestRecordStage:
    def test_record_with_trace(self):
        init_trace()
        result = record_stage(
            PipelineStage.ROUTING,
            duration_ms=5.0,
            metadata={"intent": "spl_help"},
        )
        assert result is not None
        assert result.stage == PipelineStage.ROUTING
        assert result.duration_ms == 5.0

        trace = get_trace()
        assert len(trace.stages) == 1
        assert trace.total_duration_ms == 5.0

    def test_record_without_trace(self):
        result = record_stage(PipelineStage.ROUTING, duration_ms=5.0)
        assert result is None

    def test_multiple_stages(self):
        init_trace()
        record_stage(PipelineStage.ROUTING, duration_ms=5.0)
        record_stage(PipelineStage.RETRIEVAL, duration_ms=50.0)
        record_stage(PipelineStage.LLM_INFERENCE, duration_ms=200.0)

        trace = get_trace()
        assert len(trace.stages) == 3
        assert trace.total_duration_ms == 255.0

    def test_stage_with_error(self):
        init_trace()
        result = record_stage(
            PipelineStage.RETRIEVAL,
            duration_ms=10.0,
            success=False,
            error="ChromaDB timeout",
        )
        assert result.success is False
        assert result.error == "ChromaDB timeout"


class TestFinalizeTrace:
    def test_finalize_stores_in_recent(self):
        init_trace(intent="spl_help")
        record_stage(PipelineStage.ROUTING, duration_ms=5.0)
        trace = finalize_trace(
            strategy_used="adaptive",
            agent_name="spl_expert",
            quality_score=0.85,
            collections_searched=["spl_commands_mxbai"],
        )
        assert trace is not None
        assert trace.strategy_used == "adaptive"
        assert trace.quality_score == 0.85

        recent = get_recent_traces(10)
        assert len(recent) == 1
        assert recent[0]["intent"] == "spl_help"

    def test_finalize_without_trace(self):
        result = finalize_trace()
        assert result is None

    def test_finalize_clamps_quality(self):
        init_trace()
        trace = finalize_trace(quality_score=5.0)
        assert trace.quality_score == 1.0

    def test_finalize_with_chunk_ids(self):
        init_trace()
        trace = finalize_trace(chunk_ids=["c1", "c2", "c3"])
        assert len(trace.chunk_ids) == 3


class TestRecentTraces:
    def test_most_recent_first(self):
        for i in range(5):
            init_trace(intent=f"intent_{i}")
            finalize_trace()

        recent = get_recent_traces(10)
        assert len(recent) == 5
        assert recent[0]["intent"] == "intent_4"

    def test_limit(self):
        for i in range(10):
            init_trace()
            finalize_trace()

        recent = get_recent_traces(3)
        assert len(recent) == 3


class TestGetTraceById:
    def test_found(self):
        trace = init_trace(intent="test")
        rid = trace.request_id
        finalize_trace()

        found = get_trace_by_id(rid)
        assert found is not None
        assert found["request_id"] == rid

    def test_not_found(self):
        assert get_trace_by_id("nonexistent") is None


class TestStageStats:
    def test_stats_accumulate(self):
        for _ in range(3):
            init_trace()
            record_stage(PipelineStage.ROUTING, duration_ms=5.0)
            record_stage(PipelineStage.RETRIEVAL, duration_ms=50.0)
            finalize_trace()

        stats = get_stage_stats()
        assert "routing" in stats
        assert stats["routing"]["count"] == 3
        assert stats["routing"]["avg_ms"] == 5.0
        assert stats["retrieval"]["count"] == 3

    def test_stats_with_failures(self):
        init_trace()
        record_stage(PipelineStage.RETRIEVAL, duration_ms=10.0, success=True)
        finalize_trace()

        init_trace()
        record_stage(PipelineStage.RETRIEVAL, duration_ms=5.0, success=False)
        finalize_trace()

        stats = get_stage_stats()
        assert stats["retrieval"]["count"] == 2
        assert stats["retrieval"]["success_rate"] == 0.5

    def test_empty_stats(self):
        stats = get_stage_stats()
        assert stats == {}
