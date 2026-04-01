"""Comprehensive unit tests for chat_app.observability."""
import time
from unittest.mock import patch

import pytest

from chat_app.observability import (
    AlertRule,
    AlertSeverity,
    FiredAlert,
    ObservabilityManager,
    SLODefinition,
    SLOStatus,
    SLOType,
    Span,
    SpanStatus,
    Trace,
)


# ---------------------------------------------------------------------------
# SpanStatus enum
# ---------------------------------------------------------------------------

class TestSpanStatus:
    def test_ok_value(self):
        assert SpanStatus.OK.value == "ok"

    def test_error_value(self):
        assert SpanStatus.ERROR.value == "error"

    def test_timeout_value(self):
        assert SpanStatus.TIMEOUT.value == "timeout"


# ---------------------------------------------------------------------------
# Span
# ---------------------------------------------------------------------------

class TestSpan:
    def test_creation_defaults(self):
        span = Span()
        assert len(span.span_id) == 12
        assert span.trace_id == ""
        assert span.parent_id is None
        assert span.operation == ""
        assert span.service == "obsai"
        assert span.start_time > 0
        assert span.end_time is None
        assert span.duration_ms == 0.0
        assert span.status == SpanStatus.OK
        assert span.attributes == {}
        assert span.events == []
        assert span.error is None

    def test_creation_with_values(self):
        span = Span(
            span_id="abc123",
            trace_id="trace1",
            parent_id="parent1",
            operation="classify",
            service="test",
            attributes={"key": "value"},
        )
        assert span.span_id == "abc123"
        assert span.trace_id == "trace1"
        assert span.parent_id == "parent1"
        assert span.operation == "classify"
        assert span.service == "test"
        assert span.attributes == {"key": "value"}

    def test_finish_sets_end_time_and_duration(self):
        span = Span()
        span.start_time = time.time() - 0.1  # 100ms ago
        span.finish()
        assert span.end_time is not None
        assert span.duration_ms >= 90  # at least ~90ms (allowing some tolerance)
        assert span.status == SpanStatus.OK
        assert span.error is None

    def test_finish_with_error(self):
        span = Span()
        span.finish(status=SpanStatus.ERROR, error="something broke")
        assert span.status == SpanStatus.ERROR
        assert span.error == "something broke"
        assert span.end_time is not None
        assert span.duration_ms >= 0

    def test_finish_with_timeout(self):
        span = Span()
        span.finish(status=SpanStatus.TIMEOUT)
        assert span.status == SpanStatus.TIMEOUT

    def test_add_event(self):
        span = Span()
        span.add_event("cache_hit", {"size": 42})
        assert len(span.events) == 1
        assert span.events[0]["name"] == "cache_hit"
        assert span.events[0]["attributes"] == {"size": 42}
        assert "timestamp" in span.events[0]

    def test_add_event_no_attributes(self):
        span = Span()
        span.add_event("start")
        assert span.events[0]["attributes"] == {}

    def test_add_multiple_events(self):
        span = Span()
        span.add_event("event_a")
        span.add_event("event_b")
        span.add_event("event_c")
        assert len(span.events) == 3

    def test_to_dict(self):
        span = Span(span_id="s1", trace_id="t1", operation="test_op")
        span.finish()
        d = span.to_dict()
        assert d["span_id"] == "s1"
        assert d["trace_id"] == "t1"
        assert d["operation"] == "test_op"
        assert d["status"] == "ok"
        assert d["parent_id"] is None
        assert isinstance(d["duration_ms"], float)
        assert isinstance(d["events"], list)
        assert d["error"] is None

    def test_to_dict_rounded_duration(self):
        span = Span()
        span.duration_ms = 123.456789
        d = span.to_dict()
        assert d["duration_ms"] == 123.46


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------

