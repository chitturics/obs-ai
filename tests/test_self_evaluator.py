"""
Comprehensive tests for chat_app.self_evaluator module.

Tests cover:
- QualityScore dataclass construction and defaults
- evaluate_response_quality() — main entry point with varied inputs
- _check_completeness() — query-term coverage and length bonus
- _check_grounding() — grounding against context chunks, hallucination risk
- _check_spl_in_response() — SPL code block detection and validation
- Edge cases: empty inputs, boundary lengths, score bounds, weighted formula
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chat_app.self_evaluator import (
    QualityScore,
    evaluate_response_quality,
    _check_completeness,
    _check_grounding,
    _check_spl_in_response,
)


# ---------------------------------------------------------------------------
# 1. QualityScore Dataclass Tests
# ---------------------------------------------------------------------------

class TestQualityScoreDataclass:
    """Test QualityScore dataclass construction and defaults."""

    def test_default_construction(self):
        """Default QualityScore should have zeroed scores and sensible defaults."""
        qs = QualityScore()
        assert qs.overall == 0.0
        assert qs.completeness == 0.0
        assert qs.grounding == 0.0
        assert qs.hallucination_risk == 0.0
        assert qs.spl_validity == 1.0
        assert qs.gaps == []
        assert qs.recommended_action == "send"

    def test_custom_construction(self):
        """QualityScore should accept custom values for all fields."""
        qs = QualityScore(
            overall=0.85,
            completeness=0.9,
            grounding=0.8,
            hallucination_risk=0.1,
            spl_validity=0.95,
            gaps=["minor gap"],
            recommended_action="refine",
        )
        assert qs.overall == 0.85
        assert qs.gaps == ["minor gap"]
        assert qs.recommended_action == "refine"

    def test_gaps_list_is_independent(self):
        """Each QualityScore instance should have its own gaps list."""
        qs1 = QualityScore()
        qs2 = QualityScore()
        qs1.gaps.append("gap from qs1")
        assert qs2.gaps == []
        assert len(qs1.gaps) == 1


# ---------------------------------------------------------------------------
# 2. evaluate_response_quality — Empty / Short Response Tests
# ---------------------------------------------------------------------------

class TestEvaluateEmptyShortResponse:
    """Empty or very short responses should short-circuit to overall=0.1."""

    def test_empty_response(self):
        """Empty string should yield overall=0.1 and 'refine' action."""
        result = evaluate_response_quality(
            response="",
            user_query="How do I search for failed logins?",
            context="Use index=wineventlog EventCode=4625 to find failed logins.",
        )
        assert result.overall == 0.1
        assert result.recommended_action == "refine"
        assert any("too short" in g.lower() or "empty" in g.lower() for g in result.gaps)

    def test_none_response(self):
        """None response should be handled the same as empty."""
        result = evaluate_response_quality(
            response=None,
            user_query="What is tstats?",
            context="tstats is a fast aggregation command.",
        )
        assert result.overall == 0.1
        assert result.recommended_action == "refine"

    def test_whitespace_only_response(self):
        """Whitespace-only response should be treated as too short after strip()."""
        result = evaluate_response_quality(
            response="       \n\n\t   ",
            user_query="Show me a query for errors",
            context="index=main level=ERROR",
        )
        assert result.overall == 0.1
        assert result.recommended_action == "refine"

    def test_i_dont_know_response(self):
        """A minimal 'I don't know.' response is under 20 chars and should score low."""
        result = evaluate_response_quality(
            response="I don't know.",
            user_query="How does the stats command work in Splunk?",
            context="The stats command aggregates data by fields.",
        )
        assert result.overall == 0.1
        assert result.recommended_action == "refine"

    def test_exactly_20_chars_passes_short_circuit(self):
        """A response with exactly 20 chars (after strip) should NOT hit the short-circuit."""
        response = "A" * 20  # exactly 20 chars
        result = evaluate_response_quality(
            response=response,
            user_query="test query with terms",
            context="Some context about terms and testing.",
        )
        assert result.overall != 0.1


# ---------------------------------------------------------------------------
# 3. evaluate_response_quality — Good / Grounded Responses
# ---------------------------------------------------------------------------

