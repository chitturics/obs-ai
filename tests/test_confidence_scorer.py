"""
Tests for chat_app.confidence_scorer module.

Covers:
- ScoredConfidence dataclass construction and defaults
- score_confidence with various input combinations
- format_confidence_for_context output formatting
- format_confidence_for_user output formatting
"""

import pytest

from chat_app.confidence_scorer import (
    ScoredConfidence,
    format_confidence_for_context,
    format_confidence_for_user,
    score_confidence,
)


# ---------------------------------------------------------------------------
# Helpers to build test data
# ---------------------------------------------------------------------------

def _make_chunk(collection="default", text="some text"):
    """Build a minimal chunk dict matching expected schema."""
    return {"collection": collection, "text": text}


def _make_chunks(n, collection="default"):
    """Build a list of n identical chunks."""
    return [_make_chunk(collection=collection) for _ in range(n)]


# ---------------------------------------------------------------------------
# 1. ScoredConfidence dataclass
# ---------------------------------------------------------------------------

class TestScoredConfidenceDataclass:
    """Verify default values and custom construction."""

    def test_defaults(self):
        sc = ScoredConfidence()
        assert sc.score == 0.5
        assert sc.label == "MEDIUM"
        assert sc.reasoning == ""
        assert sc.sources_used == []
        assert sc.knowledge_gaps == []
        assert sc.should_clarify is False
        assert sc.clarification_question is None

    def test_custom_construction(self):
        sc = ScoredConfidence(
            score=0.9,
            label="HIGH",
            reasoning="strong evidence",
            sources_used=["spec", "org_repo"],
            knowledge_gaps=["Cloud platform integration"],
            should_clarify=True,
            clarification_question="Which cloud?",
        )
        assert sc.score == 0.9
        assert sc.label == "HIGH"
        assert sc.reasoning == "strong evidence"
        assert sc.sources_used == ["spec", "org_repo"]
        assert sc.knowledge_gaps == ["Cloud platform integration"]
        assert sc.should_clarify is True
        assert sc.clarification_question == "Which cloud?"

    def test_mutable_defaults_are_independent(self):
        """Each instance should have its own lists."""
        a = ScoredConfidence()
        b = ScoredConfidence()
        a.sources_used.append("x")
        assert "x" not in b.sources_used


# ---------------------------------------------------------------------------
# 2. score_confidence
# ---------------------------------------------------------------------------

class TestScoreConfidenceHigh:
    """High-confidence scenarios (score >= 0.7, label == HIGH)."""

    def test_many_chunks_spec_content_and_feedback(self):
        """8+ chunks, 2 spec stanzas, high-similarity feedback, detailed query."""
        chunks = _make_chunks(10, collection="org_repo_spec")
        specs = ["stanza_a", "stanza_b"]
        query = "How do I configure the inputs.conf stanza for monitoring the var log syslog file on a heavy forwarder"
        feedback = {"similarity": 0.95}

        result = score_confidence(specs, chunks, query, feedback_match=feedback)

        assert result.label == "HIGH"
        assert result.score >= 0.7
        assert len(result.sources_used) >= 1
        assert "authoritative spec stanzas" in result.reasoning

    def test_many_diverse_chunks_with_org_repo(self):
        """Diverse collections push source_score higher."""
        chunks = (
            _make_chunks(4, collection="org_repo_data")
            + _make_chunks(4, collection="spec_files")
            + _make_chunks(2, collection="feedback_store")
        )
        specs = ["s1", "s2"]
        # 15+ words to get the specificity bonus
        query = "Explain the default stanza settings for inputs.conf on universal forwarders in our organization environment setup"

        result = score_confidence(specs, chunks, query)

        assert result.label == "HIGH"
        assert result.score >= 0.7


class TestScoreConfidenceLow:
    """Low / very-low confidence scenarios."""

    def test_no_chunks_no_specs(self):
        """Zero chunks and zero specs should score very low."""
        result = score_confidence([], [], "error")

        assert result.label == "VERY_LOW"
        assert result.score < 0.25
        assert "No relevant chunks found" in result.reasoning
        assert "No matching documents in knowledge base" in result.knowledge_gaps

    def test_no_chunks_short_query_triggers_clarification(self):
        """Should set should_clarify and generate a clarification question."""
        result = score_confidence([], [], "help me")

        assert result.should_clarify is True
        assert result.clarification_question is not None
        assert len(result.clarification_question) > 0

    def test_single_chunk_short_query(self):
        """One chunk and a vague query should be LOW."""
        result = score_confidence([], [_make_chunk()], "spl query")

        assert result.label in ("LOW", "VERY_LOW")
        assert result.score < 0.45