class TestTrace:
    def test_creation_defaults(self):
        trace = Trace()
        assert len(trace.trace_id) == 16
        assert trace.spans == []
        assert trace.start_time > 0
        assert trace.user_id is None
        assert trace.query == ""
        assert trace.intent == ""

    def test_creation_with_values(self):
        trace = Trace(trace_id="t123", user_id="u1", query="test query", intent="search")
        assert trace.trace_id == "t123"
        assert trace.user_id == "u1"
        assert trace.query == "test query"
        assert trace.intent == "search"

    def test_create_span_basic(self):
        trace = Trace(trace_id="t1")
        span = trace.create_span("classify")
        assert span.trace_id == "t1"
        assert span.operation == "classify"
        assert span.parent_id is None  # first span has no parent
        assert len(trace.spans) == 1

    def test_create_span_auto_parent(self):
        trace = Trace()
        span1 = trace.create_span("step_1")
        span2 = trace.create_span("step_2")
        # Second span should auto-parent to the first
        assert span2.parent_id == span1.span_id
        assert len(trace.spans) == 2

    def test_create_span_explicit_parent(self):
        trace = Trace()
        trace.create_span("step_1")
        span2 = trace.create_span("step_2", parent_id="custom_parent")
        assert span2.parent_id == "custom_parent"

    def test_create_span_with_attributes(self):
        trace = Trace()
        span = trace.create_span("retrieve", collection="spl_docs", top_k=5)
        assert span.attributes == {"collection": "spl_docs", "top_k": 5}

    def test_total_duration_ms_empty(self):
        trace = Trace()
        assert trace.total_duration_ms == 0.0

    def test_total_duration_ms_with_finished_spans(self):
        trace = Trace()
        s1 = trace.create_span("a")
        s1.duration_ms = 100.0
        s2 = trace.create_span("b")
        s2.duration_ms = 200.0
        assert trace.total_duration_ms == 300.0

    def test_total_duration_ms_excludes_unfinished(self):
        trace = Trace()
        s1 = trace.create_span("a")
        s1.duration_ms = 100.0
        trace.create_span("b")  # duration_ms = 0.0 by default
        assert trace.total_duration_ms == 100.0

    def test_has_errors_false(self):
        trace = Trace()
        s1 = trace.create_span("a")
        s1.finish(status=SpanStatus.OK)
        assert trace.has_errors is False

    def test_has_errors_true(self):
        trace = Trace()
        s1 = trace.create_span("a")
        s1.finish(status=SpanStatus.OK)
        s2 = trace.create_span("b")
        s2.finish(status=SpanStatus.ERROR)
        assert trace.has_errors is True

    def test_has_errors_empty(self):
        trace = Trace()
        assert trace.has_errors is False

    def test_to_dict(self):
        trace = Trace(trace_id="t1", user_id="u1", query="test", intent="search")
        s = trace.create_span("classify")
        s.finish()
        d = trace.to_dict()
        assert d["trace_id"] == "t1"
        assert d["user_id"] == "u1"
        assert d["query"] == "test"
        assert d["intent"] == "search"
        assert d["span_count"] == 1
        assert d["has_errors"] is False
        assert isinstance(d["spans"], list)
        assert len(d["spans"]) == 1
        assert isinstance(d["total_duration_ms"], float)

    def test_to_dict_truncates_long_query(self):
        long_query = "x" * 500
        trace = Trace(query=long_query)
        d = trace.to_dict()
        assert len(d["query"]) == 200


# ---------------------------------------------------------------------------
# SLODefinition
# ---------------------------------------------------------------------------

class TestSLODefinition:
    def test_creation(self):
        slo = SLODefinition(name="latency_p95", slo_type=SLOType.LATENCY, target=0.95)
        assert slo.name == "latency_p95"
        assert slo.slo_type == SLOType.LATENCY
        assert slo.target == 0.95
        assert slo.window_seconds == 3600
        assert slo.description == ""
        assert slo.latency_threshold_ms == 0.0

    def test_to_dict(self):
        slo = SLODefinition(
            name="quality",
            slo_type=SLOType.QUALITY,
            target=0.80,
            window_seconds=1800,
            description="Quality target",
            latency_threshold_ms=5000.0,
        )
        d = slo.to_dict()
        assert d["name"] == "quality"
        assert d["type"] == "quality"
        assert d["target"] == 0.80
        assert d["window_seconds"] == 1800
        assert d["description"] == "Quality target"
        assert d["latency_threshold_ms"] == 5000.0


# ---------------------------------------------------------------------------
# SLOStatus
# ---------------------------------------------------------------------------

