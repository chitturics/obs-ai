"""OpenTelemetry compatibility layer — provides trace helpers with graceful fallback.

If chat_app.otel_tracing is available, uses real OTel.
Otherwise, provides no-op stubs so callers never need try/except.
"""

try:
    from chat_app.otel_tracing import (
        init_otel, trace_span, trace_llm_call, trace_retrieval,
        trace_agent, trace_pipeline_stage, AIAttributes,
    )
    init_otel()
except ImportError:
    from contextlib import contextmanager as _cm

    @_cm
    def trace_span(name, attributes=None, kind=None):
        yield None

    trace_llm_call = lambda model, provider="ollama": trace_span(f"llm.{model}")
    trace_retrieval = lambda strategy, collections="": trace_span(f"rag.{strategy}")
    trace_agent = lambda name, strategy="": trace_span(f"agent.{name}")
    trace_pipeline_stage = lambda stage, intent="", profile="": trace_span(f"pipeline.{stage}")

    class AIAttributes:
        LLM_MODEL = "gen_ai.request.model"
        LLM_RESPONSE_CHARS = "gen_ai.response.chars"
        RAG_CHUNKS_RETRIEVED = "rag.chunks.retrieved"
        RAG_SOURCE = "rag.source"
        RAG_CACHE_HIT = "rag.cache_hit"
        RAG_MODE = "rag.mode"
        AGENT_NAME = "agent.name"
        AGENT_STRATEGY = "agent.strategy"
        AGENT_ITERATIONS = "agent.iterations"
        AGENT_QUALITY = "agent.quality_score"
        PIPELINE_INTENT = "pipeline.intent"
        PIPELINE_PROFILE = "pipeline.profile"
        PIPELINE_REQUEST_ID = "pipeline.request_id"
        PIPELINE_DURATION_MS = "pipeline.duration_ms"
        PIPELINE_SUCCESS = "pipeline.success"
        QUALITY_SCORE = "quality.score"
        QUALITY_CONFIDENCE = "quality.confidence"
        USER_ID = "user.id"
        SESSION_ID = "session.id"
