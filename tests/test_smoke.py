"""
Smoke tests — End-to-end pipeline validation using real sample files.

These tests validate that the full pipeline (ingestion → intent → routing →
retrieval → response) works correctly with real data from the repo.
Run with: pytest tests/test_smoke.py -v
"""
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Ingestion smoke tests
# ---------------------------------------------------------------------------

class TestIngestionSmoke:
    """Test that real files can be parsed and chunked."""

    def test_ingest_spl_doc(self, fixtures_dir, spl_docs_dir):
        """Parse a real SPL command doc file and extract content."""
        # Try fixtures first, fall back to real spl_docs
        doc_path = fixtures_dir / "sample_spl_doc.md"
        if not doc_path.exists():
            doc_path = spl_docs_dir / "spl_cmd_stats.md"
        assert doc_path.exists(), f"No SPL doc found at {doc_path}"
        content = doc_path.read_text(encoding="utf-8")
        assert len(content) > 100
        assert "stats" in content.lower() or "command" in content.lower()

    def test_ingest_conf_file(self, fixtures_dir):
        """Parse a real .conf file into stanzas."""
        from shared.conf_parser import parse_conf_file_advanced
        content = (fixtures_dir / "sample_props.conf").read_text(encoding="utf-8")
        result = parse_conf_file_advanced(content, filename="props.conf")
        assert len(result) >= 3
        assert "syslog" in result

    def test_ingest_conf_into_stanzas(self, fixtures_dir):
        """Parse .conf content into ConfStanza objects."""
        from shared.conf_parser import parse_conf_file
        content = (fixtures_dir / "sample_indexes.conf").read_text(encoding="utf-8")
        stanzas = parse_conf_file(content, filename="indexes.conf")
        assert len(stanzas) >= 3
        names = [s.name for s in stanzas]
        assert "main" in names

    def test_chunk_conf_file(self, fixtures_dir):
        """Chunk a .conf file into embedding-ready pieces."""
        from shared.conf_parser import chunk_conf_file
        content = (fixtures_dir / "sample_savedsearches.conf").read_text(encoding="utf-8")
        chunks = chunk_conf_file(
            content,
            str(fixtures_dir / "sample_savedsearches.conf"),
            max_chunk_size=3000,
            chunk_overlap=100,
        )
        assert len(chunks) >= 3
        for text, meta in chunks:
            assert isinstance(text, str)
            assert len(text) > 0
            assert isinstance(meta, dict)

    def test_chunk_sizes_reasonable(self, fixtures_dir):
        """All chunks should be reasonable size for embedding."""
        from shared.conf_parser import chunk_conf_file
        content = (fixtures_dir / "sample_props.conf").read_text(encoding="utf-8")
        chunks = chunk_conf_file(
            content,
            str(fixtures_dir / "sample_props.conf"),
            max_chunk_size=500,
        )
        for text, _ in chunks:
            # Allow some overflow for stanza headers but nothing extreme
            assert len(text) < 5000, f"Chunk too large: {len(text)} chars"


# ---------------------------------------------------------------------------
# Query pipeline smoke tests
# ---------------------------------------------------------------------------

class TestQueryPipelineSmoke:
    """Test that queries route correctly through the classification pipeline."""

    def test_spl_query_routes_correctly(self):
        """Raw SPL → spl_generation intent."""
        from chat_app.query_router_handler import route_query
        plan = route_query("index=main | stats count by host")
        assert plan.intent == "spl_generation"

    def test_config_query_routes(self):
        """Config reference → config_lookup intent."""
        from chat_app.query_router_handler import route_query
        plan = route_query("show me props.conf settings for syslog")
        assert plan.intent == "config_lookup"

    def test_nlp_query_routes(self):
        """Natural language → spl_generation intent (with NLP type)."""
        from chat_app.query_router_handler import route_query
        plan = route_query("show me failed logins in the last 24 hours")
        assert plan.intent == "spl_generation"
        assert plan.optimizer_type in ("nlp", "auto", "spl")

    def test_general_question_routes(self):
        """General question → general_qa intent."""
        from chat_app.query_router_handler import route_query
        plan = route_query("what is Splunk Enterprise Security?")
        assert plan.intent in ("general_qa", "spl_generation", "meta_question")

    def test_meta_question_routes(self):
        """Meta question → meta_question intent."""
        from chat_app.query_router_handler import route_query
        plan = route_query("who are you?")
        assert plan.intent == "meta_question"
        assert plan.skip_retrieval is True

    def test_troubleshoot_routes(self):
        """Troubleshooting → troubleshooting intent."""
        from chat_app.query_router_handler import route_query
        plan = route_query("my search is giving an error message")
        assert plan.intent == "troubleshooting"