class TestScoreConfidenceMedium:
    """Medium confidence: moderate chunks, partial specs."""

    def test_moderate_chunks_multiple_collections(self):
        """4-7 chunks across several collections gives MEDIUM."""
        chunks = (
            _make_chunks(2, collection="org_repo_main")
            + _make_chunks(2, collection="spec_docs")
            + _make_chunks(2, collection="general")
        )
        result = score_confidence(["one_spec"], chunks, "How does the dedup command work in SPL")

        # chunk_score=0.20, source_score=3*0.04+0.05+0.05=0.22, spec_score=0.10 => 0.52
        assert result.label == "MEDIUM"
        assert 0.45 <= result.score < 0.7

    def test_few_chunks_plus_specs_and_collections(self):
        """A handful of chunks from multiple sources + specs can reach HIGH."""
        chunks = (
            _make_chunks(2, collection="org_repo_data")
            + _make_chunks(3, collection="spec_files")
        )
        result = score_confidence(["s1", "s2"], chunks, "What are the defaults for transforms.conf in our setup")

        # chunk_score=0.30 (5 chunks), source_score=min(0.10,2*0.05)+0.05+0.05=0.20, spec_score=0.20 => 0.70
        assert result.label == "HIGH"
        assert result.score >= 0.7


class TestScoreConfidenceFeedbackBoost:
    """Feedback match should boost the score."""

    def test_feedback_match_increases_score(self):
        chunks = _make_chunks(4)
        query = "How do I configure props.conf for timestamp extraction"
        without_fb = score_confidence([], chunks, query)
        with_fb = score_confidence([], chunks, query, feedback_match={"similarity": 0.90})

        assert with_fb.score > without_fb.score
        assert "Validated answer match" in with_fb.reasoning

    def test_feedback_match_zero_similarity_no_boost(self):
        chunks = _make_chunks(4)
        query = "How do I configure props.conf for timestamp extraction"
        result = score_confidence([], chunks, query, feedback_match={"similarity": 0.0})

        # similarity=0 means feedback_score = 0.0, so no boost
        no_fb = score_confidence([], chunks, query)
        assert result.score == pytest.approx(no_fb.score, abs=0.01)


class TestScoreConfidenceQuerySpecificity:
    """Short queries get a penalty; long queries get a bonus."""

    def test_short_query_penalty(self):
        chunks = _make_chunks(5)
        short_result = score_confidence([], chunks, "spl help")
        long_result = score_confidence(
            [], chunks,
            "How do I write a search query that deduplicates events by host and source in Splunk SPL"
        )
        assert long_result.score > short_result.score

    def test_very_short_query_triggers_penalty_text(self):
        result = score_confidence([], _make_chunks(2), "hi")
        assert "Query is very short/vague" in result.reasoning

    def test_long_query_triggers_bonus_text(self):
        long_q = "Can you show me how to write a stats command grouped by host and source that counts distinct values of user field"
        result = score_confidence([], _make_chunks(2), long_q)
        assert "Detailed query helps accuracy" in result.reasoning


class TestScoreConfidenceKnowledgeGaps:
    """Knowledge gap detection for specific product topics."""

    def test_cribl_gap_detected(self):
        result = score_confidence([], _make_chunks(2), "How do I configure Cribl Stream")
        assert any("Cribl" in gap for gap in result.knowledge_gaps)

    def test_soar_gap_detected(self):
        result = score_confidence([], _make_chunks(2), "Run a Phantom playbook in SOAR")
        assert any("SOAR" in gap or "Phantom" in gap for gap in result.knowledge_gaps)

    def test_no_gap_when_topic_in_chunks(self):
        """If the chunk text already covers the topic, no gap is added for it."""
        chunks = [_make_chunk(text="Cribl Stream configuration guide")]
        result = score_confidence([], chunks, "How to set up Cribl Stream")
        cribl_gaps = [g for g in result.knowledge_gaps if "Cribl" in g]
        assert cribl_gaps == []


