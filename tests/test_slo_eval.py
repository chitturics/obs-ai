"""Tests for slo_gate.py and eval_gate.py.

Covers:
- SLO definition validity (thresholds, operators, count)
- SLO evaluator logic (lt/gt operators, budget calculation, no-data handling)
- SLO report structure
- Eval test-case field completeness
- Eval category / intent coverage
- Keyword scoring logic (hit, forbidden, min_length)
- Aggregate pass/fail thresholds
- CLI structural gate (run_eval_gate)
- EvalResult serialisation
- SLOResult serialisation
"""

import pytest

# ---------------------------------------------------------------------------
# SLO gate imports
# ---------------------------------------------------------------------------
from chat_app.slo_gate import (
    DEFAULT_SLOS,
    OPERATOR_GT,
    OPERATOR_LT,
    QUERY_LATENCY_P95_SECONDS,
    QUERY_LATENCY_P99_SECONDS,
    RETRIEVAL_LATENCY_P95_SECONDS,
    LLM_LATENCY_P95_SECONDS,
    MAX_ERROR_RATE_FRACTION,
    MIN_CACHE_HIT_RATE_FRACTION,
    SLODefinition,
    SLOEvaluator,
    SLOResult,
    get_slo_report,
    _approximate_quantile,
)

# ---------------------------------------------------------------------------
# Eval gate imports
# ---------------------------------------------------------------------------
from chat_app.eval_gate import (
    GOLDEN_CASES,
    RELEASE_QUALITY_THRESHOLD,
    CaseResult,
    EvalResult,
    EvalTestCase,
    EvalThresholds,
    _error_case,
    _score_case,
    run_eval_gate,
    run_eval_suite,
)


# ===========================================================================
# SLO Definition tests
# ===========================================================================

class TestSLODefinitions:
    """Verify the DEFAULT_SLOS list meets structural and value requirements."""

    def test_at_least_six_slos_defined(self) -> None:
        assert len(DEFAULT_SLOS) >= 6, (
            f"Expected at least 6 SLOs, got {len(DEFAULT_SLOS)}"
        )

    def test_all_slos_have_non_empty_names(self) -> None:
        for slo in DEFAULT_SLOS:
            assert slo.name.strip(), f"SLO has empty name: {slo}"

    def test_all_slo_names_are_unique(self) -> None:
        names = [slo.name for slo in DEFAULT_SLOS]
        assert len(names) == len(set(names)), f"Duplicate SLO names: {names}"

    def test_all_slos_have_valid_operators(self) -> None:
        for slo in DEFAULT_SLOS:
            assert slo.operator in {OPERATOR_LT, OPERATOR_GT}, (
                f"SLO '{slo.name}' has invalid operator '{slo.operator}'"
            )

    def test_query_latency_p95_threshold_is_10_seconds(self) -> None:
        slo = next(s for s in DEFAULT_SLOS if s.name == "query_latency_p95")
        assert slo.threshold == QUERY_LATENCY_P95_SECONDS
        assert slo.operator == OPERATOR_LT

    def test_query_latency_p99_threshold_is_30_seconds(self) -> None:
        slo = next(s for s in DEFAULT_SLOS if s.name == "query_latency_p99")
        assert slo.threshold == QUERY_LATENCY_P99_SECONDS
        assert slo.operator == OPERATOR_LT

    def test_retrieval_latency_p95_threshold_is_2_seconds(self) -> None:
        slo = next(s for s in DEFAULT_SLOS if s.name == "retrieval_latency_p95")
        assert slo.threshold == RETRIEVAL_LATENCY_P95_SECONDS
        assert slo.operator == OPERATOR_LT

    def test_llm_latency_p95_threshold_is_15_seconds(self) -> None:
        slo = next(s for s in DEFAULT_SLOS if s.name == "llm_latency_p95")
        assert slo.threshold == LLM_LATENCY_P95_SECONDS
        assert slo.operator == OPERATOR_LT

    def test_error_rate_threshold_is_5_percent(self) -> None:
        slo = next(s for s in DEFAULT_SLOS if s.name == "error_rate")
        assert slo.threshold == MAX_ERROR_RATE_FRACTION
        assert slo.operator == OPERATOR_LT

    def test_cache_hit_rate_threshold_is_30_percent(self) -> None:
        slo = next(s for s in DEFAULT_SLOS if s.name == "cache_hit_rate")
        assert slo.threshold == MIN_CACHE_HIT_RATE_FRACTION
        assert slo.operator == OPERATOR_GT

    def test_all_slo_thresholds_are_positive(self) -> None:
        for slo in DEFAULT_SLOS:
            assert slo.threshold > 0, (
                f"SLO '{slo.name}' has non-positive threshold {slo.threshold}"
            )

    def test_all_slo_window_minutes_are_positive(self) -> None:
        for slo in DEFAULT_SLOS:
            assert slo.window_minutes > 0, (
                f"SLO '{slo.name}' has non-positive window_minutes {slo.window_minutes}"
            )

    def test_slo_definition_is_frozen(self) -> None:
        slo = DEFAULT_SLOS[0]
        with pytest.raises((AttributeError, TypeError)):
            slo.threshold = 999.0  # type: ignore[misc]

    def test_invalid_operator_raises(self) -> None:
        with pytest.raises(ValueError, match="operator"):
            SLODefinition(
                name="bad",
                metric="m",
                threshold=1.0,
                operator="eq",  # invalid
            )


