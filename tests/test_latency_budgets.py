"""Tests for latency budgets — per-tool timeouts and tracking."""

import pytest


@pytest.fixture
def tracker():
    from chat_app.latency_budgets import LatencyTracker
    return LatencyTracker()


class TestTimeouts:

    def test_known_tool_timeout(self, tracker):
        timeout = tracker.get_timeout("splunk_search")
        assert timeout == 30.0

    def test_unknown_tool_default_timeout(self, tracker):
        timeout = tracker.get_timeout("unknown_tool")
        assert timeout == 30.0  # default

    def test_fast_tool_timeout(self, tracker):
        timeout = tracker.get_timeout("base64_encode")
        assert timeout == 2.0

    def test_slow_tool_timeout(self, tracker):
        timeout = tracker.get_timeout("ingest_document")
        assert timeout == 120.0

    def test_set_custom_timeout(self, tracker):
        tracker.set_timeout("custom_tool", 45.0)
        assert tracker.get_timeout("custom_tool") == 45.0


class TestLatencyRecording:

    def test_record_within_budget(self, tracker):
        violated = tracker.record("base64_encode", latency_ms=500)
        assert violated is False

    def test_record_exceeds_budget(self, tracker):
        violated = tracker.record("base64_encode", latency_ms=5000)  # 5s > 2s budget
        assert violated is True

    def test_report_after_recording(self, tracker):
        for ms in [100, 200, 150, 180, 120]:
            tracker.record("base64_encode", ms)

        report = tracker.get_report("base64_encode")
        assert report["samples"] == 5
        assert report["total_calls"] == 5
        assert report["min_ms"] == 100.0
        assert report["max_ms"] == 200.0
        assert report["within_budget"] is True  # All under 2000ms

    def test_report_no_data(self, tracker):
        report = tracker.get_report("never_called")
        assert report["samples"] == 0

    def test_violations_tracked(self, tracker):
        for _ in range(5):
            tracker.record("base64_encode", 500)
        for _ in range(5):
            tracker.record("base64_encode", 5000)  # Over budget

        report = tracker.get_report("base64_encode")
        assert report["violations"] == 5
        assert report["violation_rate"] == 0.5


class TestPercentiles:

    def test_percentile_computation(self, tracker):
        for ms in range(1, 101):
            tracker.record("test_tool", float(ms))

        report = tracker.get_report("test_tool")
        assert report["p50_ms"] == pytest.approx(50.5, abs=1)
        assert report["p95_ms"] == pytest.approx(95.05, abs=1)
        assert report["p99_ms"] == pytest.approx(99.01, abs=1)

    def test_single_sample_percentile(self, tracker):
        tracker.record("test_tool", 42.0)
        report = tracker.get_report("test_tool")
        assert report["p50_ms"] == 42.0
        assert report["p95_ms"] == 42.0


class TestFallbacks:

    def test_known_fallback(self, tracker):
        assert tracker.get_fallback("splunk_search") == "cached_search"

    def test_unknown_fallback(self, tracker):
        assert tracker.get_fallback("unknown_tool") is None

    def test_set_fallback(self, tracker):
        tracker.set_fallback("custom_tool", "fallback_tool")
        assert tracker.get_fallback("custom_tool") == "fallback_tool"

    def test_fallback_in_report(self, tracker):
        tracker.record("splunk_search", 100)
        report = tracker.get_report("splunk_search")
        assert report["fallback"] == "cached_search"


class TestViolationDetection:

    def test_no_violations_initially(self, tracker):
        violations = tracker.get_violations()
        assert violations == []

    def test_detect_budget_violation(self, tracker):
        # Consistently exceed budget (2s = 2000ms for base64_encode)
        for _ in range(20):
            tracker.record("base64_encode", 5000)

        violations = tracker.get_violations()
        assert len(violations) >= 1
        tool_names = [v["tool"] for v in violations]
        assert "base64_encode" in tool_names


class TestSummary:

    def test_empty_summary(self, tracker):
        summary = tracker.get_summary()
        assert summary["total_tools_tracked"] == 0
        assert summary["total_calls"] == 0

    def test_summary_with_data(self, tracker):
        for _ in range(10):
            tracker.record("tool_a", 100)
        for _ in range(5):
            tracker.record("tool_b", 200)

        summary = tracker.get_summary()
        assert summary["total_tools_tracked"] == 2
        assert summary["total_calls"] == 15

    def test_configured_counts(self, tracker):
        summary = tracker.get_summary()
        assert summary["configured_timeouts"] > 10
        assert summary["configured_fallbacks"] > 0


class TestTimeoutConfig:

    def test_get_all_timeouts(self, tracker):
        timeouts = tracker.get_all_timeouts()
        assert "splunk_search" in timeouts
        assert "base64_encode" in timeouts

    def test_get_all_fallbacks(self, tracker):
        fallbacks = tracker.get_all_fallbacks()
        assert "splunk_search" in fallbacks