class TestEvaluateGoodResponses:
    """High-quality, context-grounded responses should score > 0.7 and recommend 'send'."""

    def test_high_quality_grounded_response(self):
        """Long response grounded in context with matching terms should score high."""
        context = (
            "The `stats` command aggregates data by fields. "
            "It supports functions like count, sum, avg, and values. "
            "Syntax: | stats count by host. "
            "It is one of the most commonly used Splunk commands."
        )
        response = (
            "The `stats` command aggregates data by fields. "
            "Example: `| stats count by host` counts events per host. "
            "It supports functions like count, sum, avg, and values. "
            "This is one of the most commonly used Splunk commands for data analysis."
        )
        result = evaluate_response_quality(
            response=response,
            user_query="How does the stats command aggregate data by fields?",
            context=context,
            chunks_found=5,
        )
        assert result.overall > 0.7
        assert result.recommended_action == "send"
        assert result.grounding > 0.5
        assert result.completeness > 0.5

    def test_response_with_valid_spl_scores_well(self):
        """Response containing valid SPL in a code block should have spl_validity=1.0."""
        context = (
            "Use index=main sourcetype=access_combined to search web access logs. "
            "You can use stats count by status to aggregate HTTP status codes."
        )
        response = (
            "You can use this query:\n"
            "```spl\n"
            "index=main sourcetype=access_combined | stats count by status\n"
            "```\n"
            "This searches the main index for access_combined events and "
            "counts them by HTTP status code."
        )
        result = evaluate_response_quality(
            response=response,
            user_query="How do I search for web access logs?",
            context=context,
            chunks_found=3,
        )
        assert result.spl_validity == 1.0
        assert result.overall >= 0.5

    def test_many_chunks_reduce_hallucination_risk(self):
        """More chunks_found should reduce hallucination risk for the same response."""
        context = "Splunk uses indexes to store data. The default index is 'main'."
        response = (
            "Splunk organizes data into indexes for efficient storage and retrieval. "
            "The default index is called 'main' and is used when no specific index is specified."
        )
        result_few = evaluate_response_quality(
            response=response,
            user_query="What are Splunk indexes?",
            context=context,
            chunks_found=1,
        )
        result_many = evaluate_response_quality(
            response=response,
            user_query="What are Splunk indexes?",
            context=context,
            chunks_found=10,
        )
        assert result_many.hallucination_risk <= result_few.hallucination_risk


# ---------------------------------------------------------------------------
# 4. evaluate_response_quality — Medium / Vague Responses
# ---------------------------------------------------------------------------

class TestEvaluateMediumResponses:
    """Mediocre or vague responses should have reduced completeness or grounding."""

    def test_vague_response_missing_key_terms(self):
        """A response that misses key query terms should have lower completeness."""
        context = "The eval command calculates expressions and assigns results to fields."
        response = (
            "You can use various commands in Splunk to process your data. "
            "There are many options available depending on your specific needs. "
            "I recommend checking the documentation for more details about this topic."
        )
        result = evaluate_response_quality(
            response=response,
            user_query="How do I use the eval command to calculate field values?",
            context=context,
            chunks_found=2,
        )
        assert result.completeness < 0.8

    def test_response_unrelated_to_context_has_low_grounding(self):
        """Response completely unrelated to context should have low grounding."""
        context = "The stats command aggregates results using statistical functions."
        response = (
            "Docker containers provide isolated environments for running applications. "
            "You can use docker-compose to orchestrate multiple containers together. "
            "Kubernetes offers container orchestration at scale for production workloads."
        )
        result = evaluate_response_quality(
            response=response,
            user_query="How do I use the stats command?",
            context=context,
            chunks_found=3,
        )
        assert result.grounding < 0.5


# ---------------------------------------------------------------------------
# 5. evaluate_response_quality — Hallucination Risk
# ---------------------------------------------------------------------------

class TestEvaluateHallucinationRisk:
    """Hallucination risk under different grounding/context scenarios."""

    def test_no_context_high_hallucination_risk(self):
        """Empty context should flag hallucination risk, but allow substantive answers."""
        response = (
            "The best practice is to use tstats for indexed data aggregation. "
            "This provides better performance than regular stats commands."
        )
        result = evaluate_response_quality(
            response=response,
            user_query="What is the best practice for aggregation?",
            context="",
            chunks_found=0,
        )
        # Substantive responses (>100 chars) get relaxed grounding
        assert result.hallucination_risk >= 0.3
        assert result.grounding <= 0.6

    def test_no_context_marker_string(self):
        """The sentinel 'No specific context available.' allows general knowledge."""
        response = (
            "Splunk is a powerful platform for searching, monitoring, and analyzing "
            "machine-generated data. It provides a web interface for data exploration."
        )
        result = evaluate_response_quality(
            response=response,
            user_query="What is Splunk?",
            context="No specific context available.",
            chunks_found=0,
        )
        # General knowledge questions should pass through
        assert result.hallucination_risk >= 0.3
        assert result.grounding <= 0.6

    def test_zero_chunks_vs_many_chunks_risk_comparison(self):
        """Zero chunks_found should have >= hallucination risk vs. many chunks."""
        context = "Some minimal context about Splunk searches."
        response = (
            "You should configure your Splunk instance with the appropriate settings "
            "to ensure optimal search performance and data retention policies."
        )
        r0 = evaluate_response_quality(
            response=response,
            user_query="How to configure Splunk searches?",
            context=context,
            chunks_found=0,
        )
        r5 = evaluate_response_quality(
            response=response,
            user_query="How to configure Splunk searches?",
            context=context,
            chunks_found=5,
        )
        assert r0.hallucination_risk >= r5.hallucination_risk


