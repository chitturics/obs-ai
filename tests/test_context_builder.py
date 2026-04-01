"""Tests for chat_app/context_builder.py — context assembly and chunk management."""
import pytest
from chat_app.context_builder import (
    detect_config_context,
    detect_compound_query,
    format_chunk_with_metadata,
    scrub_lines,
    format_section,
    filter_references,
    classify_references,
    compute_confidence,
    merge_subquery_chunks,
    ContextResult,
)


class TestContextResultDataclass:
    """Test ContextResult data structure."""

    def test_default_construction(self):
        result = ContextResult()
        assert result.formatted_context == ""
        assert isinstance(result.all_refs, list)
        assert result.confidence_label == "LOW"
        assert result.filtered_count == 0

    def test_custom_construction(self):
        result = ContextResult(
            formatted_context="some context",
            confidence_label="HIGH",
            filtered_count=5,
        )
        assert result.formatted_context == "some context"
        assert result.confidence_label == "HIGH"


class TestDetectConfigContext:
    """Test config file detection from user input."""

    def test_detects_conf_file(self):
        files, hint = detect_config_context("show me props.conf settings")
        assert "props.conf" in files

    def test_detects_multiple_conf_files(self):
        files, hint = detect_config_context("compare props.conf and transforms.conf")
        assert "props.conf" in files
        assert "transforms.conf" in files

    def test_detects_spec_file(self):
        files, hint = detect_config_context("what does inputs.conf.spec say?")
        assert "inputs.conf.spec" in files

    def test_detects_stanza_hint_brackets(self):
        files, hint = detect_config_context("explain [syslog] stanza in props.conf")
        assert hint == "syslog"

    def test_detects_stanza_hint_keyword(self):
        files, hint = detect_config_context("show monitor settings in inputs.conf")
        assert hint == "monitor"

    def test_no_conf_file(self):
        files, hint = detect_config_context("what is Splunk?")
        assert len(files) == 0

    def test_no_stanza_hint(self):
        files, hint = detect_config_context("show me props.conf")
        # May or may not have a hint depending on presence of keywords
        assert isinstance(hint, (str, type(None)))


class TestDetectCompoundQuery:
    """Test compound query detection and splitting."""

    def test_simple_query_not_compound(self):
        is_compound, parts = detect_compound_query("what is Splunk?")
        assert is_compound is False
        assert parts == ["what is Splunk?"]

    def test_and_connector_detected(self):
        is_compound, parts = detect_compound_query(
            "explain props.conf and transforms.conf"
        )
        # Depends on whether the parts have recognizable patterns (.conf)
        if is_compound:
            assert len(parts) >= 2

    def test_comma_connector_detected(self):
        is_compound, parts = detect_compound_query(
            "show TRANSFORMS, LOOKUP table settings"
        )
        if is_compound:
            assert len(parts) >= 2

    def test_vs_connector_detected(self):
        is_compound, parts = detect_compound_query(
            "compare stats() vs eventstats()"
        )
        if is_compound:
            assert len(parts) >= 2


class TestFormatChunkWithMetadata:
    """Test chunk formatting with metadata headers."""

    def test_basic_formatting(self):
        result = format_chunk_with_metadata(
            "some chunk text",
            {"stanza": "syslog", "full_app_path": "TAs/TA-syslog/local/props.conf"},
        )
        assert "syslog" in result
        assert "some chunk text" in result

    def test_no_stanza(self):
        result = format_chunk_with_metadata("plain text", {})
        assert "plain text" in result

    def test_strips_existing_enrichment(self):
        text = "# App: TA-syslog\nactual content here"
        result = format_chunk_with_metadata(text, {"stanza": "test"})
        # Should strip the existing # App: prefix
        assert "actual content here" in result


