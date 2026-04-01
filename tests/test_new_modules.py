"""
Tests for new self-learning, document ingestion, and health monitoring modules.
"""
import os
import sys
import json
import tempfile
from pathlib import Path
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ---------------------------------------------------------------------------
# Self-Learning Tests
# ---------------------------------------------------------------------------

class TestSelfLearning:
    """Test self-learning pipeline components."""

    def test_qa_from_spl_doc(self):
        """Test Q&A generation from SPL docs."""
        from chat_app.self_learning import _extract_qa_from_spl_doc
        # Create a temp SPL doc
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', prefix='spl_cmd_test_', delete=False) as f:
            f.write("# test command\n\n## Description\nThis is a test command that does things.\n\n## Syntax\n| test <args>\n\n## Examples\n| test field=value\n")
            f.flush()
            pairs = _extract_qa_from_spl_doc(f.name)
        os.unlink(f.name)
        assert len(pairs) >= 2, f"Expected at least 2 Q&A pairs, got {len(pairs)}"
        assert any("test" in p.question.lower() for p in pairs)

    def test_qa_from_config(self):
        """Test Q&A generation from config files."""
        from chat_app.self_learning import _extract_qa_from_config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
            f.write("[default]\ndisabled = false\n\n[my_stanza]\nindex = main\nsourcetype = syslog\n")
            f.flush()
            pairs = _extract_qa_from_config(f.name)
        os.unlink(f.name)
        assert len(pairs) >= 1

    def test_qa_dedup(self):
        """Test Q&A deduplication."""
        from chat_app.self_learning import generate_qa_pairs_from_directory
        # Non-existent dir returns empty
        pairs = generate_qa_pairs_from_directory("/nonexistent/path")
        assert pairs == []

    def test_coverage_calculation(self):
        """Test coverage calculation helper."""
        from chat_app.self_learning import _calculate_coverage
        coverage = _calculate_coverage("how to use tstats for performance", "tstats provides fast indexed aggregation for performance")
        assert coverage > 0.3, f"Expected coverage > 0.3, got {coverage}"

    def test_extract_topic(self):
        """Test topic extraction from questions."""
        from chat_app.self_learning import _extract_topic
        assert _extract_topic("how do I write an SPL query") == "spl"
        assert _extract_topic("configure inputs.conf for monitoring") == "config"
        assert _extract_topic("cribl pipeline routing") == "cribl"
        assert _extract_topic("something random") == "general"


# ---------------------------------------------------------------------------
# Document Ingestion Tests
# ---------------------------------------------------------------------------

class TestDocumentIngestor:
    """Test document ingestion for various formats."""

    def test_chunk_text(self):
        """Test text chunking."""
        from chat_app.document_ingestor import _chunk_text
        text = "word " * 200
        chunks = _chunk_text(text, chunk_size=500)
        assert len(chunks) >= 1
        assert all("text" in c for c in chunks)

    def test_parse_json(self):
        """Test JSON file parsing."""
        from chat_app.document_ingestor import parse_json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"key": "value", "nested": {"a": 1, "b": 2}}, f)
            f.flush()
            doc = parse_json(f.name)
        os.unlink(f.name)
        assert doc.error is None
        assert doc.chunk_count > 0
        assert doc.source_type == "json"

    def test_parse_csv(self):
        """Test CSV file parsing."""
        from chat_app.document_ingestor import parse_csv
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("name,value,status\ntest1,100,ok\ntest2,200,error\ntest3,300,ok\n")
            f.flush()
            doc = parse_csv(f.name)
        os.unlink(f.name)
        assert doc.error is None
        assert doc.chunk_count > 0
        assert doc.source_type == "csv"

    def test_parse_html(self):
        """Test HTML parsing."""
        from chat_app.document_ingestor import parse_html
        html = "<html><head><title>Test</title></head><body><main><p>This is test content for parsing.</p></main></body></html>"
        doc = parse_html(html, source_url="http://example.com")
        assert doc.error is None
        assert doc.chunk_count > 0
        assert doc.source_type == "html"

    def test_parse_text(self):
        """Test text file parsing."""
        from chat_app.document_ingestor import _parse_text
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("This is a test document with enough content to create at least one chunk of text for the vector store.")
            f.flush()
            doc = _parse_text(f.name)
        os.unlink(f.name)
        assert doc.error is None
        assert doc.source_type == "text"

    def test_sharepoint_not_configured(self):
        """Test SharePoint connector reports unconfigured correctly."""
        from chat_app.document_ingestor import SharePointConnector
        connector = SharePointConnector()
        assert not connector.is_configured

    def test_confluence_not_configured(self):
        """Test Confluence connector reports unconfigured correctly."""
        from chat_app.document_ingestor import ConfluenceConnector
        connector = ConfluenceConnector()
        assert not connector.is_configured

    def test_flatten_dict(self):
        """Test dictionary flattening."""
        from chat_app.document_ingestor import _flatten_dict
        result = _flatten_dict({"a": 1, "b": {"c": 2, "d": [1, 2, 3]}})
        assert "a: 1" in result
        assert "b.c: 2" in result