# ===========================================================================
# SLO Evaluator tests
# ===========================================================================

class TestSLOEvaluator:
    """Unit tests for SLOEvaluator._check() and evaluate_all() logic."""

    def _make_lt_slo(self, name: str = "test_lt", threshold: float = 10.0) -> SLODefinition:
        return SLODefinition(
            name=name,
            metric=f"metric_{name}",
            threshold=threshold,
            operator=OPERATOR_LT,
        )

    def _make_gt_slo(self, name: str = "test_gt", threshold: float = 0.3) -> SLODefinition:
        return SLODefinition(
            name=name,
            metric=f"metric_{name}",
            threshold=threshold,
            operator=OPERATOR_GT,
        )

    def test_lt_slo_passes_when_actual_below_threshold(self) -> None:
        slo = self._make_lt_slo(threshold=10.0)
        passed, budget = SLOEvaluator._check(slo, actual=5.0)
        assert passed is True
        assert budget == pytest.approx(0.5)  # (10 - 5) / 10

    def test_lt_slo_fails_when_actual_equals_threshold(self) -> None:
        slo = self._make_lt_slo(threshold=10.0)
        passed, _budget = SLOEvaluator._check(slo, actual=10.0)
        assert passed is False

    def test_lt_slo_fails_when_actual_above_threshold(self) -> None:
        slo = self._make_lt_slo(threshold=10.0)
        passed, budget = SLOEvaluator._check(slo, actual=12.0)
        assert passed is False
        assert budget < 0  # breached — negative budget

    def test_gt_slo_passes_when_actual_above_threshold(self) -> None:
        slo = self._make_gt_slo(threshold=0.3)
        passed, budget = SLOEvaluator._check(slo, actual=0.5)
        assert passed is True
        assert budget == pytest.approx((0.5 - 0.3) / 0.3)

    def test_gt_slo_fails_when_actual_below_threshold(self) -> None:
        slo = self._make_gt_slo(threshold=0.3)
        passed, budget = SLOEvaluator._check(slo, actual=0.1)
        assert passed is False
        assert budget < 0

    def test_no_data_returns_passing_result(self) -> None:
        """When a metric is absent, the evaluator should not block (optimistic)."""
        slo = self._make_lt_slo()
        evaluator = SLOEvaluator(slos=[slo])
        # Empty metrics dict → no data for the metric
        results = evaluator._evaluate_one(slo, metrics={})
        assert results.passed is True
        assert results.actual_value is None
        assert results.budget_remaining == 1.0

    def test_evaluate_all_returns_one_result_per_slo(self) -> None:
        evaluator = SLOEvaluator(slos=DEFAULT_SLOS)
        results = evaluator.evaluate_all()
        assert len(results) == len(DEFAULT_SLOS)

    def test_evaluate_one_returns_none_for_unknown_name(self) -> None:
        evaluator = SLOEvaluator()
        result = evaluator.evaluate_one("nonexistent_slo_xyz")
        assert result is None

    def test_slo_result_to_dict_has_required_keys(self) -> None:
        slo = self._make_lt_slo()
        result = SLOResult(
            slo=slo,
            passed=True,
            actual_value=5.0,
            budget_remaining=0.5,
            message="PASS",
        )
        data = result.to_dict()
        for key in ("name", "metric", "threshold", "operator", "passed",
                    "actual_value", "budget_remaining", "message", "evaluated_at"):
            assert key in data, f"Missing key '{key}' in SLOResult.to_dict()"

    def test_get_slo_report_structure(self) -> None:
        report = get_slo_report()
        for key in ("passed", "total", "passing_count", "failing_count",
                    "slos", "evaluated_at"):
            assert key in report, f"Missing key '{key}' in SLO report"
        assert report["total"] == len(DEFAULT_SLOS)
        assert report["passing_count"] + report["failing_count"] == report["total"]

    def test_approximate_quantile_midpoint(self) -> None:
        # Buckets: 0–1 → 50 obs, 1–2 → 50 obs (total 100)
        buckets = {1.0: 50.0, 2.0: 100.0, float("inf"): 100.0}
        p50 = _approximate_quantile(buckets, 100, 0.50)
        assert 0.9 <= p50 <= 1.1, f"Expected ~1.0 for p50, got {p50}"

    def test_approximate_quantile_empty_buckets(self) -> None:
        result = _approximate_quantile({}, 0, 0.95)
        assert result == 0.0