class TestSLOStatus:
    def test_creation_defaults(self):
        defn = SLODefinition(name="test", slo_type=SLOType.AVAILABILITY, target=0.99)
        status = SLOStatus(definition=defn)
        assert status.current_value == 0.0
        assert status.is_met is True
        assert status.error_budget_remaining == 1.0
        assert status.sample_count == 0
        assert status.window_start > 0

    def test_to_dict(self):
        defn = SLODefinition(name="test_slo", slo_type=SLOType.ERROR_RATE, target=0.01)
        status = SLOStatus(
            definition=defn,
            current_value=0.005,
            is_met=True,
            error_budget_remaining=0.5051,
            sample_count=100,
        )
        d = status.to_dict()
        assert d["name"] == "test_slo"
        assert d["type"] == "error_rate"
        assert d["target"] == 0.01
        assert d["current_value"] == 0.005
        assert d["is_met"] is True
        assert d["error_budget_remaining"] == 0.5051
        assert d["sample_count"] == 100


# ---------------------------------------------------------------------------
# AlertRule — evaluate
# ---------------------------------------------------------------------------

class TestAlertRuleEvaluate:
    def test_greater_than_true(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0, operator=">",
        )
        assert rule.evaluate(15.0) is True

    def test_greater_than_false(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0, operator=">",
        )
        assert rule.evaluate(10.0) is False

    def test_less_than_true(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0, operator="<",
        )
        assert rule.evaluate(5.0) is True

    def test_less_than_false(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0, operator="<",
        )
        assert rule.evaluate(10.0) is False

    def test_greater_equal_true_when_equal(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0, operator=">=",
        )
        assert rule.evaluate(10.0) is True

    def test_greater_equal_true_when_above(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0, operator=">=",
        )
        assert rule.evaluate(15.0) is True

    def test_greater_equal_false_when_below(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0, operator=">=",
        )
        assert rule.evaluate(9.9) is False

    def test_less_equal_true_when_equal(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0, operator="<=",
        )
        assert rule.evaluate(10.0) is True

    def test_less_equal_false_when_above(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0, operator="<=",
        )
        assert rule.evaluate(10.1) is False

    def test_equal_true(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=5.0, operator="==",
        )
        assert rule.evaluate(5.0) is True

    def test_equal_within_tolerance(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=5.0, operator="==",
        )
        assert rule.evaluate(5.0005) is True

    def test_equal_false(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=5.0, operator="==",
        )
        assert rule.evaluate(5.01) is False

    def test_unknown_operator_defaults_to_greater_than(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0, operator="!=",
        )
        # Falls back to ">" operator
        assert rule.evaluate(15.0) is True
        assert rule.evaluate(5.0) is False


# ---------------------------------------------------------------------------
# AlertRule — should_fire and fire
# ---------------------------------------------------------------------------

class TestAlertRuleShouldFire:
    def test_should_fire_true(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.CRITICAL,
            metric="m", threshold=10.0, operator=">", cooldown_seconds=60,
        )
        assert rule.should_fire(15.0) is True

    def test_should_fire_false_condition_not_met(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.CRITICAL,
            metric="m", threshold=10.0, operator=">", cooldown_seconds=60,
        )
        assert rule.should_fire(5.0) is False

    def test_should_fire_false_during_cooldown(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.CRITICAL,
            metric="m", threshold=10.0, operator=">", cooldown_seconds=300,
        )
        rule.last_fired = time.time()  # Just fired
        assert rule.should_fire(15.0) is False

    def test_should_fire_true_after_cooldown_expires(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.CRITICAL,
            metric="m", threshold=10.0, operator=">", cooldown_seconds=5,
        )
        rule.last_fired = time.time() - 10  # Cooldown expired
        assert rule.should_fire(15.0) is True


class TestAlertRuleFire:
    def test_fire_increments_count(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0,
        )
        assert rule.fire_count == 0
        rule.fire()
        assert rule.fire_count == 1
        rule.fire()
        assert rule.fire_count == 2

    def test_fire_updates_last_fired(self):
        rule = AlertRule(
            name="test", condition="c", severity=AlertSeverity.WARNING,
            metric="m", threshold=10.0,
        )
        assert rule.last_fired == 0.0
        before = time.time()
        rule.fire()
        after = time.time()
        assert before <= rule.last_fired <= after


# ---------------------------------------------------------------------------
# FiredAlert
# ---------------------------------------------------------------------------