# ---------------------------------------------------------------------------
# 6. evaluate_response_quality — Recommended Action Logic
# ---------------------------------------------------------------------------

class TestRecommendedAction:
    """Test the recommended_action decision boundaries."""

    def test_high_score_sends(self):
        """Overall >= 0.6 should recommend 'send'."""
        context = (
            "The dedup command removes duplicate events based on specified fields. "
            "Syntax: | dedup field1 field2. It keeps the first event for each combination."
        )
        response = (
            "The dedup command removes duplicate events from your search results based on "
            "the specified fields. The syntax is: | dedup field1 field2. It keeps only the "
            "first event encountered for each unique combination of the specified fields."
        )
        result = evaluate_response_quality(
            response=response,
            user_query="How does the dedup command work?",
            context=context,
            chunks_found=5,
        )
        assert result.recommended_action == "send"

    def test_empty_response_refines(self):
        """Short-circuit path always recommends 'refine'."""
        result = evaluate_response_quality(
            response="",
            user_query="What is Splunk?",
            context="Splunk is a platform.",
        )
        assert result.recommended_action == "refine"

    def test_very_low_unrelated_response_refines_or_abstains(self):
        """Completely off-topic response with no context should refine, abstain, or clarify."""
        response = (
            "Quantum computing leverages quantum mechanical phenomena. "
            "Superposition allows qubits to exist in multiple states simultaneously. "
            "Entanglement creates correlations between distant quantum particles."
        )
        result = evaluate_response_quality(
            response=response,
            user_query="How to configure props.conf transform lookups in Splunk?",
            context="",
            chunks_found=0,
        )
        # Off-topic response should not be sent as-is
        assert result.recommended_action in ("refine", "abstain", "clarify")


# ---------------------------------------------------------------------------
# 7. _check_completeness — Direct Tests
# ---------------------------------------------------------------------------

class TestCheckCompleteness:
    """Test _check_completeness helper directly."""

    def test_full_coverage_scores_high(self):
        """All key terms present should yield high completeness."""
        score = _check_completeness(
            response="The stats command aggregates results using count, sum, and avg functions.",
            user_query="How does the stats command aggregate results?",
        )
        assert score >= 0.7

    def test_zero_coverage_scores_low(self):
        """No key terms from query in response should yield low completeness."""
        score = _check_completeness(
            response="Docker containers provide isolated environments.",
            user_query="How does tstats differ from stats in Splunk?",
        )
        assert score < 0.5

    def test_only_stopwords_returns_default(self):
        """Query containing only stopwords should return 0.7 (cannot evaluate)."""
        score = _check_completeness(
            response="Something about data.",
            user_query="how can you help with this?",
        )
        assert score == 0.7

    def test_longer_response_gets_length_bonus(self):
        """A longer response should receive a small length bonus over a short one."""
        query = "How does the eval command work?"
        short_resp = "The eval command calculates expressions."
        long_resp = (
            "The eval command calculates expressions and assigns results to fields. "
            "It supports mathematical operations, string functions, and conditional logic. "
            "Common use cases include creating new calculated fields and converting types. "
        ) * 5
        short_score = _check_completeness(short_resp, query)
        long_score = _check_completeness(long_resp, query)
        assert long_score >= short_score

    def test_partial_coverage_is_intermediate(self):
        """Partial term overlap should give a score between 0 and 1."""
        score = _check_completeness(
            response="The stats command is useful for counting events.",
            user_query="How do I use stats to aggregate field values and create timecharts?",
        )
        assert 0.1 <= score <= 0.9


# ---------------------------------------------------------------------------
# 8. _check_grounding — Direct Tests
# ---------------------------------------------------------------------------