# ===========================================================================
# Eval test-case structure tests
# ===========================================================================

class TestEvalTestCaseStructure:
    """Verify GOLDEN_CASES meet the field and coverage requirements."""

    def test_at_least_20_golden_cases(self) -> None:
        assert len(GOLDEN_CASES) >= 20, (
            f"Expected at least 20 cases, got {len(GOLDEN_CASES)}"
        )

    def test_all_cases_have_non_empty_query(self) -> None:
        for index, case in enumerate(GOLDEN_CASES):
            assert case.query.strip(), f"Case {index} has empty query"

    def test_all_cases_have_non_empty_intent(self) -> None:
        for index, case in enumerate(GOLDEN_CASES):
            assert case.intent.strip(), f"Case {index} has empty intent"

    def test_all_cases_have_non_empty_category(self) -> None:
        for index, case in enumerate(GOLDEN_CASES):
            assert case.category.strip(), f"Case {index} has empty category"

    def test_all_cases_have_at_least_one_expected_keyword(self) -> None:
        for index, case in enumerate(GOLDEN_CASES):
            assert len(case.expected_keywords) >= 1, (
                f"Case {index} ('{case.query[:40]}') has no expected_keywords"
            )

    def test_all_cases_have_non_negative_min_length(self) -> None:
        for index, case in enumerate(GOLDEN_CASES):
            assert case.min_length >= 0, (
                f"Case {index} has negative min_length {case.min_length}"
            )

    def test_spl_generation_has_at_least_5_cases(self) -> None:
        count = sum(1 for c in GOLDEN_CASES if c.category == "spl_generation")
        assert count >= 5, f"Only {count} spl_generation cases (need 5+)"

    def test_spl_explanation_has_at_least_5_cases(self) -> None:
        count = sum(1 for c in GOLDEN_CASES if c.category == "spl_explanation")
        assert count >= 5, f"Only {count} spl_explanation cases (need 5+)"

    def test_conceptual_has_at_least_5_cases(self) -> None:
        count = sum(1 for c in GOLDEN_CASES if c.category == "conceptual")
        assert count >= 5, f"Only {count} conceptual cases (need 5+)"

    def test_config_troubleshoot_has_at_least_5_cases(self) -> None:
        count = sum(1 for c in GOLDEN_CASES if c.category == "config_troubleshoot")
        assert count >= 5, f"Only {count} config_troubleshoot cases (need 5+)"

    def test_release_quality_threshold_is_80_percent(self) -> None:
        assert RELEASE_QUALITY_THRESHOLD == 0.80


# ===========================================================================
# Scoring logic tests
# ===========================================================================

class TestScoringLogic:
    """Unit tests for _score_case and _error_case."""

    def _make_case(
        self,
        expected: list,
        forbidden: list,
        min_length: int = 10,
    ) -> EvalTestCase:
        return EvalTestCase(
            query="test query",
            intent="general_qa",
            category="conceptual",
            expected_keywords=expected,
            forbidden_keywords=forbidden,
            min_length=min_length,
        )

    def test_all_criteria_met_passes(self) -> None:
        case = self._make_case(expected=["stats"], forbidden=["I cannot"], min_length=5)
        result = _score_case(case, response="The stats command counts events.")
        assert result.passed is True
        assert result.keyword_hit is True
        assert result.no_forbidden is True
        assert result.min_length_met is True
        assert result.matched_keyword == "stats"

    def test_missing_expected_keyword_fails(self) -> None:
        case = self._make_case(expected=["tstats"], forbidden=[], min_length=5)
        result = _score_case(case, response="This is a general answer about indexes.")
        assert result.passed is False
        assert result.keyword_hit is False
        assert result.matched_keyword is None

    def test_forbidden_keyword_present_fails(self) -> None:
        case = self._make_case(expected=["splunk"], forbidden=["I cannot"], min_length=5)
        result = _score_case(case, response="I cannot help with Splunk right now.")
        assert result.passed is False
        assert result.no_forbidden is False
        assert result.matched_forbidden == "I cannot"
        # expected keyword still matched (splunk appears in response)
        assert result.keyword_hit is True

    def test_response_too_short_fails(self) -> None:
        case = self._make_case(expected=["stats"], forbidden=[], min_length=200)
        result = _score_case(case, response="Use stats.")
        assert result.passed is False
        assert result.min_length_met is False
        assert result.keyword_hit is True

    def test_keyword_matching_is_case_insensitive(self) -> None:
        case = self._make_case(expected=["Stats"], forbidden=[], min_length=1)
        result = _score_case(case, response="use the STATS command")
        assert result.keyword_hit is True

    def test_forbidden_matching_is_case_insensitive(self) -> None:
        case = self._make_case(expected=["splunk"], forbidden=["I CANNOT"], min_length=1)
        result = _score_case(case, response="i cannot provide splunk info")
        assert result.no_forbidden is False

    def test_score_is_fraction_of_criteria_met(self) -> None:
        case = self._make_case(expected=["stats"], forbidden=[], min_length=1000)
        # keyword_hit=True, no_forbidden=True, min_length_met=False → 2/3
        result = _score_case(case, response="stats command is useful")
        assert result.score == pytest.approx(2 / 3)

    def test_error_case_is_always_failing(self) -> None:
        case = self._make_case(expected=["anything"], forbidden=[], min_length=1)
        result = _error_case(case, error_message="Connection refused")
        assert result.passed is False
        assert result.error == "Connection refused"
        assert result.response is None


