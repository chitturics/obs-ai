"""Tests for OpenTelemetry tracing wrapper."""
import pytest
from chat_app.otel_tracer import trace_span, _NoOpSpan, init_otel, is_otel_available


class TestTraceSpan:
    def test_noop_span_basic(self):
        with trace_span("test_op") as span:
            assert span is not None

    def test_noop_span_with_attributes(self):
        with trace_span("test_op", {"key": "value", "count": 42}) as span:
            assert span is not None

    def test_noop_span_set_attribute(self):
        with trace_span("test_op") as span:
            if hasattr(span, 'set_attribute'):
                span.set_attribute("extra", "data")

    def test_noop_span_duration(self):
        import time
        with trace_span("test_op") as span:
            time.sleep(0.01)
        if hasattr(span, 'duration_ms'):
            assert span.duration_ms > 0

    def test_noop_span_exception(self):
        with pytest.raises(ValueError):
            with trace_span("test_op") as span:
                raise ValueError("test error")


class TestNoOpSpan:
    def test_init(self):
        span = _NoOpSpan("test", {"a": 1}, 0.0)
        assert span.name == "test"
        assert span.attributes == {"a": 1}

    def test_set_attribute(self):
        span = _NoOpSpan("test", {}, 0.0)
        span.set_attribute("key", "value")
        assert span.attributes["key"] == "value"

    def test_add_event(self):
        span = _NoOpSpan("test", {}, 0.0)
        span.add_event("event_name")  # Should not raise


class TestInitOtel:
    def test_init_without_sdk(self):
        # May or may not have SDK installed — just verify it doesn't crash
        result = init_otel(service_name="test-service")
        assert isinstance(result, bool)

    def test_is_available(self):
        result = is_otel_available()
        assert isinstance(result, bool)