class TestFiredAlert:
    def test_creation(self):
        alert = FiredAlert(
            alert_name="high_latency",
            severity=AlertSeverity.WARNING,
            metric="latency_p95_ms",
            value=20000.0,
            threshold=15000.0,
            message="Latency too high",
        )
        assert alert.alert_name == "high_latency"
        assert alert.severity == AlertSeverity.WARNING
        assert alert.metric == "latency_p95_ms"
        assert alert.value == 20000.0
        assert alert.threshold == 15000.0
        assert alert.message == "Latency too high"
        assert alert.timestamp > 0


# ---------------------------------------------------------------------------
# ObservabilityManager — tracing
# ---------------------------------------------------------------------------

class TestObservabilityManagerTracing:
    def test_start_trace(self):
        mgr = ObservabilityManager()
        trace = mgr.start_trace(query="test", user_id="u1", intent="search")
        assert trace.query == "test"
        assert trace.user_id == "u1"
        assert trace.intent == "search"
        assert trace.trace_id in mgr._active_traces

    def test_finish_trace(self):
        mgr = ObservabilityManager()
        trace = mgr.start_trace(query="test")
        tid = trace.trace_id
        mgr.finish_trace(tid)
        assert tid not in mgr._active_traces
        assert len(mgr._traces) == 1

    def test_finish_trace_unknown_id(self):
        mgr = ObservabilityManager()
        mgr.finish_trace("nonexistent")  # Should not raise
        assert len(mgr._traces) == 0

    def test_get_trace_active(self):
        mgr = ObservabilityManager()
        trace = mgr.start_trace(query="q")
        found = mgr.get_trace(trace.trace_id)
        assert found is trace

    def test_get_trace_completed(self):
        mgr = ObservabilityManager()
        trace = mgr.start_trace(query="q")
        tid = trace.trace_id
        mgr.finish_trace(tid)
        found = mgr.get_trace(tid)
        assert found is not None
        assert found.trace_id == tid

    def test_get_trace_not_found(self):
        mgr = ObservabilityManager()
        assert mgr.get_trace("missing") is None

    def test_get_recent_traces(self):
        mgr = ObservabilityManager()
        for i in range(5):
            t = mgr.start_trace(query=f"q{i}")
            mgr.finish_trace(t.trace_id)
        recent = mgr.get_recent_traces(limit=3)
        assert len(recent) == 3
        # Returned in reverse order (most recent first)
        assert recent[0]["query"] == "q4"

    def test_get_recent_traces_empty(self):
        mgr = ObservabilityManager()
        assert mgr.get_recent_traces() == []

    def test_finish_trace_records_metrics(self):
        mgr = ObservabilityManager()
        trace = mgr.start_trace(query="q")
        span = trace.create_span("classify")
        span.finish()
        mgr.finish_trace(trace.trace_id)
        assert mgr._counters["traces_total"] == 1
        assert len(mgr._histograms["trace_duration_ms"]) == 1


# ---------------------------------------------------------------------------
# ObservabilityManager — SLO tracking
# ---------------------------------------------------------------------------