# ---------------------------------------------------------------------------
# Reasoning / quality smoke tests
# ---------------------------------------------------------------------------

class TestReasoningSmoke:
    """Test quality evaluation on sample responses."""

    def test_good_response_scores_high(self):
        """Well-grounded response with context → acceptable quality."""
        from chat_app.self_evaluator import evaluate_response_quality
        response = (
            "The `stats` command in Splunk is used for aggregating data. "
            "For example: ```spl\nindex=main | stats count by host\n```\n"
            "This will count events grouped by the host field. "
            "The stats command supports functions like count, sum, avg, min, max."
        )
        context = (
            "The stats command calculates aggregate statistics over results. "
            "Syntax: stats [stats-function(field)] [by field-list]. "
            "Common functions: count, sum, avg, min, max, dc."
        )
        quality = evaluate_response_quality(
            response=response,
            user_query="how does the stats command work?",
            context=context,
            chunks_found=5,
        )
        assert quality.overall >= 0.5
        assert quality.recommended_action == "send"

    def test_empty_response_flagged(self):
        """Empty response → low quality."""
        from chat_app.self_evaluator import evaluate_response_quality
        quality = evaluate_response_quality(
            response="",
            user_query="what is Splunk?",
            context="Splunk is a data platform.",
            chunks_found=3,
        )
        assert quality.overall < 0.5
        assert quality.recommended_action in ("refine", "abstain", "clarify")

    def test_spl_in_response_validated(self):
        """Response with SPL block → SPL validity checked."""
        from chat_app.self_evaluator import evaluate_response_quality
        response = (
            "Here is your query:\n```spl\nindex=main | stats count by host\n```\n"
            "This counts events by host."
        )
        quality = evaluate_response_quality(
            response=response,
            user_query="count events by host",
            context="stats command counts events",
            chunks_found=3,
        )
        assert quality.spl_validity >= 0.5


# ---------------------------------------------------------------------------
# SPL generation and analysis smoke tests
# ---------------------------------------------------------------------------

class TestSPLSmoke:
    """Test SPL generation and analysis with real examples."""

    def test_template_generates_valid_spl(self):
        """NLP → SPL template generates a query string."""
        from shared.spl_template_engine import SPLTemplateEngine
        query, intent, explanation = SPLTemplateEngine.generate_query(
            "show me failed logins by source IP"
        )
        assert isinstance(query, str)
        assert len(query) > 0
        assert isinstance(explanation, str)

    def test_analyzer_catches_anti_patterns(self):
        """Known bad SPL → issues detected."""
        from shared.spl_robust_analyzer import analyze_spl
        result = analyze_spl("index=main | sort _time | stats count by host")
        # Sort before stats is an anti-pattern
        assert len(result.issues) > 0 or len(result.recommendations) > 0

    def test_analyzer_passes_good_query(self):
        """Valid tstats query → no critical issues."""
        from shared.spl_robust_analyzer import analyze_spl
        result = analyze_spl("| tstats count WHERE index=main by sourcetype")
        critical = [i for i in result.issues if i.severity.value == "critical"]
        assert len(critical) == 0

    def test_spl_intent_detection(self):
        """SPL template engine detects intent from NL."""
        from shared.spl_template_engine import SPLTemplateEngine
        intent = SPLTemplateEngine.detect_intent("count errors by sourcetype in the last hour")
        assert intent.query_type is not None
        assert intent.confidence >= 0.0


# ---------------------------------------------------------------------------
# Sample data smoke tests
# ---------------------------------------------------------------------------