class TestCheckGrounding:
    """Test _check_grounding helper directly."""

    def test_well_grounded_response(self):
        """Response closely matching context should have high grounding, low risk."""
        context = (
            "The lookup command enriches events with fields from an external table. "
            "Use inputlookup to load a lookup table directly."
        )
        response = (
            "The lookup command enriches events with fields from an external table. "
            "You can also use inputlookup to load a lookup table directly for viewing."
        )
        grounding, risk = _check_grounding(response, context, chunks_found=5)
        assert grounding >= 0.5
        assert risk < 0.5

    def test_empty_context_returns_low_grounding_high_risk(self):
        """Empty context should return grounding=0.3, risk=0.7."""
        grounding, risk = _check_grounding(
            "Some response about Splunk.", "", chunks_found=0
        )
        # Short response (<100 chars) still gets strict grounding
        assert grounding == 0.3
        assert risk == 0.7

    def test_no_context_marker_returns_low_grounding_high_risk(self):
        """The sentinel marker 'No specific context available.' with short response."""
        grounding, risk = _check_grounding(
            "Some response.", "No specific context available.", chunks_found=3
        )
        # Short response (<100 chars) still gets strict grounding
        assert grounding == 0.3
        assert risk == 0.7

    def test_ungrounded_response_has_low_grounding(self):
        """Response with no term overlap to context should have low grounding."""
        context = "The tstats command provides fast aggregation over indexed fields."
        response = (
            "Docker containers provide isolated execution environments. "
            "Kubernetes orchestrates containers across multiple cluster nodes."
        )
        grounding, risk = _check_grounding(response, context, chunks_found=0)
        assert grounding < 0.5

    def test_more_chunks_reduce_risk_monotonically(self):
        """Higher chunks_found should monotonically reduce hallucination risk."""
        context = "Some context about Splunk searches and data processing."
        response = (
            "Splunk provides powerful search capabilities for processing and analyzing data."
        )
        _, risk_zero = _check_grounding(response, context, chunks_found=0)
        _, risk_five = _check_grounding(response, context, chunks_found=5)
        _, risk_ten = _check_grounding(response, context, chunks_found=10)
        assert risk_ten <= risk_five <= risk_zero

    def test_short_sentences_fallback(self):
        """If no sentence is > 20 chars, returns grounding=0.5, risk=0.4."""
        grounding, risk = _check_grounding(
            "Short. Tiny. Yes.", "Some context about things.", chunks_found=2
        )
        assert grounding == 0.5
        assert risk == 0.4


# ---------------------------------------------------------------------------
# 9. _check_spl_in_response — Direct Tests
# ---------------------------------------------------------------------------

class TestCheckSPLInResponse:
    """Test _check_spl_in_response helper directly."""

    def test_no_spl_blocks_returns_one(self):
        """No code blocks at all should return 1.0 (nothing to invalidate)."""
        score = _check_spl_in_response("This is a plain text response with no code.")
        assert score == 1.0

    def test_valid_spl_with_index(self):
        """SPL block with index= structure should be valid."""
        response = "```spl\nindex=main sourcetype=syslog | stats count by host\n```"
        score = _check_spl_in_response(response)
        assert score == 1.0

    def test_valid_spl_with_leading_pipe(self):
        """SPL block starting with a pipe command should be valid."""
        response = "```\n| makeresults count=10 | eval x=random()\n```"
        score = _check_spl_in_response(response)
        assert score == 1.0

    def test_realistic_spl_block(self):
        """Realistic response with SPL block should score 1.0."""
        response = (
            "You can use this query:\n"
            "```spl\n"
            "index=main | stats count by host\n"
            "```"
        )
        score = _check_spl_in_response(response)
        assert score == 1.0

    def test_invalid_spl_broken_pipes(self):
        """SPL block with '| |' (consecutive pipes) should be invalid."""
        response = "```spl\nindex=main | | stats count\n```"
        score = _check_spl_in_response(response)
        assert score == 0.0

    def test_invalid_spl_trailing_pipe(self):
        """SPL block ending with a trailing pipe should be invalid."""
        response = "```spl\nindex=main | stats count |\n```"
        score = _check_spl_in_response(response)
        assert score == 0.0

    def test_invalid_spl_no_structure(self):
        """SPL block with no recognizable SPL structure should be invalid."""
        response = "```spl\njust some random words here\n```"
        score = _check_spl_in_response(response)
        assert score == 0.0

    def test_multiple_valid_blocks(self):
        """Multiple valid SPL blocks should yield 1.0."""
        response = (
            "```spl\nindex=main | stats count by host\n```\n\n"
            "```spl\nindex=security | where status=\"failed\" | table user, src_ip\n```"
        )
        score = _check_spl_in_response(response)
        assert score == 1.0

    def test_mixed_valid_and_invalid_blocks(self):
        """One valid + one invalid block should yield 0.5."""
        response = (
            "```spl\nindex=main | stats count\n```\n\n"
            "```spl\nbroken nonsense text\n```"
        )
        score = _check_spl_in_response(response)
        assert score == 0.5