class TestObservabilityManagerSLO:
    def test_default_slos_initialized(self):
        mgr = ObservabilityManager()
        assert "response_latency_p95" in mgr._slo_definitions
        assert "response_quality" in mgr._slo_definitions
        assert "availability" in mgr._slo_definitions
        assert "error_rate" in mgr._slo_definitions

    def test_record_slo_data(self):
        mgr = ObservabilityManager()
        mgr.record_slo_data("response_quality", 0.85)
        assert len(mgr._slo_data["response_quality"]) == 1

    def test_record_slo_data_unknown_name_ignored(self):
        mgr = ObservabilityManager()
        mgr.record_slo_data("nonexistent_slo", 1.0)
        assert "nonexistent_slo" not in mgr._slo_data

    def test_get_slo_status_all(self):
        mgr = ObservabilityManager()
        statuses = mgr.get_slo_status()
        assert len(statuses) == 4  # 4 default SLOs

    def test_get_slo_status_specific(self):
        mgr = ObservabilityManager()
        mgr.record_slo_data("response_quality", 0.9)
        statuses = mgr.get_slo_status("response_quality")
        assert len(statuses) == 1
        assert statuses[0].definition.name == "response_quality"
        assert statuses[0].sample_count == 1

    def test_get_slo_status_latency(self):
        mgr = ObservabilityManager()
        # Record latency data: 9 within threshold, 1 over
        for _ in range(9):
            mgr.record_slo_data("response_latency_p95", 5000.0)  # under 10000ms
        mgr.record_slo_data("response_latency_p95", 15000.0)  # over threshold
        statuses = mgr.get_slo_status("response_latency_p95")
        assert statuses[0].sample_count == 10
        assert statuses[0].current_value == pytest.approx(0.9)  # 9/10 within threshold

    def test_get_slo_status_quality(self):
        mgr = ObservabilityManager()
        # 8 good quality (>= 0.5), 2 bad quality (< 0.5)
        for _ in range(8):
            mgr.record_slo_data("response_quality", 0.7)
        for _ in range(2):
            mgr.record_slo_data("response_quality", 0.3)
        statuses = mgr.get_slo_status("response_quality")
        assert statuses[0].current_value == pytest.approx(0.8)  # 8/10 meet quality bar
        assert statuses[0].is_met is True  # target is 0.80

    def test_get_slo_status_availability(self):
        mgr = ObservabilityManager()
        # 99 successes, 1 failure
        for _ in range(99):
            mgr.record_slo_data("availability", 1.0)
        mgr.record_slo_data("availability", 0.0)
        statuses = mgr.get_slo_status("availability")
        assert statuses[0].current_value == pytest.approx(0.99)
        # Target is 0.995, so 0.99 < 0.995 means SLO is NOT met
        assert statuses[0].is_met is False

    def test_get_slo_status_error_rate(self):
        mgr = ObservabilityManager()
        # 95 success, 5 failures -> error_rate = 1 - (95/100) = 0.05
        for _ in range(95):
            mgr.record_slo_data("error_rate", 1.0)
        for _ in range(5):
            mgr.record_slo_data("error_rate", 0.0)
        statuses = mgr.get_slo_status("error_rate")
        assert statuses[0].current_value == pytest.approx(0.05)
        # Error rate SLO: current (0.05) <= target (0.01)? No, so not met
        assert statuses[0].is_met is False

    def test_get_slo_status_no_data_returns_default(self):
        mgr = ObservabilityManager()
        statuses = mgr.get_slo_status("response_quality")
        assert statuses[0].sample_count == 0
        assert statuses[0].is_met is True  # Default


# ---------------------------------------------------------------------------
# ObservabilityManager — alerting
# ---------------------------------------------------------------------------

class TestObservabilityManagerAlerting:
    def test_default_alert_rules_initialized(self):
        mgr = ObservabilityManager()
        assert "high_latency" in mgr._alert_rules
        assert "critical_latency" in mgr._alert_rules
        assert "high_error_rate" in mgr._alert_rules
        assert "low_quality" in mgr._alert_rules
        assert "slo_breach" in mgr._alert_rules

    def test_evaluate_alerts_no_metrics(self):
        mgr = ObservabilityManager()
        fired = mgr.evaluate_alerts()
        assert fired == []

    def test_evaluate_alerts_fires_on_high_latency(self):
        mgr = ObservabilityManager()
        # Record high latency data so P95 exceeds 15000ms
        for _ in range(100):
            mgr.record_histogram("trace_duration_ms", 20000.0)
        mgr._counters["traces_total"] = 100
        fired = mgr.evaluate_alerts()
        alert_names = [a.alert_name for a in fired]
        assert "high_latency" in alert_names
        assert "critical_latency" not in alert_names  # 20000 < 30000

    def test_evaluate_alerts_fires_critical_latency(self):
        mgr = ObservabilityManager()
        for _ in range(100):
            mgr.record_histogram("trace_duration_ms", 35000.0)
        mgr._counters["traces_total"] = 100
        fired = mgr.evaluate_alerts()
        alert_names = [a.alert_name for a in fired]
        assert "critical_latency" in alert_names

    def test_get_fired_alerts(self):
        mgr = ObservabilityManager()
        # Manually add a fired alert
        alert = FiredAlert(
            alert_name="test_alert",
            severity=AlertSeverity.INFO,
            metric="test_metric",
            value=42.0,
            threshold=40.0,
            message="test",
        )
        mgr._fired_alerts.append(alert)
        fired = mgr.get_fired_alerts()
        assert len(fired) == 1
        assert fired[0]["alert_name"] == "test_alert"
        assert fired[0]["severity"] == "info"
        assert fired[0]["value"] == 42.0

    def test_get_fired_alerts_limit(self):
        mgr = ObservabilityManager()
        for i in range(10):
            mgr._fired_alerts.append(FiredAlert(
                alert_name=f"alert_{i}",
                severity=AlertSeverity.WARNING,
                metric="m",
                value=float(i),
                threshold=0.0,
                message=f"msg_{i}",
            ))
        fired = mgr.get_fired_alerts(limit=3)
        assert len(fired) == 3