class TestScoreConfidenceSourceDiversity:
    """Collections and authority flags affect the source score."""

    def test_org_repo_collection_noted(self):
        chunks = _make_chunks(4, collection="org_repo_main")
        result = score_confidence([], chunks, "Show me our org config for outputs.conf")
        assert "Organization configs available" in result.reasoning

    def test_spec_collection_noted(self):
        chunks = _make_chunks(4, collection="spec_docs")
        result = score_confidence([], chunks, "What fields does spec define for inputs.conf")
        assert "Official spec files matched" in result.reasoning

    def test_feedback_collection_noted(self):
        chunks = _make_chunks(4, collection="feedback_store")
        result = score_confidence([], chunks, "Previously answered question about props")
        assert "Similar feedback Q&A found" in result.reasoning


class TestScoreConfidenceEdgeCases:
    """Edge-case and boundary behaviour."""

    def test_score_clamped_to_zero(self):
        """Score cannot drop below 0.0."""
        result = score_confidence([], [], "hi")
        assert result.score >= 0.0

    def test_score_clamped_to_one(self):
        """Score cannot exceed 1.0 even with extreme inputs."""
        chunks = _make_chunks(20, collection="org_repo_spec_feedback_secondary")
        specs = [f"s{i}" for i in range(20)]
        fb = {"similarity": 1.0}
        query = " ".join(["detailed"] * 20)
        result = score_confidence(specs, chunks, query, feedback_match=fb)
        assert result.score <= 1.0


# ---------------------------------------------------------------------------
# 3. format_confidence_for_context
# ---------------------------------------------------------------------------

class TestFormatConfidenceForContext:

    def test_contains_label_and_score(self):
        sc = ScoredConfidence(score=0.72, label="HIGH", reasoning="good data")
        text = format_confidence_for_context(sc)
        assert "[CONFIDENCE: HIGH (0.72)]" in text
        assert "Basis: good data" in text

    def test_includes_knowledge_gaps(self):
        sc = ScoredConfidence(
            score=0.3, label="LOW",
            reasoning="sparse",
            knowledge_gaps=["Missing ITSI docs", "Missing SOAR docs"],
        )
        text = format_confidence_for_context(sc)
        assert "Gaps:" in text
        assert "Missing ITSI docs" in text

    def test_low_label_includes_instruction(self):
        sc = ScoredConfidence(score=0.2, label="LOW")
        text = format_confidence_for_context(sc)
        assert "INSTRUCTION" in text
        assert "LIMITED context" in text

    def test_very_low_label_includes_instruction(self):
        sc = ScoredConfidence(score=0.1, label="VERY_LOW")
        text = format_confidence_for_context(sc)
        assert "CRITICAL INSTRUCTION" in text
        assert "MUST respond" in text

    def test_high_label_no_instruction(self):
        sc = ScoredConfidence(score=0.8, label="HIGH", reasoning="solid")
        text = format_confidence_for_context(sc)
        assert "INSTRUCTION" not in text

    def test_medium_label_includes_note(self):
        sc = ScoredConfidence(score=0.5, label="MEDIUM")
        text = format_confidence_for_context(sc)
        assert "Only answer based on" in text

    def test_medium_label_no_instruction(self):
        sc = ScoredConfidence(score=0.5, label="MEDIUM", reasoning="ok")
        text = format_confidence_for_context(sc)
        assert "INSTRUCTION" not in text


# ---------------------------------------------------------------------------
# 4. format_confidence_for_user
# ---------------------------------------------------------------------------

class TestFormatConfidenceForUser:

    def test_high_label_formatting(self):
        sc = ScoredConfidence(label="HIGH", sources_used=["spec_docs"])
        text = format_confidence_for_user(sc)
        assert "**Confidence:** HIGH" in text
        assert "Sources: spec_docs" in text

    def test_very_low_label_formatting(self):
        sc = ScoredConfidence(label="VERY_LOW")
        text = format_confidence_for_user(sc)
        assert "VERY LOW" in text

    def test_no_sources_omits_sources_section(self):
        sc = ScoredConfidence(label="MEDIUM", sources_used=[])
        text = format_confidence_for_user(sc)
        assert "Sources" not in text

    def test_sources_limited_to_four(self):
        sc = ScoredConfidence(
            label="HIGH",
            sources_used=["src_alpha", "src_beta", "src_gamma", "src_delta", "src_epsilon", "src_zeta"],
        )
        text = format_confidence_for_user(sc)
        # Only first 4 should appear
        assert "src_alpha, src_beta, src_gamma, src_delta" in text
        assert "src_epsilon" not in text
        assert "src_zeta" not in text

    def test_unknown_label_falls_through(self):
        sc = ScoredConfidence(label="CUSTOM")
        text = format_confidence_for_user(sc)
        assert "**Confidence:** CUSTOM" in text