# ---------------------------------------------------------------------------
# 10. Edge Cases and Score Boundaries
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases, boundary conditions, and formula verification."""

    def test_empty_query_does_not_crash(self):
        """Empty user query should not cause errors."""
        result = evaluate_response_quality(
            response="This is a valid response with enough length to pass the short check.",
            user_query="",
            context="Some context.",
            chunks_found=1,
        )
        assert isinstance(result, QualityScore)
        assert 0.0 <= result.overall <= 1.0

    def test_very_long_response_handled(self):
        """Very long response should be processed without errors."""
        long_response = (
            "The Splunk platform provides comprehensive data analytics capabilities. "
            "It ingests machine data from various sources including logs and metrics. "
        ) * 100
        context = "Splunk is a data analytics platform for machine data."
        result = evaluate_response_quality(
            response=long_response,
            user_query="What does Splunk do?",
            context=context,
            chunks_found=5,
        )
        assert isinstance(result, QualityScore)
        assert 0.0 <= result.overall <= 1.0

    def test_overall_score_always_bounded_zero_to_one(self):
        """Overall score should always be between 0.0 and 1.0 for various inputs."""
        cases = [
            ("A" * 25, "test query words here", "test context with query words here", 0),
            ("A" * 25, "test query words here", "test context with query words here", 10),
            ("A" * 25, "test", "", 0),
            (
                "Full detailed response covering all aspects of Splunk configuration and deployment.",
                "How to configure Splunk?",
                "Splunk configuration involves editing conf files for deployment.",
                5,
            ),
        ]
        for resp, query, ctx, chunks in cases:
            result = evaluate_response_quality(resp, query, ctx, chunks)
            assert 0.0 <= result.overall <= 1.0, (
                f"Overall {result.overall} out of bounds for response='{resp[:30]}...'"
            )

    def test_overall_score_matches_weighted_formula(self):
        """Verify overall = 0.30*completeness + 0.35*grounding + 0.20*(1-risk) + 0.15*spl."""
        context = (
            "The rename command renames fields in your search results. "
            "Syntax: | rename old_field AS new_field."
        )
        response = (
            "The rename command renames fields in your search results. "
            "Use the syntax: | rename old_field AS new_field to change field names."
        )
        result = evaluate_response_quality(
            response=response,
            user_query="How do I rename fields in Splunk?",
            context=context,
            chunks_found=3,
        )
        expected = (
            result.completeness * 0.30
            + result.grounding * 0.35
            + (1 - result.hallucination_risk) * 0.20
            + result.spl_validity * 0.15
        )
        assert abs(result.overall - expected) < 1e-9

    def test_spl_detected_in_response_with_spl_block(self):
        """Responses with SPL blocks should have them detected (spl_validity != 1.0 default
        only when the block is present and invalid, or == 1.0 when valid)."""
        response_valid = (
            "You can use this query:\n"
            "```spl\n"
            "index=main | stats count by host\n"
            "```"
        )
        response_invalid = (
            "Try this:\n"
            "```spl\n"
            "not valid spl at all\n"
            "```"
        )
        result_valid = evaluate_response_quality(
            response=response_valid,
            user_query="Give me a query",
            context="index=main | stats count by host is commonly used.",
            chunks_found=2,
        )
        result_invalid = evaluate_response_quality(
            response=response_invalid,
            user_query="Give me a query",
            context="index=main is a common search.",
            chunks_found=1,
        )
        assert result_valid.spl_validity == 1.0
        assert result_invalid.spl_validity < 1.0

    def test_hallucination_markers_lower_grounding_score(self):
        """An off-topic response against good context should have low grounding,
        effectively acting as a hallucination marker."""
        context = (
            "The `stats` command aggregates data by fields. "
            "Example: `| stats count by host` counts events per host. "
            "It supports count, sum, avg, min, max, and values functions."
        )
        # Completely unrelated hallucinated content
        hallucinated_response = (
            "Machine learning pipelines orchestrate model training workflows. "
            "Feature engineering transforms raw data into numerical representations. "
            "Hyperparameter tuning optimizes algorithm performance across validation sets."
        )
        result = evaluate_response_quality(
            response=hallucinated_response,
            user_query="How does the stats command work?",
            context=context,
            chunks_found=5,
        )
        assert result.grounding < 0.5
        assert result.completeness < 0.5