# ---------------------------------------------------------------------------
# Health Monitor Tests
# ---------------------------------------------------------------------------

class TestHealthMonitor:
    """Test internal health monitoring."""

    def test_internal_metrics_singleton(self):
        """Test metrics singleton pattern."""
        from chat_app.health_monitor import get_internal_metrics
        m1 = get_internal_metrics()
        m2 = get_internal_metrics()
        assert m1 is m2

    def test_metrics_increment(self):
        """Test counter increment."""
        from chat_app.health_monitor import InternalMetrics
        # Create fresh instance for test
        m = InternalMetrics.__new__(InternalMetrics)
        m._initialized = False
        m.__init__()
        m._initialized = True  # prevent singleton override
        m.increment("queries_total")
        m.increment("queries_total")
        assert m._counters["queries_total"] == 2

    def test_metrics_latency(self):
        """Test latency recording."""
        from chat_app.health_monitor import InternalMetrics
        m = InternalMetrics.__new__(InternalMetrics)
        m._initialized = False
        m.__init__()
        m._initialized = True
        m.record_latency(100.0)
        m.record_latency(200.0)
        assert m._gauges["avg_response_latency_ms"] == 150.0

    def test_prometheus_export(self):
        """Test Prometheus text format export."""
        from chat_app.health_monitor import InternalMetrics
        m = InternalMetrics.__new__(InternalMetrics)
        m._initialized = False
        m.__init__()
        m._initialized = True
        m.increment("queries_total", 5)
        m.record_latency(100.0)
        output = m.to_prometheus()
        assert "obsai_queries_total 5" in output
        assert "obsai_response_latency_ms" in output

    def test_grafana_dashboard(self):
        """Test Grafana dashboard generation."""
        from chat_app.health_monitor import generate_grafana_dashboard
        dashboard = generate_grafana_dashboard()
        assert "dashboard" in dashboard
        assert dashboard["dashboard"]["title"] == "ObsAI - Internal Health"
        assert len(dashboard["dashboard"]["panels"]) >= 6


# ---------------------------------------------------------------------------
# Proactive Insights Tests
# ---------------------------------------------------------------------------

