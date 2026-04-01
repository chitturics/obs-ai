"""OpenTelemetry tracing wrapper -- backward-compatible shim."""
from chat_app.otel_tracing import (  # noqa: F401
    AIAttributes,
    HAS_OTEL,
    _NoOpSpan,
    get_memory_exporter,
    get_tracer,
    init_otel,
    is_otel_available,
    trace_agent,
    trace_kind,
    trace_llm_call,
    trace_pipeline_stage,
    trace_retrieval,
    trace_span,
)
