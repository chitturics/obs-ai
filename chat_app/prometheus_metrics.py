"""
Prometheus metric definitions for the Chainlit Splunk Assistant.

Bridges the existing in-memory Metrics class with Prometheus client.
"""
import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram, Gauge, Info, REGISTRY
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.info("prometheus_client not available, metrics export disabled")


def _safe_counter(name, desc, labels):
    """Create a Counter, returning existing one if already registered."""
    try:
        return Counter(name, desc, labels)
    except ValueError:
        existing = REGISTRY._names_to_collectors.get(name) or REGISTRY._names_to_collectors.get(name + "_total")
        if existing is not None:
            return existing
        raise


def _safe_histogram(name, desc, labels, buckets=None):
    """Create a Histogram, returning existing one if already registered."""
    kwargs = {"buckets": buckets} if buckets else {}
    try:
        return Histogram(name, desc, labels, **kwargs)
    except ValueError:
        existing = REGISTRY._names_to_collectors.get(name)
        if existing is not None:
            return existing
        raise


def _safe_gauge(name, desc, labels=None):
    """Create a Gauge, returning existing one if already registered."""
    args = [name, desc] + ([labels] if labels else [])
    try:
        return Gauge(*args)
    except ValueError:
        existing = REGISTRY._names_to_collectors.get(name)
        if existing is not None:
            return existing
        raise

if PROMETHEUS_AVAILABLE:
    # Query metrics
    QUERY_TOTAL = _safe_counter("chainlit_queries_total", "Total number of queries processed", ["intent", "profile"])
    QUERY_LATENCY = _safe_histogram("chainlit_query_latency_seconds", "Query processing latency in seconds", ["intent"], buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0])

    # LLM metrics
    LLM_CALLS = _safe_counter("chainlit_llm_calls_total", "Total LLM invocations", ["model", "status"])
    LLM_LATENCY = _safe_histogram("chainlit_llm_latency_seconds", "LLM call latency in seconds", [], buckets=[1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0])

    # Cache metrics
    CACHE_HITS = _safe_counter("chainlit_cache_hits_total", "Cache hit count", [])
    CACHE_MISSES = _safe_counter("chainlit_cache_misses_total", "Cache miss count", [])

    # Vector store metrics
    VECTOR_SEARCH_LATENCY = _safe_histogram("chainlit_vector_search_seconds", "Vector store search latency", ["collection"], buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0])
    VECTOR_RESULTS_COUNT = _safe_histogram("chainlit_vector_results_count", "Number of results returned from vector search", [], buckets=[0, 5, 10, 20, 50, 100])

    # Circuit breaker metrics
    CIRCUIT_STATE = _safe_gauge("chainlit_circuit_breaker_state", "Circuit breaker state (0=closed, 1=half_open, 2=open)", ["service"])

    # Pipeline stage latency (per-stage breakdown)
    PIPELINE_STAGE_LATENCY = _safe_histogram("chainlit_pipeline_stage_seconds", "Per-stage pipeline latency in seconds", ["stage"], buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0])

    # Agent dispatch metrics
    AGENT_DISPATCH_TOTAL = _safe_counter("chainlit_agent_dispatches_total", "Total agent dispatches", ["agent_name", "department", "status"])
    AGENT_DISPATCH_LATENCY = _safe_histogram("chainlit_agent_dispatch_seconds", "Agent dispatch latency in seconds", ["agent_name"], buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0])
    AGENT_QUALITY_SCORE = _safe_histogram("chainlit_agent_quality_score", "Agent dispatch quality scores", ["agent_name"], buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])

    # Skill execution metrics
    SKILL_EXECUTION_TOTAL = _safe_counter("chainlit_skill_executions_total", "Total skill executions", ["skill_name", "status"])

    # SLO and alert metrics
    SLO_STATUS = _safe_gauge("chainlit_slo_status", "SLO current value (1=met, 0=breached)", ["slo_name", "slo_type"])
    SLO_ERROR_BUDGET = _safe_gauge("chainlit_slo_error_budget_remaining", "SLO error budget remaining (0-1)", ["slo_name"])
    ALERTS_FIRED_TOTAL = _safe_counter("chainlit_alerts_fired_total", "Total alerts fired", ["alert_name", "severity"])
    ALERTS_ACTIVE = _safe_gauge("chainlit_alerts_active", "Currently active alerts count", ["severity"])

    # Skill execution latency
    SKILL_EXECUTION_LATENCY = _safe_histogram("chainlit_skill_execution_seconds", "Skill execution latency in seconds", ["skill_name"], buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])

    # Service health gauges (aligned with Prometheus alert rules)
    SERVICE_UP = _safe_gauge("chainlit_service_up", "Service availability (1=up, 0=down)", ["service"])

    # LLM cost tracking
    LLM_COST = _safe_counter("chainlit_llm_cost_usd", "Cumulative LLM cost in USD", ["model", "purpose"])

    # Document ingestion metrics
    INGESTION_DOCS_TOTAL = _safe_counter("chainlit_ingestion_documents_total", "Total documents processed during ingestion", ["collection", "status"])
    INGESTION_LATENCY = _safe_histogram("chainlit_ingestion_latency_seconds", "Document ingestion latency in seconds", ["collection"], buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0])
    INGESTION_CHUNKS_TOTAL = _safe_counter("chainlit_ingestion_chunks_total", "Total chunks created during ingestion", ["collection"])

    # Orchestration metrics
    ORCHESTRATION_TOTAL = _safe_counter("chainlit_orchestration_total", "Total orchestration executions", ["strategy", "status"])
    ORCHESTRATION_LATENCY = _safe_histogram("chainlit_orchestration_latency_seconds", "Orchestration execution latency in seconds", ["strategy"], buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0])
    ORCHESTRATION_AGENTS_USED = _safe_histogram("chainlit_orchestration_agents_used", "Number of agents used per orchestration", ["strategy"], buckets=[1, 2, 3, 5, 8, 10])

    # LLM cost metrics
    LLM_COST_USD = _safe_counter("chainlit_llm_cost_usd_total", "Total estimated LLM cost in USD", ["model", "purpose"])
    LLM_TOKENS_INPUT = _safe_counter("chainlit_llm_tokens_input_total", "Total input tokens", ["model"])
    LLM_TOKENS_OUTPUT = _safe_counter("chainlit_llm_tokens_output_total", "Total output tokens", ["model"])

    # Guardrail metrics
    GUARDRAIL_TOTAL = _safe_counter("chainlit_guardrail_checks_total", "Total guardrail checks", ["layer", "result"])
    GUARDRAIL_BLOCKED = _safe_counter("chainlit_guardrail_blocked_total", "Total blocked by guardrails", ["layer"])
    GUARDRAIL_PII_DETECTED = _safe_counter("chainlit_guardrail_pii_detected_total", "Total PII detections", ["layer"])
    GUARDRAIL_INJECTION_DETECTED = _safe_counter("chainlit_guardrail_injection_detected_total", "Prompt injection detections", [])

    # Application info
    try:
        APP_INFO = Info("chainlit_app", "Application information")
    except ValueError:
        APP_INFO = REGISTRY._names_to_collectors.get("chainlit_app_info")