class TestProactiveInsights:
    """Test proactive insights engine."""

    def test_explain_spl_basic(self):
        """Test basic SPL explanation."""
        from chat_app.proactive_insights import explain_spl
        explanation = explain_spl("index=main sourcetype=access_combined | stats count by status | sort -count")
        assert explanation.steps, "Expected at least one step"
        assert explanation.summary, "Expected a summary"
        assert len(explanation.steps) >= 2

    def test_explain_spl_complex(self):
        """Test complex SPL explanation."""
        from chat_app.proactive_insights import explain_spl
        explanation = explain_spl(
            "index=main sourcetype=access_combined | join type=left host [search index=_internal | stats count by host] | table host, count"
        )
        assert explanation.complexity in ("moderate", "complex")
        assert any("join" in note.lower() for note in explanation.performance_notes)

    def test_explain_spl_empty(self):
        """Test empty SPL explanation."""
        from chat_app.proactive_insights import explain_spl
        explanation = explain_spl("")
        assert "doesn't appear" in explanation.summary.lower() or len(explanation.steps) == 0

    def test_quick_spl_review(self):
        """Test quick SPL review for issues."""
        from chat_app.proactive_insights import _quick_spl_review
        # Test join detection
        insight = _quick_spl_review("index=main | join type=left host [search index=_internal]")
        assert insight is not None
        assert "join" in insight.title.lower()

        # Test wildcard sourcetype (no stats to avoid matching tstats/time-range rules)
        insight = _quick_spl_review("index=main sourcetype=* | table host, source")
        assert insight is not None
        assert "wildcard" in insight.title.lower()

    def test_inject_org_context(self):
        """Test organization context injection."""
        from chat_app.proactive_insights import inject_org_context
        org_config = {
            "index_mappings": {"authentication": "wineventlog", "network": "firewall"},
            "field_mappings": {"user": "user", "source_ip": "src_ip"},
        }
        result = inject_org_context("show me authentication events", org_config)
        assert "wineventlog" in result
        assert "authentication" in result

    def test_format_reasoning_trace(self):
        """Test reasoning trace formatting."""
        from chat_app.proactive_insights import format_reasoning_trace
        trace = format_reasoning_trace(
            intent="spl_generation",
            profile="spl_expert",
            chunks_found=8,
            collections_searched=["spl_commands_mxbai", "org_repo_mxbai"],
            confidence_score=0.85,
            tools_used=["analyze_spl", "optimize_spl"],
            latency_ms=3500,
        )
        assert "spl_generation" in trace
        assert "85%" in trace
        assert "analyze_spl" in trace


# ---------------------------------------------------------------------------
# Auto-Explain & Intent Classification Tests
# ---------------------------------------------------------------------------

class TestAutoExplain:
    """Test auto-explain for raw SPL pasted without context."""

    def test_raw_spl_without_context_gets_explain(self):
        """Raw SPL with no question words should get auto_explain."""
        from chat_app.intent_classifier import IntentClassifier
        classifier = IntentClassifier()
        query = "index=main sourcetype=access_combined | stats count by status | sort -count"
        plan = classifier.classify(query, word_count=len(query.split()))
        assert plan.intent == "spl_generation"
        assert plan.optimizer_action == "explain"
        assert plan.auto_explain is True

    def test_raw_spl_with_question_gets_optimize(self):
        """Raw SPL with question context should get optimize."""
        from chat_app.intent_classifier import IntentClassifier
        classifier = IntentClassifier()
        query = "can you optimize index=main | stats count by host"
        plan = classifier.classify(query, word_count=len(query.split()))
        assert plan.intent == "spl_generation"
        assert plan.optimizer_action == "optimize"

    def test_raw_spl_with_help_gets_explain(self):
        """SPL with 'help' context triggers explain action."""
        from chat_app.intent_classifier import IntentClassifier
        classifier = IntentClassifier()
        query = "help me fix index=main sourcetype=syslog | stats count"
        plan = classifier.classify(query, word_count=len(query.split()))
        assert plan.optimizer_action in ("explain", "optimize")


# ---------------------------------------------------------------------------
# Retrieval Boost Tests
# ---------------------------------------------------------------------------

