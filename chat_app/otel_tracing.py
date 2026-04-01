"""OpenTelemetry tracing for ObsAI pipeline stages."""
import os
import logging
from contextlib import contextmanager
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.semconv.resource import ResourceAttributes
    from opentelemetry.trace import StatusCode, Status
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False

# AI-specific span attribute keys (OTel GenAI draft conventions)
class AIAttributes:
    LLM_MODEL = "gen_ai.request.model"
    LLM_PROVIDER = "gen_ai.system"
    LLM_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    LLM_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    LLM_TOTAL_TOKENS = "gen_ai.usage.total_tokens"
    LLM_COST_USD = "gen_ai.cost.usd"
    LLM_TEMPERATURE = "gen_ai.request.temperature"
    LLM_MAX_TOKENS = "gen_ai.request.max_tokens"
    LLM_STOP_REASON = "gen_ai.response.finish_reason"
    LLM_RESPONSE_CHARS = "gen_ai.response.chars"
    RAG_STRATEGY = "rag.strategy"
    RAG_COLLECTIONS = "rag.collections"
    RAG_CHUNKS_RETRIEVED = "rag.chunks.retrieved"
    RAG_CHUNKS_USED = "rag.chunks.used"
    RAG_RELEVANCE_AVG = "rag.relevance.avg"
    RAG_COVERAGE = "rag.coverage"
    RAG_SOURCE = "rag.source"
    RAG_CACHE_HIT = "rag.cache_hit"
    RAG_MODE = "rag.mode"
    AGENT_NAME = "agent.name"
    AGENT_DEPARTMENT = "agent.department"
    AGENT_STRATEGY = "agent.strategy"
    AGENT_STEPS = "agent.steps"
    AGENT_QUALITY = "agent.quality_score"
    AGENT_ITERATIONS = "agent.iterations"
    AGENT_FALLBACK = "agent.fallback_used"
    PIPELINE_INTENT = "pipeline.intent"
    PIPELINE_PROFILE = "pipeline.profile"
    PIPELINE_STAGE = "pipeline.stage"
    PIPELINE_DURATION_MS = "pipeline.duration_ms"
    PIPELINE_SUCCESS = "pipeline.success"
    PIPELINE_REQUEST_ID = "pipeline.request_id"
    PIPELINE_USER_QUERY = "pipeline.user_query"
    QUALITY_SCORE = "quality.score"
    QUALITY_CONFIDENCE = "quality.confidence"
    QUALITY_LABEL = "quality.label"
    USER_ID = "user.id"
    SESSION_ID = "session.id"
    REQUEST_ID = "request.id"

_tracer = None
_initialized = False
_memory_exporter = None


def init_otel(service_name: str = "", endpoint: str = "", max_spans: int = 500) -> bool:
    global _tracer, _initialized, _memory_exporter
    if _initialized:
        return _tracer is not None
    _initialized = True
    if not HAS_OTEL:
        return False

    _svc, _ep, _console = service_name, endpoint, False
    try:
        from chat_app.settings import get_settings
        otel_cfg = getattr(get_settings(), "otel", None)
        if otel_cfg:
            if not otel_cfg.enabled:
                return False
            _svc = _svc or otel_cfg.service_name
            _ep = _ep or otel_cfg.endpoint
            _console = otel_cfg.console_export
            max_spans = otel_cfg.max_spans
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    _svc = _svc or os.getenv("OTEL_SERVICE_NAME", "obsai-app")
    _ep = _ep or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    _console = _console or os.getenv("OTEL_TRACE_CONSOLE", "").lower() == "true"

    try:
        resource = Resource.create({
            ResourceAttributes.SERVICE_NAME: _svc,
            ResourceAttributes.SERVICE_VERSION: "3.5.1",
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        })
        provider = TracerProvider(resource=resource)

        if _ep:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_ep)))
            except ImportError:
                try:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExp
                    provider.add_span_processor(BatchSpanProcessor(HTTPExp(endpoint=_ep)))
                except ImportError:
                    pass

        if _console:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        from chat_app.otel_memory_exporter import InMemorySpanExporter
        import chat_app.otel_memory_exporter as _mem_mod
        _memory_exporter = InMemorySpanExporter(max_spans=max_spans)
        _mem_mod._memory_exporter_instance = _memory_exporter
        provider.add_span_processor(BatchSpanProcessor(_memory_exporter))

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("obsai.pipeline", "3.5.1")
        logger.info("[OTEL] Initialized: service=%s spans=%d", _svc, max_spans)
        return True
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning("[OTEL] Init failed: %s", e)
        return False


def get_tracer():
    if not _initialized and HAS_OTEL:
        init_otel()
    return _tracer

def get_memory_exporter():
    return _memory_exporter

def is_otel_available() -> bool:
    return _tracer is not None


class _NoOpSpan:
    __slots__ = ("name", "attributes", "duration_ms")
    def __init__(self, name="", attributes=None, start=0.0):
        self.name = name
        self.attributes = dict(attributes or {})
        self.duration_ms = 0.0
    def set_attribute(self, key, value): self.attributes[key] = value
    def add_event(self, *a, **kw): pass
    def set_status(self, *a): pass
    def record_exception(self, *a): pass


@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None, kind=None):
    tracer = get_tracer()
    if tracer is not None:
        with tracer.start_as_current_span(name, kind=kind or trace.SpanKind.INTERNAL) as span:
            for k, v in (attributes or {}).items():
                if v is not None:
                    span.set_attribute(k, v if isinstance(v, (int, float, bool)) else str(v))
            try:
                yield span
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise
    else:
        yield _NoOpSpan(name, attributes)


def trace_kind(kind: str, name: str, **attrs):
    """Generic traced span for llm/retrieval/agent/pipeline operations."""
    prefix_map = {"llm": "gen_ai", "retrieval": "rag", "agent": "agent", "pipeline": "pipeline"}
    prefix = prefix_map.get(kind, kind)
    return trace_span(f"{prefix}.{name}", attrs)

# Convenience wrappers preserving backward compatibility
def trace_llm_call(model: str, provider: str = "ollama"):
    return trace_kind("llm", f"{provider}.{model}",
                       **{AIAttributes.LLM_MODEL: model, AIAttributes.LLM_PROVIDER: provider})

def trace_retrieval(strategy: str, collections: str = ""):
    return trace_kind("retrieval", strategy,
                       **{AIAttributes.RAG_STRATEGY: strategy, AIAttributes.RAG_COLLECTIONS: collections})

def trace_agent(name: str, strategy: str = ""):
    return trace_kind("agent", name,
                       **{AIAttributes.AGENT_NAME: name, AIAttributes.AGENT_STRATEGY: strategy})

def trace_pipeline_stage(stage: str, intent: str = "", profile: str = ""):
    return trace_kind("pipeline", stage,
                       **{AIAttributes.PIPELINE_STAGE: stage, AIAttributes.PIPELINE_INTENT: intent,
                          AIAttributes.PIPELINE_PROFILE: profile})