# ===========================================================================
# run_eval_gate (structural gate) tests
# ===========================================================================

class TestRunEvalGate:
    """Tests for the structural-only gate that runs without a live pipeline."""

    def test_structural_gate_passes_with_default_cases(self) -> None:
        result = run_eval_gate()
        assert result["passed"] is True, (
            f"Structural gate failed: {result['failures']}"
        )

    def test_structural_gate_result_has_required_keys(self) -> None:
        result = run_eval_gate()
        for key in ("passed", "failures", "warnings", "golden_cases",
                    "categories", "intents_covered", "timestamp"):
            assert key in result, f"Missing key '{key}' in run_eval_gate result"

    def test_structural_gate_reports_correct_case_count(self) -> None:
        result = run_eval_gate()
        assert result["golden_cases"] == len(GOLDEN_CASES)

    def test_structural_gate_fails_when_min_test_cases_too_high(self) -> None:
        thresholds = EvalThresholds(min_test_cases=9999)
        result = run_eval_gate(thresholds=thresholds)
        assert result["passed"] is False
        assert any("golden cases" in f for f in result["failures"])


# ===========================================================================
# run_eval_suite (aggregate logic) tests
# ===========================================================================

class TestRunEvalSuite:
    """Tests for the live evaluation runner using mock cases."""

    def _passing_case(self) -> EvalTestCase:
        return EvalTestCase(
            query="What is Splunk?",
            intent="general_qa",
            category="conceptual",
            expected_keywords=["test_keyword"],
            forbidden_keywords=[],
            min_length=5,
        )

    def _failing_case(self) -> EvalTestCase:
        return EvalTestCase(
            query="No match query",
            intent="general_qa",
            category="conceptual",
            expected_keywords=["xyzzy_not_in_any_response_ever"],
            forbidden_keywords=[],
            min_length=5,
        )

    def test_eval_result_to_dict_has_required_keys(self) -> None:
        result = EvalResult(
            overall_passed=True,
            pass_rate=1.0,
            total=5,
            passed_count=5,
            failed_count=0,
            threshold=0.80,
            case_results=[],
            failures=[],
        )
        data = result.to_dict()
        for key in ("overall_passed", "pass_rate", "total", "passed_count",
                    "failed_count", "threshold", "failures", "evaluated_at", "cases"):
            assert key in data, f"Missing key '{key}' in EvalResult.to_dict()"

    def test_suite_passes_when_all_cases_pass(self) -> None:
        # Manufacture case results where everything passes
        case = self._passing_case()
        case_result = CaseResult(
            test_case=case,
            response="test_keyword found here",
            keyword_hit=True,
            no_forbidden=True,
            min_length_met=True,
            passed=True,
            matched_keyword="test_keyword",
            matched_forbidden=None,
            error=None,
        )
        result = EvalResult(
            overall_passed=True,
            pass_rate=1.0,
            total=1,
            passed_count=1,
            failed_count=0,
            threshold=0.80,
            case_results=[case_result],
            failures=[],
        )
        assert result.overall_passed is True
        assert result.pass_rate == 1.0

    def test_suite_fails_below_threshold(self) -> None:
        # 1 case passing out of 5 = 20%, below 80% threshold
        result = EvalResult(
            overall_passed=False,
            pass_rate=0.20,
            total=5,
            passed_count=1,
            failed_count=4,
            threshold=RELEASE_QUALITY_THRESHOLD,
            case_results=[],
            failures=["case 1 failed", "case 2 failed", "case 3 failed", "case 4 failed"],
        )
        assert result.overall_passed is False
        assert result.pass_rate < result.threshold