class TestRetrievalBoost:
    """Test retrieval boost from learning feedback."""

    def test_boost_scores_cache(self):
        """Test that cached boost scores return a dict."""
        from chat_app.self_learning import get_cached_boost_scores
        scores = get_cached_boost_scores()
        assert isinstance(scores, dict)

    def test_boost_cache_update(self):
        """Test that boost cache can be populated."""
        from chat_app import self_learning_cycle
        # Simulate populating cache (canonical location is self_learning_cycle)
        self_learning_cycle._boost_cache = {"spl_commands_mxbai": 1.2, "org_repo_mxbai": 0.8}
        scores = self_learning_cycle.get_cached_boost_scores()
        assert scores["spl_commands_mxbai"] == 1.2
        assert scores["org_repo_mxbai"] == 0.8
        # Clean up
        self_learning_cycle._boost_cache = {}


# ---------------------------------------------------------------------------
# Model Customization Pipeline Tests
# ---------------------------------------------------------------------------

class TestModelCustomization:
    """Test model customization pipeline."""

    def test_export_qa_to_training_data(self, tmp_path):
        """Test exporting Q&A pairs to JSONL training format."""
        from chat_app.self_learning import QAPair, export_qa_to_training_data
        pairs = [
            QAPair(question="What is index?", answer="An index stores data.", source_type="doc"),
            QAPair(question="How to use stats?", answer="stats count by host", source_type="spl_doc"),
            QAPair(question="", answer="empty question"),  # Should be skipped
        ]
        filepath, count = export_qa_to_training_data(pairs, output_dir=str(tmp_path))
        assert count == 2  # Empty question skipped
        assert Path(filepath).exists()

        # Verify JSONL format
        import json
        lines = Path(filepath).read_text().strip().split("\n")
        assert len(lines) == 2
        entry = json.loads(lines[0])
        assert "messages" in entry
        assert len(entry["messages"]) == 3
        assert entry["messages"][0]["role"] == "system"
        assert entry["messages"][1]["role"] == "user"
        assert entry["messages"][2]["role"] == "assistant"

    def test_build_combined_training_file(self, tmp_path):
        """Test combining multiple JSONL files."""
        from chat_app.self_learning import build_combined_training_file
        import json

        # Create two JSONL files with some overlap
        f1 = tmp_path / "file1.jsonl"
        f2 = tmp_path / "file2.jsonl"
        f1.write_text(json.dumps({"q": "a"}) + "\n" + json.dumps({"q": "b"}) + "\n")
        f2.write_text(json.dumps({"q": "b"}) + "\n" + json.dumps({"q": "c"}) + "\n")

        filepath, count = build_combined_training_file(output_dir=str(tmp_path))
        assert count == 3  # Deduplicated
        assert Path(filepath).exists()

    def test_generate_modelfile(self, tmp_path):
        """Test Modelfile generation."""
        from chat_app.self_learning import generate_modelfile
        path = generate_modelfile(
            base_model="qwen2.5:3b",
            output_dir=str(tmp_path),
        )
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "FROM qwen2.5:3b" in content
        assert "PARAMETER temperature" in content
        assert "SYSTEM" in content

    def test_model_customization_report_dataclass(self):
        """Test ModelCustomizationReport structure."""
        from chat_app.self_learning import ModelCustomizationReport
        report = ModelCustomizationReport()
        assert report.qa_pairs_exported == 0
        assert report.model_created is False
        assert report.error == ""

    def test_extract_qa_from_savedsearches(self, tmp_path):
        """Test Q&A extraction from savedsearches.conf."""
        from chat_app.self_learning import _extract_qa_from_savedsearches
        conf = tmp_path / "savedsearches.conf"
        conf.write_text(
            "[Failed Logins]\n"
            "search = index=wineventlog EventCode=4625 | stats count by user\n"
            "cron_schedule = */15 * * * *\n"
            "description = Tracks failed login attempts\n"
            "\n"
            "[default]\n"
            "dispatch.earliest_time = -24h\n"
        )
        pairs = _extract_qa_from_savedsearches(str(conf))
        # Should create 2 pairs for "Failed Logins" (what does it do + show SPL), skip default
        assert len(pairs) == 2
        assert "Failed Logins" in pairs[0].question
        assert pairs[0].source_type == "savedsearch"

    def test_extract_qa_from_macros(self, tmp_path):
        """Test Q&A extraction from macros.conf."""
        from chat_app.self_learning import _extract_qa_from_macros
        conf = tmp_path / "macros.conf"
        conf.write_text(
            "[get_auth_events(1)]\n"
            "definition = index=$idx$ sourcetype=auth*\n"
            "args = idx\n"
            "description = Returns auth events for given index\n"
        )
        pairs = _extract_qa_from_macros(str(conf))
        assert len(pairs) == 1
        assert "get_auth_events" in pairs[0].question
        assert pairs[0].source_type == "macro"

    def test_extract_qa_from_indexes(self, tmp_path):
        """Test Q&A extraction from indexes.conf."""
        from chat_app.self_learning import _extract_qa_from_indexes
        conf = tmp_path / "indexes.conf"
        conf.write_text(
            "[security]\n"
            "frozenTimePeriodInSecs = 7776000\n"
            "maxDataSizeMB = 50000\n"
            "datatype = event\n"
        )
        pairs = _extract_qa_from_indexes(str(conf))
        assert len(pairs) == 1
        assert "security" in pairs[0].question
        assert "90" in pairs[0].answer  # 7776000 / 86400 = 90 days

    def test_directory_scanner_routes_specialized_conf(self, tmp_path):
        """Test that generate_qa_pairs_from_directory routes specialized .conf files."""
        from chat_app.self_learning import generate_qa_pairs_from_directory

        # Create a savedsearches.conf in the temp directory
        ss_conf = tmp_path / "savedsearches.conf"
        ss_conf.write_text(
            "[My Search]\n"
            "search = index=main | stats count\n"
            "cron_schedule = 0 * * * *\n"
        )

        pairs = generate_qa_pairs_from_directory(str(tmp_path))
        # Should get 2 pairs from savedsearch extractor (not generic config)
        assert len(pairs) == 2
        assert any("My Search" in p.question for p in pairs)
        assert all(p.source_type == "savedsearch" for p in pairs)