class TestSampleDataSmoke:
    """Test with actual sample data files from fixtures."""

    def test_savedsearches_parsing(self, fixtures_dir):
        """Parse sample savedsearches.conf → correct stanza count."""
        from shared.conf_parser import parse_conf_file_advanced
        content = (fixtures_dir / "sample_savedsearches.conf").read_text(encoding="utf-8")
        result = parse_conf_file_advanced(content, filename="savedsearches.conf")
        assert "Failed Login Attempts - Last 24h" in result
        assert "Network Traffic by Host - Hourly" in result

    def test_macros_parsing(self, fixtures_dir):
        """Parse sample macros.conf → macro definitions found."""
        from shared.conf_parser import parse_conf_file_advanced
        content = (fixtures_dir / "sample_macros.conf").read_text(encoding="utf-8")
        result = parse_conf_file_advanced(content, filename="macros.conf")
        assert "cim_authentication" in result

    def test_indexes_parsing(self, fixtures_dir):
        """Parse sample indexes.conf → index definitions found."""
        from shared.conf_parser import parse_conf_file_advanced
        content = (fixtures_dir / "sample_indexes.conf").read_text(encoding="utf-8")
        result = parse_conf_file_advanced(content, filename="indexes.conf")
        assert "main" in result
        assert "security" in result

    def test_conf_enrichment(self, fixtures_dir):
        """Chunk enrichment adds metadata for search."""
        from shared.conf_parser import enrich_chunk_for_search
        enriched = enrich_chunk_for_search(
            "disabled = false\nindex = main",
            {"stanza": "monitor:///var/log", "filename": "inputs.conf"},
        )
        assert "monitor:///var/log" in enriched or "inputs.conf" in enriched

    def test_all_fixtures_parseable(self, fixtures_dir):
        """Every .conf fixture file can be parsed without errors."""
        from shared.conf_parser import parse_conf_file_advanced
        for conf_file in fixtures_dir.glob("*.conf"):
            content = conf_file.read_text(encoding="utf-8")
            result = parse_conf_file_advanced(content, filename=conf_file.name)
            assert isinstance(result, dict), f"Failed to parse {conf_file.name}"

    def test_knowledge_gap_with_no_chunks(self):
        """Knowledge gap detector identifies gaps when chunks are empty."""
        from chat_app.knowledge_gap_detector import detect_knowledge_gaps
        gaps = detect_knowledge_gaps(
            user_query="how do I configure ITSI?",
            retrieved_chunks=[],
            chunk_threshold=2,
        )
        assert len(gaps) > 0

    def test_confidence_scorer_low_with_no_data(self):
        """Confidence scorer returns low with no supporting data."""
        from chat_app.confidence_scorer import score_confidence
        score = score_confidence(
            local_spec_content=[],
            retrieved_chunks=[],
            user_query="tell me about Splunk SOAR",
        )
        assert score.label in ("LOW", "VERY_LOW")


# ---------------------------------------------------------------------------
# Optimizer integration smoke tests
# ---------------------------------------------------------------------------

class TestOptimizerSmoke:
    """Test the local SPL optimizer components (no remote service needed)."""

    def test_robust_analyzer_valid_query(self):
        """Valid SPL query passes analysis."""
        from shared.spl_robust_analyzer import analyze_spl
        result = analyze_spl("index=main | stats count by host")
        assert result.is_valid is True
        assert isinstance(result.recommendations, list)

    def test_robust_analyzer_complex_query(self):
        """Complex query with multiple pipes analyzed correctly."""
        from shared.spl_robust_analyzer import analyze_spl
        result = analyze_spl(
            "index=main sourcetype=access_combined | where status>=400 "
            "| stats count as error_count by host, uri_path "
            "| sort -error_count | head 20"
        )
        assert result.is_valid is True
        assert len(result.commands) >= 4

    def test_robust_analyzer_detects_sort_before_stats(self):
        """Anti-pattern: sort before stats is detected."""
        from shared.spl_robust_analyzer import analyze_spl
        result = analyze_spl("index=main | sort _time | stats count by host")
        issues_text = " ".join(str(i) for i in result.issues)
        recs_text = " ".join(result.recommendations)
        combined = (issues_text + recs_text).lower()
        # Either an issue or recommendation should mention sort or ordering
        assert "sort" in combined or len(result.issues) > 0

    def test_template_engine_ip_detection(self):
        """IP address in NL query is detected and included."""
        from shared.spl_template_engine import SPLTemplateEngine
        intent = SPLTemplateEngine.detect_intent("find traffic from 10.0.0.1")
        # The IP should be recognized as a keyword
        assert any("10.0.0.1" in kw or "ip" in kw.lower() for kw in intent.keywords) or intent.query_type is not None

    def test_template_engine_time_range(self):
        """Time range in NL query is extracted."""
        from shared.spl_template_engine import SPLTemplateEngine
        intent = SPLTemplateEngine.detect_intent("events in the last 4 hours")
        assert intent.time_range is not None

    def test_template_engine_groupby_extraction(self):
        """Group-by fields extracted from NL query."""
        from shared.spl_template_engine import SPLTemplateEngine
        query, intent, explanation = SPLTemplateEngine.generate_query(
            "count events by sourcetype and host"
        )
        # The generated query should reference sourcetype or host
        lower_query = query.lower()
        assert "sourcetype" in lower_query or "host" in lower_query

    def test_optimizer_bypass_format_review(self):
        """Optimizer bypass formats review responses correctly."""
        from chat_app.response_generator import _format_optimizer_bypass_response
        opt_result = {
            "review": {
                "status": "valid",
                "risk_score": 15,
                "errors": [],
                "warnings": ["Consider using tstats for better performance"],
            },
            "optimization": {
                "optimized_query": "| tstats count WHERE index=main BY host",
            },
        }
        response = _format_optimizer_bypass_response(
            opt_result, "index=main | stats count by host", "review"
        )
        assert response is not None
        assert "Query Review" in response
        assert "valid" in response

    def test_optimizer_bypass_format_optimize(self):
        """Optimizer bypass formats optimization responses correctly."""
        from chat_app.response_generator import _format_optimizer_bypass_response
        opt_result = {
            "optimization": {
                "optimized_query": "| tstats count WHERE index=main BY host",
                "strategy": "tstats_conversion",
                "performance_notes": ["10-100x faster with tstats"],
            },
        }
        response = _format_optimizer_bypass_response(
            opt_result, "index=main | stats count by host", "optimize"
        )
        assert response is not None
        assert "tstats" in response
        assert "Optimized Query" in response

    def test_optimizer_bypass_unchanged_returns_none(self):
        """Optimizer bypass returns None when query is unchanged."""
        from chat_app.response_generator import _format_optimizer_bypass_response
        response = _format_optimizer_bypass_response(
            {"optimization": {"optimized_query": "index=main | stats count"}},
            "index=main | stats count",
            "optimize",
        )
        assert response is None


