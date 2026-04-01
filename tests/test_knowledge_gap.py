"""Tests for chat_app.knowledge_gap_detector module."""

import pytest

from chat_app.knowledge_gap_detector import (
    KnowledgeGap,
    detect_knowledge_gaps,
    format_gap_suggestions,
    should_suggest_ingestion,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk(text: str, metadata: dict | None = None) -> dict:
    """Build a chunk dict matching the shape expected by detect_knowledge_gaps."""
    return {"text": text, "metadata": metadata or {}}


def _make_chunks(texts: list[str]) -> list[dict]:
    return [_chunk(t) for t in texts]


# ===========================================================================
# 1. KnowledgeGap dataclass construction
# ===========================================================================


class TestKnowledgeGapDataclass:

    def test_basic_construction(self):
        gap = KnowledgeGap(
            topic="ITSI",
            gap_type="missing_entirely",
            severity="high",
        )
        assert gap.topic == "ITSI"
        assert gap.gap_type == "missing_entirely"
        assert gap.severity == "high"
        assert gap.suggestion == ""
        assert gap.ingest_url is None

    def test_construction_with_all_fields(self):
        gap = KnowledgeGap(
            topic="UBA",
            gap_type="sparse",
            severity="medium",
            suggestion="Add UBA docs",
            ingest_url="https://docs.splunk.com/Documentation/UBA",
        )
        assert gap.topic == "UBA"
        assert gap.gap_type == "sparse"
        assert gap.severity == "medium"
        assert gap.suggestion == "Add UBA docs"
        assert gap.ingest_url == "https://docs.splunk.com/Documentation/UBA"

    def test_defaults(self):
        gap = KnowledgeGap(topic="x", gap_type="y", severity="z")
        assert gap.suggestion == ""
        assert gap.ingest_url is None


# ===========================================================================
# 2. detect_knowledge_gaps
# ===========================================================================


class TestDetectKnowledgeGaps:

    # -- Splunk product references with no matching chunks --

    def test_itsi_product_no_chunks(self):
        gaps = detect_knowledge_gaps("How do I configure ITSI?", [])
        topics = [g.topic for g in gaps]
        assert "ITSI" in topics
        itsi = next(g for g in gaps if g.topic == "ITSI")
        assert itsi.gap_type == "missing_entirely"
        assert itsi.severity == "high"
        assert itsi.ingest_url == "https://docs.splunk.com/Documentation/ITSI"

    def test_soar_product_no_chunks(self):
        gaps = detect_knowledge_gaps("Run a SOAR playbook for this alert", [])
        topics = [g.topic for g in gaps]
        assert "SOAR/Phantom" in topics

    def test_enterprise_security_no_chunks(self):
        gaps = detect_knowledge_gaps("Show me notable events in Enterprise Security", [])
        topics = [g.topic for g in gaps]
        assert "Enterprise Security" in topics

    def test_uba_product_no_chunks(self):
        gaps = detect_knowledge_gaps("What is UBA anomaly scoring?", [])
        topics = [g.topic for g in gaps]
        assert "UBA" in topics

    def test_observability_cloud_no_chunks(self):
        gaps = detect_knowledge_gaps("How to send data to SignalFx?", [])
        topics = [g.topic for g in gaps]
        assert "Observability Cloud" in topics

    def test_product_query_with_matching_chunks_no_gap(self):
        """When the chunks already contain the product keyword, no gap is flagged."""
        chunks = _make_chunks([
            "ITSI service health scores are computed every 5 minutes.",
            "Configure ITSI glass tables for executive dashboards.",
            "ITSI KPI thresholds control alert severity.",
        ])
        gaps = detect_knowledge_gaps("How do I configure ITSI?", chunks)
        topics = [g.topic for g in gaps]
        assert "ITSI" not in topics

    # -- .conf file references --

    def test_conf_file_not_in_chunks(self):
        gaps = detect_knowledge_gaps("How to set inputs.conf for UDP?", [])
        topics = [g.topic for g in gaps]
        assert "inputs.conf" in topics
        conf_gap = next(g for g in gaps if g.topic == "inputs.conf")
        assert conf_gap.gap_type == "sparse"
        assert conf_gap.severity == "medium"
        assert "inputs.conf" in conf_gap.suggestion

    def test_conf_file_present_in_chunks(self):
        """When chunk text contains the .conf filename, no gap is raised for it."""
        chunks = _make_chunks([
            "Edit inputs.conf to add a UDP listener on port 514.",
            "The inputs.conf stanza [udp://514] enables syslog collection.",
            "Restart Splunk after changing inputs.conf.",
        ])
        gaps = detect_knowledge_gaps("How to set inputs.conf for UDP?", chunks)
        topics = [g.topic for g in gaps]
        assert "inputs.conf" not in topics

    def test_conf_spec_file_detection(self):
        gaps = detect_knowledge_gaps("Where is transforms.conf.spec?", [])
        topics = [g.topic for g in gaps]
        assert "transforms.conf.spec" in topics

    # -- SPL command references --

    def test_spl_command_not_in_chunks(self):
        gaps = detect_knowledge_gaps("index=main | tstats count where index=*", [])
        topics = [g.topic for g in gaps]
        assert "SPL command: tstats" in topics
        cmd_gap = next(g for g in gaps if g.topic == "SPL command: tstats")
        assert cmd_gap.gap_type == "sparse"
        assert cmd_gap.severity == "low"

    def test_spl_command_present_in_chunks(self):
        chunks = _make_chunks([
            "Use | tstats to search accelerated data models quickly.",
            "The tstats command supports summariesonly and prestats arguments.",
            "tstats is faster than stats for large data volumes.",
        ])
        gaps = detect_knowledge_gaps("index=main | tstats count", chunks)
        topics = [g.topic for g in gaps]
        assert "SPL command: tstats" not in topics

    def test_short_spl_commands_ignored(self):
        """Commands with 2 or fewer characters (like 'or') should be skipped."""
        # 'or' is not in _KNOWN_SPL_COMMANDS, but even if it were, len <= 2 filters it
        gaps = detect_knowledge_gaps("| or something", [])
        topics = [g.topic for g in gaps]
        # 'or' is not a known SPL command and is <= 2 chars — should not appear
        assert not any("SPL command: or" in t for t in topics)

    # -- Many relevant chunks → no sparsity gap --

    def test_many_chunks_no_sparsity_gap(self):
        chunks = _make_chunks([f"Chunk {i} about timechart usage" for i in range(5)])
        gaps = detect_knowledge_gaps("basic question about Splunk", chunks)
        topics = [g.topic for g in gaps]
        assert "general" not in topics

    # -- Overall sparsity --

    def test_zero_chunks_general_gap(self):
        gaps = detect_knowledge_gaps("Tell me about index optimization", [])
        general = next(g for g in gaps if g.topic == "general")
        assert general.gap_type == "missing_entirely"
        assert general.severity == "high"
        assert "No relevant content" in general.suggestion

    def test_below_threshold_sparse_gap(self):
        chunks = _make_chunks(["single chunk about topic"])
        gaps = detect_knowledge_gaps("Tell me about index optimization", chunks, chunk_threshold=2)
        general = next(g for g in gaps if g.topic == "general")
        assert general.gap_type == "sparse"
        assert general.severity == "medium"
        assert "1 relevant chunks" in general.suggestion

    # -- chunk_threshold variations --

    def test_chunk_threshold_exact_no_gap(self):
        """Exactly meeting the threshold should not trigger the sparsity gap."""
        chunks = _make_chunks(["a", "b"])
        gaps = detect_knowledge_gaps("anything", chunks, chunk_threshold=2)
        topics = [g.topic for g in gaps]
        assert "general" not in topics

    def test_custom_high_threshold(self):
        chunks = _make_chunks(["a", "b", "c"])
        gaps = detect_knowledge_gaps("anything", chunks, chunk_threshold=5)
        general = next(g for g in gaps if g.topic == "general")
        assert general.gap_type == "sparse"
        assert "3 relevant chunks" in general.suggestion

    # -- Deduplication --

    def test_duplicate_topics_deduplicated(self):
        """If a query triggers the same topic twice, only one gap per topic is returned."""
        gaps = detect_knowledge_gaps("Tell me about ITSI and ITSI configuration", [])
        itsi_gaps = [g for g in gaps if g.topic == "ITSI"]
        assert len(itsi_gaps) == 1


# ===========================================================================
# 3. format_gap_suggestions
# ===========================================================================


class TestFormatGapSuggestions:

    def test_no_gaps_returns_none(self):
        assert format_gap_suggestions([]) is None

    def test_only_low_severity_returns_none(self):
        """Low-severity gaps are not actionable and should not produce output."""
        gaps = [
            KnowledgeGap(topic="SPL command: eval", gap_type="sparse", severity="low",
                         suggestion="eval docs missing"),
        ]
        assert format_gap_suggestions(gaps) is None

    def test_only_medium_sparse_returns_none(self):
        """Medium severity with gap_type='sparse' (not 'missing_entirely') is excluded."""
        gaps = [
            KnowledgeGap(topic="general", gap_type="sparse", severity="medium",
                         suggestion="Only 1 chunk found"),
        ]
        assert format_gap_suggestions(gaps) is None

    def test_high_severity_gap_formatted(self):
        gaps = [
            KnowledgeGap(topic="ITSI", gap_type="missing_entirely", severity="high",
                         suggestion="Splunk ITSI documentation not found in knowledge base",
                         ingest_url="https://docs.splunk.com/Documentation/ITSI"),
        ]
        result = format_gap_suggestions(gaps)
        assert result is not None
        assert "note on coverage" in result
        assert "ITSI documentation not found" in result
        assert "read_url: https://docs.splunk.com/Documentation/ITSI" in result

    def test_medium_missing_entirely_included(self):
        gaps = [
            KnowledgeGap(topic="general", gap_type="missing_entirely", severity="medium",
                         suggestion="No content found"),
        ]
        result = format_gap_suggestions(gaps)
        assert result is not None
        assert "No content found" in result

    def test_max_three_gaps_displayed(self):
        gaps = [
            KnowledgeGap(topic=f"topic{i}", gap_type="missing_entirely", severity="high",
                         suggestion=f"Suggestion {i}")
            for i in range(5)
        ]
        result = format_gap_suggestions(gaps)
        assert result is not None
        assert result.count("- Suggestion") == 3

    def test_gap_without_url_no_suggested_source(self):
        gaps = [
            KnowledgeGap(topic="MINT", gap_type="missing_entirely", severity="high",
                         suggestion="MINT docs missing", ingest_url=None),
        ]
        result = format_gap_suggestions(gaps)
        assert result is not None
        assert "Suggested source" not in result


# ===========================================================================
# 4. should_suggest_ingestion
# ===========================================================================


class TestShouldSuggestIngestion:

    def test_no_gaps_returns_false(self):
        assert should_suggest_ingestion([]) is False

    def test_high_missing_entirely_returns_true(self):
        gaps = [
            KnowledgeGap(topic="ITSI", gap_type="missing_entirely", severity="high",
                         suggestion="Missing"),
        ]
        assert should_suggest_ingestion(gaps) is True

    def test_medium_missing_entirely_returns_true(self):
        gaps = [
            KnowledgeGap(topic="general", gap_type="missing_entirely", severity="medium",
                         suggestion="Missing"),
        ]
        assert should_suggest_ingestion(gaps) is True

    def test_low_severity_returns_false(self):
        gaps = [
            KnowledgeGap(topic="SPL command: eval", gap_type="missing_entirely", severity="low",
                         suggestion="Eval docs missing"),
        ]
        assert should_suggest_ingestion(gaps) is False

    def test_high_sparse_returns_false(self):
        """gap_type must be 'missing_entirely' for ingestion suggestion."""
        gaps = [
            KnowledgeGap(topic="general", gap_type="sparse", severity="high",
                         suggestion="Sparse"),
        ]
        assert should_suggest_ingestion(gaps) is False

    def test_mixed_gaps_true_if_any_qualifies(self):
        gaps = [
            KnowledgeGap(topic="cmd", gap_type="sparse", severity="low", suggestion="x"),
            KnowledgeGap(topic="ITSI", gap_type="missing_entirely", severity="high", suggestion="y"),
        ]
        assert should_suggest_ingestion(gaps) is True