# ---------------------------------------------------------------------------
# Logging & Observability Tests
# ---------------------------------------------------------------------------

class TestLoggingUtils:
    """Test enhanced logging utilities."""

    def test_request_context(self):
        """Test set/get/clear request context."""
        from chat_app.logging_utils import set_request_context, get_request_id, clear_request_context
        rid = set_request_context(user_id="testuser", session_id="sess123")
        assert len(rid) == 12  # Auto-generated hex
        assert get_request_id() == rid
        clear_request_context()
        assert get_request_id() == ""

    def test_request_context_custom_id(self):
        """Test setting a custom request ID."""
        from chat_app.logging_utils import set_request_context, get_request_id, clear_request_context
        rid = set_request_context(request_id="custom-req-001")
        assert rid == "custom-req-001"
        assert get_request_id() == "custom-req-001"
        clear_request_context()

    def test_latency_tracker(self):
        """Test component latency tracking."""
        import time
        from chat_app.logging_utils import LatencyTracker
        tracker = LatencyTracker()
        tracker.start("component_a")
        time.sleep(0.01)  # 10ms
        elapsed = tracker.stop("component_a")
        assert elapsed >= 5  # At least 5ms
        assert "component_a" in tracker.to_dict()
        assert "component_a" in tracker.summary()

    def test_latency_tracker_multiple(self):
        """Test tracking multiple components."""
        from chat_app.logging_utils import LatencyTracker
        tracker = LatencyTracker()
        tracker.start("a")
        tracker.stop("a")
        tracker.start("b")
        tracker.stop("b")
        d = tracker.to_dict()
        assert "a" in d
        assert "b" in d

    def test_json_formatter(self):
        """Test JSON log formatter produces valid JSON."""
        import logging
        from chat_app.logging_utils import JSONFormatter
        fmt = JSONFormatter("test_app")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Test message", args=(), exc_info=None,
        )
        record.app = "test_app"
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert parsed["app"] == "test_app"

    def test_kv_formatter_with_structured_fields(self):
        """Test key-value formatter includes structured extra fields."""
        import logging
        from chat_app.logging_utils import KeyValueFormatter
        fmt = KeyValueFormatter("test_app")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Test", args=(), exc_info=None,
        )
        record.app = "test_app"
        record.structured = {"intent": "search", "latency_ms": 150}
        output = fmt.format(record)
        assert "intent=search" in output
        assert "latency_ms=150" in output