def record_query(intent: str, profile: str, latency: float):
    """Record a query metric."""
    if not PROMETHEUS_AVAILABLE:
        return
    QUERY_TOTAL.labels(intent=intent, profile=profile).inc()
    QUERY_LATENCY.labels(intent=intent).observe(latency)


def record_llm_call(model: str, status: str, latency: float):
    """Record an LLM call metric."""
    if not PROMETHEUS_AVAILABLE:
        return
    LLM_CALLS.labels(model=model, status=status).inc()
    LLM_LATENCY.observe(latency)


def record_cache_hit():
    """Record a cache hit."""
    if PROMETHEUS_AVAILABLE:
        CACHE_HITS.inc()


def record_cache_miss():
    """Record a cache miss."""
    if PROMETHEUS_AVAILABLE:
        CACHE_MISSES.inc()


def record_vector_search(collection: str, latency: float, result_count: int):
    """Record vector store search metrics."""
    if not PROMETHEUS_AVAILABLE:
        return
    VECTOR_SEARCH_LATENCY.labels(collection=collection).observe(latency)
    VECTOR_RESULTS_COUNT.observe(result_count)


def record_pipeline_stages(stage_timings: dict):
    """Record per-stage pipeline latency from LatencyTracker.to_dict()."""
    if not PROMETHEUS_AVAILABLE:
        return
    for stage, ms in stage_timings.items():
        PIPELINE_STAGE_LATENCY.labels(stage=stage).observe(ms / 1000.0)


def record_agent_dispatch(
    agent_name: str, department: str, success: bool,
    latency: float, quality_score: float = None,
):
    """Record agent dispatch metrics."""
    if not PROMETHEUS_AVAILABLE:
        return
    status = "success" if success else "failure"
    AGENT_DISPATCH_TOTAL.labels(
        agent_name=agent_name, department=department, status=status,
    ).inc()
    AGENT_DISPATCH_LATENCY.labels(agent_name=agent_name).observe(latency)
    if quality_score is not None:
        AGENT_QUALITY_SCORE.labels(agent_name=agent_name).observe(quality_score)