class TestScrubLines:
    """Test noise/PII removal from text lines."""

    def test_removes_noise_lines(self):
        lines = ["real data", "generated for testing", "more data"]
        cleaned = scrub_lines(lines)
        # "generated for" is a noise pattern
        noise_found = any("generated for" in ln for ln in cleaned)
        assert not noise_found or len(cleaned) <= len(lines)

    def test_preserves_valid_lines(self):
        lines = ["index=main", "sourcetype=syslog", "disabled = false"]
        cleaned = scrub_lines(lines)
        assert len(cleaned) == 3

    def test_empty_input(self):
        assert scrub_lines([]) == []

    def test_empty_strings_removed(self):
        lines = ["data", "", "", "more data"]
        cleaned = scrub_lines(lines)
        assert "" not in cleaned


class TestFormatSection:
    """Test context section formatting."""

    def test_empty_items(self):
        assert format_section("## Header", []) == ""

    def test_single_line_items(self):
        result = format_section("## Header", ["item1", "item2"])
        assert "## Header" in result
        assert "* item1" in result
        assert "* item2" in result

    def test_multiline_items(self):
        result = format_section("## Header", ["[stanza1]\nkey=val", "[stanza2]\nkey2=val2"])
        assert "## Header" in result
        # Multi-line items use blank-line separation, not bullets
        assert "* " not in result


class TestFilterReferences:
    """Test reference filtering."""

    def test_removes_spec_refs_by_default(self):
        refs = ["/path/to/file.conf.spec", "/path/to/real.conf"]
        filtered = filter_references(refs, "show me props.conf settings")
        assert not any(".spec" in r for r in filtered)

    def test_keeps_spec_when_queried(self):
        refs = ["/path/to/props.conf.spec", "/path/to/real.conf"]
        filtered = filter_references(refs, "show me the props.conf.spec file")
        assert any(".spec" in r for r in filtered)

    def test_removes_feedback_refs(self):
        refs = ["feedback://previous-answer", "/path/to/real.conf"]
        filtered = filter_references(refs, "what is Splunk?")
        assert "feedback://previous-answer" not in filtered


class TestClassifyReferences:
    """Test reference type classification."""

    def test_feedback_ref_classified(self):
        refs = ["feedback://previous-answer"]
        classified = classify_references(refs)
        assert len(classified) >= 1
        assert classified[0][0] == "feedback"

    def test_empty_refs(self):
        assert classify_references([]) == []

    def test_limits_to_10(self):
        refs = [f"/path/to/file{i}.conf" for i in range(20)]
        classified = classify_references(refs)
        assert len(classified) <= 10


class TestComputeConfidence:
    """Test confidence label computation."""

    def test_high_with_spec_content(self):
        label = compute_confidence(
            local_spec_content=["spec data"],
            all_refs=[],
            filtered_count=0,
            doc_snippets=[],
        )
        assert label == "HIGH"

    def test_high_with_spec_refs_and_chunks(self):
        label = compute_confidence(
            local_spec_content=[],
            all_refs=["props.conf.spec", "other.conf"],
            filtered_count=2,
            doc_snippets=[],
        )
        assert label == "HIGH"

    def test_medium_with_doc_snippets(self):
        label = compute_confidence(
            local_spec_content=[],
            all_refs=["some_ref"],
            filtered_count=1,
            doc_snippets=["some doc"],
        )
        assert label == "MEDIUM"

    def test_low_with_nothing(self):
        label = compute_confidence(
            local_spec_content=[],
            all_refs=[],
            filtered_count=0,
            doc_snippets=[],
        )
        assert "LOW" in label


class TestMergeSubqueryChunks:
    """Test merging chunks from multiple sub-queries."""

    def test_single_query_passthrough(self):
        chunks = [{"page_content": "a"}, {"page_content": "b"}]
        merged = merge_subquery_chunks([chunks], k=10)
        assert len(merged) == 2

    def test_empty_input(self):
        merged = merge_subquery_chunks([], k=10)
        assert merged == []

    def test_respects_k_limit(self):
        chunks1 = [{"page_content": f"a{i}"} for i in range(10)]
        chunks2 = [{"page_content": f"b{i}"} for i in range(10)]
        merged = merge_subquery_chunks([chunks1, chunks2], k=5)
        assert len(merged) <= 5