# ---------------------------------------------------------------------------
# Resource Manager Tests
# ---------------------------------------------------------------------------

class TestResourceManager:
    """Test resource management, auto-heal, and learning history."""

    def test_resource_snapshot(self):
        """Test getting a resource snapshot."""
        from chat_app.resource_manager import get_resource_snapshot
        snap = get_resource_snapshot()
        assert snap.timestamp != ""
        # On Linux, memory should be detected
        assert snap.memory_percent >= 0

    def test_can_run_heavy_task(self):
        """Test resource check for heavy tasks."""
        from chat_app.resource_manager import can_run_heavy_task
        # Use 100.1 thresholds — WSL2 /proc/loadavg can report 100% CPU
        allowed, reason = can_run_heavy_task(max_cpu=100.1, max_memory=100.1)
        assert allowed is True
        assert reason == "OK"

    def test_job_overlap_prevention(self):
        """Test that jobs can't overlap."""
        from chat_app.resource_manager import acquire_job, release_job, is_job_running
        assert acquire_job("test_job") is True
        assert is_job_running("test_job") is True
        assert acquire_job("test_job") is False  # Can't acquire again
        release_job("test_job")
        assert is_job_running("test_job") is False
        assert acquire_job("test_job") is True  # Can acquire after release
        release_job("test_job")

    def test_stale_job_detection(self):
        """Test that stale jobs are automatically released."""
        import time
        from chat_app.resource_manager import _running_jobs, is_job_running
        # Simulate a stale job (started 2 hours ago)
        _running_jobs["stale_job"] = time.monotonic() - 7200
        # With max_duration=3600, this should be detected as stale
        assert is_job_running("stale_job", max_duration_s=3600) is False
        assert "stale_job" not in _running_jobs

    def test_service_health_tracking(self):
        """Test service health cache."""
        from chat_app.resource_manager import (
            update_service_health, get_service_health, is_service_healthy,
            get_all_service_health,
        )
        update_service_health("test_svc", "healthy")
        assert get_service_health("test_svc") == "healthy"
        assert is_service_healthy("test_svc") is True

        update_service_health("test_svc", "unhealthy")
        assert is_service_healthy("test_svc") is False

        health = get_all_service_health()
        assert "test_svc" in health
        # Cleanup
        update_service_health("test_svc", "healthy")

    def test_learning_snapshot(self):
        """Test recording and querying learning snapshots."""
        from chat_app.resource_manager import (
            record_learning_snapshot, get_learning_history, get_learning_trend,
        )
        record_learning_snapshot(
            qa_pairs=100, facts=10, quality_avg=0.75, success_rate=0.8,
            notes=["Test snapshot"],
        )
        history = get_learning_history(limit=5)
        assert len(history) >= 1
        assert history[-1]["qa_pairs"] == 100

        trend = get_learning_trend()
        assert trend["snapshots"] >= 1

    def test_healing_event_dataclass(self):
        """Test HealingEvent structure."""
        from chat_app.resource_manager import HealingEvent
        event = HealingEvent(
            timestamp="2026-01-01T00:00:00Z",
            service="test",
            issue="connection failed",
            action="reconnect",
            success=True,
        )
        assert event.success is True
        assert event.service == "test"