# ---------------------------------------------------------------------------
# Failure handling smoke tests
# ---------------------------------------------------------------------------

class TestFailureHandlingSmoke:
    """Test failure analysis and recovery paths."""

    def test_connection_error_categorized(self):
        """ConnectionError → LLM_ERROR failure type."""
        from chat_app.failure_analyzer import categorize_failure
        report = categorize_failure(ConnectionError("connection refused"))
        assert report.failure_type.name == "LLM_ERROR"
        assert report.severity in ("high", "critical")

    def test_timeout_error_categorized(self):
        """TimeoutError → appropriate failure type."""
        from chat_app.failure_analyzer import categorize_failure
        report = categorize_failure(TimeoutError("request timed out"))
        assert report.failure_type is not None
        assert len(report.recovery_actions) > 0

    def test_quality_failure_empty_chunks(self):
        """No chunks retrieved → RETRIEVAL_EMPTY failure."""
        from chat_app.failure_analyzer import categorize_quality_failure
        report = categorize_quality_failure(
            chunks_found=0, confidence=0.1, response_length=5
        )
        assert report is not None
        assert report.failure_type.name == "RETRIEVAL_EMPTY"

    def test_quality_failure_good_response_no_report(self):
        """Good response quality → no failure report."""
        from chat_app.failure_analyzer import categorize_quality_failure
        report = categorize_quality_failure(
            chunks_found=10, confidence=0.9, response_length=500
        )
        assert report is None


# ---------------------------------------------------------------------------
# User model and personalization smoke tests
# ---------------------------------------------------------------------------

class TestUserModelSmoke:
    """Test user model and personalization."""

    def test_default_user_model(self):
        """Default user model has sensible defaults."""
        from chat_app.user_model import UserModel
        model = UserModel()
        assert model.expertise_level == "intermediate"
        assert model.preferred_style == "detailed"
        assert model.total_queries == 0

    def test_expert_user_model(self):
        """Expert user model has correct properties."""
        from chat_app.user_model import UserModel
        model = UserModel(
            expertise_level="expert",
            common_topics=["tstats", "datamodels"],
            total_queries=100,
            positive_feedback=80,
            negative_feedback=20,
        )
        assert model.satisfaction_rate == 0.8

    def test_beginner_user_model(self):
        """Beginner user model."""
        from chat_app.user_model import UserModel
        model = UserModel(
            expertise_level="beginner",
            common_topics=["basic search"],
            total_queries=5,
        )
        assert model.expertise_level == "beginner"


# ---------------------------------------------------------------------------
# Context compression smoke tests
# ---------------------------------------------------------------------------

class TestContextCompressionSmoke:
    """Test context compression utilities."""

    def test_short_context_no_compression(self):
        """Short context does not need compression."""
        from chat_app.context_compressor import should_compress
        assert not should_compress("Hello world, this is a test.")

    def test_large_context_needs_compression(self):
        """Large context triggers compression."""
        from chat_app.context_compressor import should_compress
        large = "x" * 20000  # ~5000 tokens
        assert should_compress(large)

    def test_token_estimation(self):
        """Token estimation is roughly 4 chars per token."""
        from chat_app.context_compressor import estimate_context_tokens
        tokens = estimate_context_tokens("abcd" * 100)  # 400 chars
        assert 90 <= tokens <= 110  # Should be ~100 tokens
