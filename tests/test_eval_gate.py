"""Sprint 5: Evaluation gate tests."""

import pytest


class TestEvalGate:

    def test_gate_passes_with_golden_cases(self):
        from chat_app.eval_gate import run_eval_gate
        result = run_eval_gate()
        assert result["passed"] is True
        assert result["golden_cases"] >= 10

    def test_gate_has_intent_coverage(self):
        from chat_app.eval_gate import run_eval_gate
        result = run_eval_gate()
        assert "general_qa" in result["intents_covered"]
        assert "spl_help" in result["intents_covered"]
        assert len(result["intents_covered"]) >= 3

    def test_golden_cases_have_descriptions(self):
        from chat_app.eval_gate import GOLDEN_CASES
        for case in GOLDEN_CASES:
            desc = getattr(case, 'description', None) or (case.get('description') if isinstance(case, dict) else None)
            assert desc, f"Case missing description: {getattr(case, 'query', '?')}"

    def test_thresholds_are_reasonable(self):
        from chat_app.eval_gate import EvalThresholds
        t = EvalThresholds()
        assert 0.5 <= t.min_grounding_score <= 1.0
        assert 0.0 < t.max_hallucination_rate <= 0.1
        assert t.min_test_cases >= 10
