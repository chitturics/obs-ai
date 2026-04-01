"""Tests for self-evaluation — confidence scoring and grounding."""

import pytest


@pytest.fixture
def evaluator():
    from chat_app.self_evaluation import SelfEvaluator
    return SelfEvaluator()


class TestConfidenceScoring:

    def test_high_confidence_with_good_retrieval(self, evaluator):
        result = evaluator.evaluate(
            query="How do I configure HEC in Splunk?",
            response="To configure HEC, navigate to Settings > Data Inputs > HTTP Event Collector. "
                     "Enable HEC and create a new token. Configure the source type and index.",
            retrieved_chunks=[
                "HTTP Event Collector (HEC) configuration: Go to Settings > Data Inputs > "
                "HTTP Event Collector. Click 'New Token' to create a token.",
                "HEC tokens can be configured with source type and index settings.",
            ],
            collection_names=["spl_docs", "configs"],
        )
        assert result.confidence > 0.5
        assert result.grounding in ("high", "medium")

    def test_low_confidence_no_retrieval(self, evaluator):
        result = evaluator.evaluate(
            query="What is the meaning of life?",
            response="The meaning of life is 42, according to Douglas Adams.",
            retrieved_chunks=[],
        )
        assert result.confidence < 0.5
        assert result.grounding == "ungrounded"
        assert any("no retrieval" in w.lower() for w in result.warnings)

    def test_medium_confidence_partial_match(self, evaluator):
        result = evaluator.evaluate(
            query="How do I restart Splunk?",
            response="You can restart Splunk using the CLI: splunk restart",
            retrieved_chunks=["Splunk CLI commands include start, stop, and restart."],
            collection_names=["spl_docs"],
        )
        assert 0.2 <= result.confidence <= 0.9

    def test_tool_failure_reduces_confidence(self, evaluator):
        result_success = evaluator.evaluate(
            query="Search for errors",
            response="Found 42 errors in the last hour.",
            tools_used=[{"name": "splunk_search", "success": True}],
        )
        result_failure = evaluator.evaluate(
            query="Search for errors",
            response="I couldn't complete the search.",
            tools_used=[{"name": "splunk_search", "success": False}],
        )
        assert result_success.tool_success_rate == 1.0
        assert result_failure.tool_success_rate == 0.0
        assert result_success.confidence > result_failure.confidence

    def test_multiple_tools_partial_failure(self, evaluator):
        result = evaluator.evaluate(
            query="Check health",
            response="Partial health check results...",
            tools_used=[
                {"name": "health_check", "success": True},
                {"name": "splunk_search", "success": False},
                {"name": "list_indexes", "success": True},
            ],
        )
        assert result.tool_success_rate == pytest.approx(0.667, abs=0.01)
        assert "1/3 tools failed" in result.warnings[0]


class TestGroundingLevels:

    def test_high_grounding(self, evaluator):
        # Many overlapping terms between query, response, and chunks
        result = evaluator.evaluate(
            query="configure splunk forwarder",
            response="To configure a Splunk forwarder, install the universal forwarder package "
                     "and configure outputs.conf with the receiving indexer address.",
            retrieved_chunks=[
                "Splunk Universal Forwarder configuration requires outputs.conf",
                "Configure the forwarder to send data to the indexer",
                "Universal forwarder installation and configuration guide",
            ],
            collection_names=["spl_docs", "configs", "guides"],
        )
        assert result.grounding in ("high", "medium")

    def test_ungrounded(self, evaluator):
        result = evaluator.evaluate(
            query="Tell me a joke",
            response="Why did the chicken cross the road?",
        )
        assert result.grounding == "ungrounded"


class TestWarnings:

    def test_short_response_warning(self, evaluator):
        result = evaluator.evaluate(
            query="How to configure HEC?",
            response="Yes.",
        )
        assert any("short response" in w.lower() for w in result.warnings)

    def test_uncertainty_warning(self, evaluator):
        result = evaluator.evaluate(
            query="What port does HEC use?",
            response="I'm not sure, but I think it might be port 8088.",
        )
        assert any("uncertainty" in w.lower() for w in result.warnings)


class TestSourceDiversity:

    def test_multiple_sources_increase_confidence(self, evaluator):
        single_source = evaluator.evaluate(
            query="splunk search",
            response="Use the search command to search for events.",
            retrieved_chunks=["search command documentation"],
            collection_names=["spl_docs"],
        )
        multi_source = evaluator.evaluate(
            query="splunk search",
            response="Use the search command to search for events.",
            retrieved_chunks=["search command documentation", "search examples", "search tutorial"],
            collection_names=["spl_docs", "configs", "tutorials"],
        )
        assert multi_source.source_diversity > single_source.source_diversity


class TestResultSerialization:

    def test_to_dict(self, evaluator):
        result = evaluator.evaluate(
            query="test", response="test response",
            retrieved_chunks=["test chunk"],
        )
        d = result.to_dict()
        assert "confidence" in d
        assert "confidence_pct" in d
        assert "grounding" in d
        assert "explanation" in d
        assert isinstance(d["confidence"], float)
        assert d["confidence_pct"].endswith("%")


class TestStats:

    def test_empty_stats(self, evaluator):
        stats = evaluator.get_stats()
        assert stats["total_evaluations"] == 0

    def test_stats_after_evaluations(self, evaluator):
        evaluator.evaluate("q1", "r1", ["chunk"])
        evaluator.evaluate("q2", "r2", [])
        evaluator.evaluate("q3", "r3", ["c1", "c2"])

        stats = evaluator.get_stats()
        assert stats["total_evaluations"] == 3
        assert 0 <= stats["avg_confidence"] <= 1
        assert "grounding_distribution" in stats


class TestTermExtraction:

    def test_extract_terms(self):
        from chat_app.self_evaluation import _extract_terms
        terms = _extract_terms("How do I configure the Splunk forwarder?")
        assert "configure" in terms
        assert "splunk" in terms
        assert "forwarder" in terms
        assert "how" not in terms  # stopword
        assert "the" not in terms  # stopword