def record_skill_execution(skill_name: str, success: bool):
    """Record skill execution metrics."""
    if not PROMETHEUS_AVAILABLE:
        return
    status = "success" if success else "failure"
    SKILL_EXECUTION_TOTAL.labels(skill_name=skill_name, status=status).inc()


def record_slo_status(slo_name: str, slo_type: str, is_met: bool, error_budget: float):
    """Record SLO status as Prometheus gauge."""
    if not PROMETHEUS_AVAILABLE:
        return
    SLO_STATUS.labels(slo_name=slo_name, slo_type=slo_type).set(1.0 if is_met else 0.0)
    SLO_ERROR_BUDGET.labels(slo_name=slo_name).set(error_budget)


def record_alert_fired(alert_name: str, severity: str):
    """Record a fired alert."""
    if not PROMETHEUS_AVAILABLE:
        return
    ALERTS_FIRED_TOTAL.labels(alert_name=alert_name, severity=severity).inc()


def record_active_alerts(info_count: int, warning_count: int, critical_count: int):
    """Update active alert gauges."""
    if not PROMETHEUS_AVAILABLE:
        return
    ALERTS_ACTIVE.labels(severity="info").set(info_count)
    ALERTS_ACTIVE.labels(severity="warning").set(warning_count)
    ALERTS_ACTIVE.labels(severity="critical").set(critical_count)


def record_skill_execution_latency(skill_name: str, latency: float):
    """Record skill execution latency."""
    if not PROMETHEUS_AVAILABLE:
        return
    SKILL_EXECUTION_LATENCY.labels(skill_name=skill_name).observe(latency)


def record_ingestion(collection: str, doc_count: int, chunk_count: int,
                     latency: float, success: bool = True):
    """Record document ingestion metrics."""
    if not PROMETHEUS_AVAILABLE:
        return
    status = "success" if success else "failure"
    INGESTION_DOCS_TOTAL.labels(collection=collection, status=status).inc(doc_count)
    INGESTION_CHUNKS_TOTAL.labels(collection=collection).inc(chunk_count)
    INGESTION_LATENCY.labels(collection=collection).observe(latency)


def record_orchestration(strategy: str, success: bool, latency: float, agents_used: int = 1):
    """Record orchestration execution metrics."""
    if not PROMETHEUS_AVAILABLE:
        return
    status = "success" if success else "failure"
    ORCHESTRATION_TOTAL.labels(strategy=strategy, status=status).inc()
    ORCHESTRATION_LATENCY.labels(strategy=strategy).observe(latency)
    ORCHESTRATION_AGENTS_USED.labels(strategy=strategy).observe(agents_used)


def record_llm_cost_metric(model: str, purpose: str, cost_usd: float,
                           input_tokens: int, output_tokens: int):
    """Record LLM cost as Prometheus metrics."""
    if not PROMETHEUS_AVAILABLE:
        return
    LLM_COST_USD.labels(model=model, purpose=purpose).inc(cost_usd)
    LLM_TOKENS_INPUT.labels(model=model).inc(input_tokens)
    LLM_TOKENS_OUTPUT.labels(model=model).inc(output_tokens)


def record_guardrail_event(layer: str, blocked: bool = False,
                           pii: bool = False, injection: bool = False):
    """Record a guardrail check event."""
    if not PROMETHEUS_AVAILABLE:
        return
    result = "blocked" if blocked else "passed"
    GUARDRAIL_TOTAL.labels(layer=layer, result=result).inc()
    if blocked:
        GUARDRAIL_BLOCKED.labels(layer=layer).inc()
    if pii:
        GUARDRAIL_PII_DETECTED.labels(layer=layer).inc()
    if injection:
        GUARDRAIL_INJECTION_DETECTED.inc()


def set_app_info(version: str, environment: str, model: str):
    """Set application info metric."""
    if PROMETHEUS_AVAILABLE:
        APP_INFO.info({
            "version": version,
            "environment": environment,
            "llm_model": model,
        })


def record_service_health(service: str, is_up: bool):
    """Record service availability gauge (aligned with Prometheus alert rules).

    Called by health_monitor during periodic health checks.
    Maps directly to chainlit_service_up{service="..."} used in alert_rules.yml.
    """
    if PROMETHEUS_AVAILABLE:
        SERVICE_UP.labels(service=service).set(1 if is_up else 0)


def record_error_budget(slo_name: str, budget_remaining: float):
    """Record SLO error budget remaining (0.0 to 1.0)."""
    if PROMETHEUS_AVAILABLE:
        SLO_ERROR_BUDGET.labels(slo_name=slo_name).set(budget_remaining)
