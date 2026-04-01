"""Tests for workflow_contracts and lesson_store modules."""
import pytest
from chat_app.workflow_contracts import (
    WorkflowStepContract,
    StepDecision,
    validate_step_inputs,
    validate_step_outputs,
    decide_step_outcome,
    get_contract,
    get_all_contracts,
    get_contract_summary,
    PIPELINE_CONTRACTS,
    WORKFLOW_CONTRACTS,
)
from chat_app.lesson_store import (
    LessonStore,
    LessonEntry,
    LessonCategory,
    LessonSeverity,
)


# ---------------------------------------------------------------------------
# WorkflowStepContract
# ---------------------------------------------------------------------------

class TestWorkflowStepContract:
    def test_frozen_immutability(self):
        c = WorkflowStepContract(
            step_name="test", description="test", required_inputs=frozenset({"a"}),
            expected_outputs=frozenset({"b"}), definition_of_done="done",
            error_code="E_TEST",
        )
        with pytest.raises(AttributeError):
            c.step_name = "changed"

    def test_default_values(self):
        c = WorkflowStepContract(
            step_name="test", description="test", required_inputs=frozenset(),
            expected_outputs=frozenset(), definition_of_done="done",
            error_code="E_TEST",
        )
        assert c.max_retries == 2
        assert c.timeout_seconds == 30.0
        assert c.quality_threshold == 0.5


class TestValidation:
    def test_inputs_all_present(self):
        c = WorkflowStepContract(
            step_name="test", description="", required_inputs=frozenset({"a", "b"}),
            expected_outputs=frozenset(), definition_of_done="", error_code="E",
        )
        violations = validate_step_inputs(c, {"a": 1, "b": 2, "c": 3})
        assert len(violations) == 0

    def test_inputs_missing(self):
        c = WorkflowStepContract(
            step_name="test", description="", required_inputs=frozenset({"a", "b"}),
            expected_outputs=frozenset(), definition_of_done="", error_code="E",
        )
        violations = validate_step_inputs(c, {"a": 1})
        assert len(violations) == 1
        assert "b" in violations[0].missing_keys

    def test_inputs_none_value_treated_as_missing(self):
        c = WorkflowStepContract(
            step_name="test", description="", required_inputs=frozenset({"a"}),
            expected_outputs=frozenset(), definition_of_done="", error_code="E",
        )
        violations = validate_step_inputs(c, {"a": None})
        assert len(violations) == 1

    def test_outputs_all_present(self):
        c = WorkflowStepContract(
            step_name="test", description="", required_inputs=frozenset(),
            expected_outputs=frozenset({"x", "y"}), definition_of_done="", error_code="E",
        )
        violations = validate_step_outputs(c, {"x": "val", "y": "val"})
        assert len(violations) == 0

    def test_outputs_missing(self):
        c = WorkflowStepContract(
            step_name="test", description="", required_inputs=frozenset(),
            expected_outputs=frozenset({"x", "y"}), definition_of_done="", error_code="E",
        )
        violations = validate_step_outputs(c, {"x": "val"})
        assert len(violations) == 1


class TestDecision:
    def test_proceed_when_all_good(self):
        c = WorkflowStepContract(
            step_name="test", description="", required_inputs=frozenset(),
            expected_outputs=frozenset({"result"}), definition_of_done="",
            error_code="E", quality_threshold=0.5,
        )
        outcome = decide_step_outcome(c, {"result": "ok"}, quality_score=0.8)
        assert outcome.decision == StepDecision.PROCEED

    def test_refine_when_quality_low(self):
        c = WorkflowStepContract(
            step_name="test", description="", required_inputs=frozenset(),
            expected_outputs=frozenset({"result"}), definition_of_done="",
            error_code="E", quality_threshold=0.5, max_retries=2,
        )
        outcome = decide_step_outcome(c, {"result": "ok"}, quality_score=0.3, retry_count=0)
        assert outcome.decision == StepDecision.REFINE

    def test_pivot_when_retries_exhausted(self):
        c = WorkflowStepContract(
            step_name="test", description="", required_inputs=frozenset(),
            expected_outputs=frozenset({"result"}), definition_of_done="",
            error_code="E", quality_threshold=0.5, max_retries=2,
        )
        outcome = decide_step_outcome(c, {"result": "ok"}, quality_score=0.3, retry_count=2)
        assert outcome.decision == StepDecision.PIVOT

    def test_refine_when_outputs_missing(self):
        c = WorkflowStepContract(
            step_name="test", description="", required_inputs=frozenset(),
            expected_outputs=frozenset({"result"}), definition_of_done="",
            error_code="E", max_retries=2,
        )
        outcome = decide_step_outcome(c, {}, retry_count=0)
        assert outcome.decision == StepDecision.REFINE

    def test_pivot_when_outputs_missing_and_retries_done(self):
        c = WorkflowStepContract(
            step_name="test", description="", required_inputs=frozenset(),
            expected_outputs=frozenset({"result"}), definition_of_done="",
            error_code="E", max_retries=1,
        )
        outcome = decide_step_outcome(c, {}, retry_count=1)
        assert outcome.decision == StepDecision.PIVOT