# ---------------------------------------------------------------------------
# ObservabilityManager — metrics
# ---------------------------------------------------------------------------

class TestObservabilityManagerMetrics:
    def test_increment(self):
        mgr = ObservabilityManager()
        mgr.increment("requests")
        mgr.increment("requests")
        mgr.increment("requests", 3)
        assert mgr._counters["requests"] == 5

    def test_set_gauge(self):
        mgr = ObservabilityManager()
        mgr.set_gauge("active_users", 42.0)
        assert mgr._gauges["active_users"] == 42.0
        mgr.set_gauge("active_users", 10.0)
        assert mgr._gauges["active_users"] == 10.0

    def test_record_histogram(self):
        mgr = ObservabilityManager()
        mgr.record_histogram("latency", 100.0)
        mgr.record_histogram("latency", 200.0)
        assert mgr._histograms["latency"] == [100.0, 200.0]

    def test_record_histogram_truncation(self):
        mgr = ObservabilityManager()
        for i in range(5100):
            mgr.record_histogram("big", float(i))
        # After exceeding 5000, truncated to last 2500
        assert len(mgr._histograms["big"]) <= 5000

    def test_get_metrics_summary(self):
        mgr = ObservabilityManager()
        mgr.increment("req_count", 10)
        mgr.set_gauge("cpu", 55.5)
        mgr.record_histogram("latency", 100.0)
        mgr.record_histogram("latency", 200.0)

        summary = mgr.get_metrics_summary()
        assert summary["counters"]["req_count"] == 10
        assert summary["gauges"]["cpu"] == 55.5
        assert "latency" in summary["histograms"]
        lat = summary["histograms"]["latency"]
        assert lat["count"] == 2
        assert lat["avg"] == 150.0
        assert lat["min"] == 100.0
        assert lat["max"] == 200.0

    def test_get_metrics_summary_empty(self):
        mgr = ObservabilityManager()
        summary = mgr.get_metrics_summary()
        assert summary["counters"] == {}
        assert summary["gauges"] == {}
        assert summary["histograms"] == {}


# ---------------------------------------------------------------------------
# ObservabilityManager — dashboard
# ---------------------------------------------------------------------------

class TestObservabilityManagerDashboard:
    def test_get_dashboard_data_structure(self):
        mgr = ObservabilityManager()
        data = mgr.get_dashboard_data()
        assert "timestamp" in data
        assert "tracing" in data
        assert "slos" in data
        assert "alerts" in data
        assert "metrics" in data

    def test_get_dashboard_data_tracing_section(self):
        mgr = ObservabilityManager()
        trace = mgr.start_trace(query="dashboard test")
        data = mgr.get_dashboard_data()
        assert data["tracing"]["active_traces"] == 1
        assert data["tracing"]["completed_traces"] == 0
        mgr.finish_trace(trace.trace_id)
        data = mgr.get_dashboard_data()
        assert data["tracing"]["active_traces"] == 0
        assert data["tracing"]["completed_traces"] == 1

    def test_get_dashboard_data_slos_section(self):
        mgr = ObservabilityManager()
        data = mgr.get_dashboard_data()
        assert "definitions" in data["slos"]
        assert "status" in data["slos"]
        assert "all_met" in data["slos"]
        assert len(data["slos"]["definitions"]) == 4

    def test_get_dashboard_data_alerts_section(self):
        mgr = ObservabilityManager()
        data = mgr.get_dashboard_data()
        assert "rules" in data["alerts"]
        assert "recent_fired" in data["alerts"]
        assert len(data["alerts"]["rules"]) == 5  # 5 default alert rules