class TestContractRegistry:
    def test_pipeline_contracts_exist(self):
        assert len(PIPELINE_CONTRACTS) >= 6

    def test_workflow_contracts_exist(self):
        assert len(WORKFLOW_CONTRACTS) >= 3

    def test_get_contract_by_name(self):
        c = get_contract("retrieval")
        assert c is not None
        assert c.step_name == "retrieval"

    def test_get_contract_unknown_returns_none(self):
        assert get_contract("nonexistent") is None

    def test_get_all_contracts(self):
        all_c = get_all_contracts()
        assert len(all_c) >= 9

    def test_summary(self):
        summary = get_contract_summary()
        assert "total" in summary
        assert "contracts" in summary
        assert summary["total"] >= 9


# ---------------------------------------------------------------------------
# LessonStore
# ---------------------------------------------------------------------------

class TestLessonEntry:
    def test_auto_id_generation(self):
        entry = LessonEntry(description="test", fix="fix it")
        assert len(entry.lesson_id) == 16

    def test_auto_timestamp(self):
        entry = LessonEntry(description="test")
        assert entry.created_at != ""

    def test_time_decay_fresh(self):
        entry = LessonEntry(description="test")
        weight = entry.time_decay_weight()
        assert 0.99 <= weight <= 1.0  # Just created, should be near 1.0

    def test_relevance_score_keyword_match(self):
        entry = LessonEntry(
            description="stats command error",
            keywords=["stats", "count", "by"],
            intent="spl_generation",
        )
        score = entry.relevance_score("stats count by host", "spl_generation")
        assert score > 0.3  # Should have good relevance

    def test_relevance_score_no_match(self):
        entry = LessonEntry(
            description="redis connection timeout",
            keywords=["redis", "timeout"],
            intent="config_check",
        )
        score = entry.relevance_score("what is Splunk?", "general_qa")
        assert score < 0.2

    def test_context_string(self):
        entry = LessonEntry(
            category="spl_error",
            description="Missing BY clause",
            fix="Add 'by <field>' after stats",
        )
        ctx = entry.to_context_string()
        assert "SPL_ERROR" in ctx
        assert "Missing BY clause" in ctx


class TestLessonStore:
    def test_record_and_retrieve(self, tmp_path):
        store = LessonStore(persist_path=str(tmp_path / "lessons.jsonl"))
        store.record_lesson(
            category="spl_error",
            description="Missing BY clause in stats",
            fix="Always include BY clause",
            keywords=["stats", "by"],
            intent="spl_generation",
        )
        assert len(store.get_all()) == 1

    def test_deduplication(self, tmp_path):
        store = LessonStore(persist_path=str(tmp_path / "lessons.jsonl"))
        store.record_lesson(description="same lesson", fix="same fix")
        store.record_lesson(description="same lesson", fix="same fix")
        assert len(store.get_all()) == 1  # Deduplicated
        assert store.get_all()[0].times_applied == 1

    def test_query_relevant(self, tmp_path):
        store = LessonStore(persist_path=str(tmp_path / "lessons.jsonl"))
        store.record_lesson(
            description="stats requires BY clause",
            fix="Add BY clause",
            keywords=["stats", "by", "group"],
            intent="spl_generation",
        )
        store.record_lesson(
            description="Redis timeout on cache",
            fix="Increase timeout",
            keywords=["redis", "cache", "timeout"],
            intent="config_check",
        )
        results = store.query_relevant("stats count by host", "spl_generation")
        assert len(results) >= 1
        assert results[0].description == "stats requires BY clause"

    def test_format_for_context(self, tmp_path):
        store = LessonStore(persist_path=str(tmp_path / "lessons.jsonl"))
        store.record_lesson(
            description="test lesson",
            fix="test fix",
            keywords=["test"],
        )
        ctx = store.format_for_context("test query")
        assert "Known Pitfalls" in ctx or ctx == ""

    def test_delete_lesson(self, tmp_path):
        store = LessonStore(persist_path=str(tmp_path / "lessons.jsonl"))
        entry = store.record_lesson(description="deleteme", fix="fix")
        assert store.delete_lesson(entry.lesson_id) is True
        assert len(store.get_all()) == 0

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "lessons.jsonl")
        store1 = LessonStore(persist_path=path)
        store1.record_lesson(description="persist test", fix="fix", keywords=["persist"])
        # Create new store from same file
        store2 = LessonStore(persist_path=path)
        assert len(store2.get_all()) == 1
        assert store2.get_all()[0].description == "persist test"

    def test_stats(self, tmp_path):
        store = LessonStore(persist_path=str(tmp_path / "lessons.jsonl"))
        store.record_lesson(category="spl_error", description="a", fix="b")
        store.record_lesson(category="hallucination", description="c", fix="d")
        stats = store.get_stats()
        assert stats["total_lessons"] == 2
        assert "spl_error" in stats["by_category"]
