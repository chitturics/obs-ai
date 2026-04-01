"""
Internal Health Monitoring & Observability — Self-monitoring for the AI assistant.

Provides comprehensive health monitoring:
1. Service health checks (Postgres, Ollama, ChromaDB, Redis, Search Optimizer)
2. Internal metrics collection (response quality, latency, throughput)
3. Self-healing capabilities (auto-recovery, circuit breakers)
4. Prometheus metrics exposition
5. Learning effectiveness tracking
6. Grafana dashboard configuration

"Eat your own dog food" — an observability assistant should have excellent observability.
"""
import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _record_service_metric(service: str, is_up: bool) -> None:
    """Record service health to Prometheus (aligned with alert_rules.yml)."""
    try:
        from chat_app.prometheus_metrics import record_service_health
        record_service_health(service, is_up)
    except Exception as _exc:  # broad catch — resilience against all failures
        logger.debug("Prometheus metrics unavailable: %s", _exc)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class ServiceHealth:
    """Health status of a single service."""
    name: str
    status: str = "unknown"  # healthy, degraded, unhealthy, unknown
    latency_ms: float = 0.0
    last_check: str = ""
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemHealth:
    """Aggregate system health."""
    overall: str = "unknown"
    services: List[ServiceHealth] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    learning: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""


@dataclass
class HealthAlert:
    """A health alert to surface to admins."""
    severity: str  # info, warning, critical
    service: str
    message: str
    timestamp: str = ""
    auto_action: Optional[str] = None


# ---------------------------------------------------------------------------
# Service Health Checks
# ---------------------------------------------------------------------------

async def check_postgres(engine) -> ServiceHealth:
    """Check PostgreSQL database connectivity and performance."""
    health = ServiceHealth(name="postgres")
    start = time.monotonic()
    try:
        from sqlalchemy import text
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.scalar()

            # Get connection pool stats
            pool = engine.pool
            health.details = {
                "pool_size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
            }

        health.status = "healthy"
        health.latency_ms = (time.monotonic() - start) * 1000
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        health.status = "unhealthy"
        health.error = str(exc)
        health.latency_ms = (time.monotonic() - start) * 1000

    health.last_check = datetime.now(timezone.utc).isoformat()
    _record_service_metric("postgres", health.status == "healthy")
    return health


async def check_ollama() -> ServiceHealth:
    """Check Ollama LLM service availability and loaded models."""
    health = ServiceHealth(name="ollama")
    start = time.monotonic()
    try:
        import httpx
        from chat_app.settings import get_settings
        base_url = get_settings().ollama.base_url

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()

            models = [m.get("name", "") for m in data.get("models", [])]
            health.details = {
                "models_loaded": len(models),
                "model_names": models[:5],
                "expected_model": get_settings().ollama.model,
                "model_available": get_settings().ollama.model in models or any(
                    get_settings().ollama.model in m for m in models
                ),
            }
            health.status = "healthy" if health.details["model_available"] else "degraded"
            if not health.details["model_available"]:
                health.error = f"Expected model '{get_settings().ollama.model}' not loaded"

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        health.status = "unhealthy"
        health.error = str(exc)

    health.latency_ms = (time.monotonic() - start) * 1000
    health.last_check = datetime.now(timezone.utc).isoformat()
    _record_service_metric("ollama", health.status == "healthy")
    return health


async def check_chromadb() -> ServiceHealth:
    """Check ChromaDB vector store availability and collection stats."""
    health = ServiceHealth(name="chromadb")
    start = time.monotonic()
    try:
        import httpx
        from chat_app.settings import get_settings
        chroma_url = get_settings().chroma.http_url

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{chroma_url}/api/v2/heartbeat")
            resp.raise_for_status()

            # Get collection count
            try:
                coll_resp = await client.get(f"{chroma_url}/api/v1/collections")
                if coll_resp.status_code == 200:
                    collections = coll_resp.json()
                    health.details["collection_count"] = len(collections) if isinstance(collections, list) else 0
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)  # was: pass

            health.status = "healthy"

    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        health.status = "unhealthy"
        health.error = str(exc)

    health.latency_ms = (time.monotonic() - start) * 1000
    health.last_check = datetime.now(timezone.utc).isoformat()
    _record_service_metric("chromadb", health.status == "healthy")
    return health


async def check_redis() -> ServiceHealth:
    """Check Redis cache availability."""
    health = ServiceHealth(name="redis")
    start = time.monotonic()
    try:
        import redis.asyncio as aioredis  # noqa: F811 — must be before early return
    except ImportError:
        aioredis = None  # type: ignore
    try:
        from chat_app.settings import get_settings
        settings = get_settings()

        if not settings.cache.enabled:
            health.status = "healthy"
            health.details = {"enabled": False, "note": "Cache disabled"}
            health.last_check = datetime.now(timezone.utc).isoformat()
            _record_service_metric("redis", health.status == "healthy")
            return health

        r = aioredis.Redis(
            host=settings.cache.host,
            port=settings.cache.port,
            password=settings.cache.password,
        )
        pong = await r.ping()
        info = await r.info("memory")
        await r.aclose()

        health.status = "healthy" if pong else "unhealthy"
        health.details = {
            "enabled": True,
            "used_memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
            "connected_clients": info.get("connected_clients", 0),
        }

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        health.status = "degraded"  # Redis is optional
        health.error = str(exc)

    health.latency_ms = (time.monotonic() - start) * 1000
    health.last_check = datetime.now(timezone.utc).isoformat()
    return health


async def check_search_optimizer() -> ServiceHealth:
    """Check Search Optimizer microservice."""
    health = ServiceHealth(name="search_optimizer")
    start = time.monotonic()
    try:
        import httpx
        from chat_app.settings import get_settings
        opt_url = get_settings().search_optimizer.url

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{opt_url}/health")
            resp.raise_for_status()
            data = resp.json()
            health.status = "healthy" if data.get("status") in ("healthy", "ok") else "degraded"
            health.details = data

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        health.status = "degraded"  # Optimizer is optional
        health.error = str(exc)

    health.latency_ms = (time.monotonic() - start) * 1000
    health.last_check = datetime.now(timezone.utc).isoformat()
    _record_service_metric("search_optimizer", health.status == "healthy")
    return health


async def check_docling() -> ServiceHealth:
    """Check Docling document conversion sidecar."""
    import httpx  # must be before early return to avoid UnboundLocalError
    health = ServiceHealth(name="docling")
    start = time.monotonic()
    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        if not settings.docling.enabled:
            health.status = "disabled"
            health.details = {"reason": "Docling not enabled in config"}
            health.latency_ms = (time.monotonic() - start) * 1000
            health.last_check = datetime.now(timezone.utc).isoformat()
            _record_service_metric("docling", health.status == "healthy")
            return health


        base_url = settings.docling.base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/health")
            resp.raise_for_status()
            data = resp.json()
            health.status = "healthy" if data.get("status") in ("healthy", "ok", True) else "degraded"
            health.details = data

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        health.status = "degraded"  # Docling is optional
        health.error = str(exc)

    health.latency_ms = (time.monotonic() - start) * 1000
    health.last_check = datetime.now(timezone.utc).isoformat()
    _record_service_metric("docling", health.status == "healthy")
    return health


async def check_disk_usage() -> ServiceHealth:
    """Check disk usage on the root filesystem.

    Returns warning status if usage > 80%, critical/unhealthy if > 90%.
    """
    health = ServiceHealth(name="disk")
    start = time.monotonic()
    try:
        usage = shutil.disk_usage("/")
        used_pct = (usage.used / usage.total) * 100 if usage.total else 0
        health.details = {
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "used_gb": round(usage.used / (1024 ** 3), 2),
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "used_percent": round(used_pct, 1),
        }
        if used_pct > 90:
            health.status = "unhealthy"
            health.error = f"Disk usage critical: {used_pct:.1f}% (>90%)"
        elif used_pct > 80:
            health.status = "degraded"
            health.error = f"Disk usage warning: {used_pct:.1f}% (>80%)"
        else:
            health.status = "healthy"
    except (OSError, ValueError) as exc:
        health.status = "unknown"
        health.error = str(exc)

    health.latency_ms = (time.monotonic() - start) * 1000
    health.last_check = datetime.now(timezone.utc).isoformat()
    return health


# ---------------------------------------------------------------------------
# Internal Metrics Collection
# ---------------------------------------------------------------------------

class InternalMetrics:
    """Collect and expose internal assistant metrics with Redis persistence."""

    _instance = None
    _REDIS_KEY = "obsai:metrics:counters"
    _REDIS_GAUGES_KEY = "obsai:metrics:gauges"
    _PERSIST_INTERVAL = 10  # Persist to Redis every N increments

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._counters = {
            "queries_total": 0,
            "queries_success": 0,
            "queries_failed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "tool_executions": 0,
            "tool_failures": 0,
            "learning_cycles": 0,
            "qa_pairs_generated": 0,
            "facts_learned": 0,
            "documents_ingested": 0,
        }
        self._gauges = {
            "avg_response_latency_ms": 0.0,
            "avg_confidence_score": 0.0,
            "avg_quality_score": 0.0,
            "active_sessions": 0,
            "collections_count": 0,
        }
        self._latencies = []  # Rolling window of last 100 latencies
        self._qualities = []   # Rolling window of last 100 quality scores
        self._dirty_count = 0
        self._redis = None
        self._restore_from_redis()

    def _get_redis(self):
        """Get synchronous Redis client for counter persistence."""
        if self._redis is not None:
            return self._redis
        try:
            import redis
            from chat_app.settings import get_settings
            cfg = get_settings().cache
            if cfg.enabled:
                self._redis = redis.Redis(
                    host=cfg.host, port=cfg.port,
                    password=cfg.password, decode_responses=True,
                    socket_connect_timeout=2,
                )
                self._redis.ping()
                return self._redis
        except Exception as _exc:  # broad catch — resilience against all failures
            self._redis = False  # Mark as unavailable
        return None

    def _restore_from_redis(self):
        """Load persisted counters from Redis on startup."""
        try:
            r = self._get_redis()
            if not r:
                return
            saved = r.hgetall(self._REDIS_KEY)
            if saved:
                for key, val in saved.items():
                    if key in self._counters:
                        self._counters[key] = int(val)
                logger.info("[METRICS] Restored counters from Redis: %s",
                            {k: v for k, v in self._counters.items() if v > 0})
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.debug("[METRICS] Redis restore failed: %s", e)

    def _persist_to_redis(self):
        """Save current counters to Redis."""
        try:
            r = self._get_redis()
            if not r:
                return
            r.hset(self._REDIS_KEY, mapping={k: str(v) for k, v in self._counters.items()})
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

    def increment(self, counter: str, value: int = 1):
        if counter in self._counters:
            self._counters[counter] += value
            self._dirty_count += 1
            if self._dirty_count >= self._PERSIST_INTERVAL:
                self._dirty_count = 0
                self._persist_to_redis()

    def record_latency(self, latency_ms: float):
        self._latencies.append(latency_ms)
        if len(self._latencies) > 100:
            self._latencies = self._latencies[-100:]
        self._gauges["avg_response_latency_ms"] = sum(self._latencies) / len(self._latencies)

    def record_quality(self, score: float):
        self._qualities.append(score)
        if len(self._qualities) > 100:
            self._qualities = self._qualities[-100:]
        self._gauges["avg_quality_score"] = sum(self._qualities) / len(self._qualities)

    def set_gauge(self, gauge: str, value: float):
        self._gauges[gauge] = value

    def get_all(self) -> Dict[str, Any]:
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "latency_p50": sorted(self._latencies)[len(self._latencies) // 2] if self._latencies else 0,
            "latency_p95": sorted(self._latencies)[int(len(self._latencies) * 0.95)] if self._latencies else 0,
            "quality_p50": sorted(self._qualities)[len(self._qualities) // 2] if self._qualities else 0,
        }

    def flush(self):
        """Force persist current counters to Redis."""
        self._persist_to_redis()

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        for name, value in self._counters.items():
            lines.append(f"# TYPE obsai_{name} counter")
            lines.append(f"obsai_{name} {value}")

        for name, value in self._gauges.items():
            lines.append(f"# TYPE obsai_{name} gauge")
            lines.append(f"obsai_{name} {value:.4f}")

        if self._latencies:
            lines.append("# TYPE obsai_response_latency_ms summary")
            lines.append(f'obsai_response_latency_ms{{quantile="0.5"}} {sorted(self._latencies)[len(self._latencies) // 2]:.1f}')
            lines.append(f'obsai_response_latency_ms{{quantile="0.95"}} {sorted(self._latencies)[int(len(self._latencies) * 0.95)]:.1f}')
            lines.append(f'obsai_response_latency_ms{{quantile="0.99"}} {sorted(self._latencies)[int(len(self._latencies) * 0.99)]:.1f}')

        return "\n".join(lines) + "\n"


def get_internal_metrics() -> InternalMetrics:
    return InternalMetrics()


# ---------------------------------------------------------------------------
# Learning Effectiveness Tracking
# ---------------------------------------------------------------------------

async def get_learning_stats(engine) -> Dict[str, Any]:
    """
    Get comprehensive learning effectiveness statistics.

    Tracks how well the self-learning system is performing.
    """
    stats = {
        "episodes_total": 0,
        "episodes_successful": 0,
        "episodes_failed": 0,
        "success_rate": 0.0,
        "avg_confidence": 0.0,
        "semantic_facts": 0,
        "top_intents": [],
        "top_failure_reasons": [],
        "improvement_trend": "stable",  # improving, stable, declining
    }

    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            # Overall episode stats
            result = await conn.execute(text("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failures,
                    AVG(confidence) as avg_conf
                FROM assistant_episodes
                WHERE created_at > NOW() - INTERVAL '30 days'
            """))
            row = result.fetchone()
            if row:
                stats["episodes_total"] = row[0] or 0
                stats["episodes_successful"] = row[1] or 0
                stats["episodes_failed"] = row[2] or 0
                total_rated = (row[1] or 0) + (row[2] or 0)
                stats["success_rate"] = (row[1] or 0) / total_rated if total_rated > 0 else 0
                stats["avg_confidence"] = float(row[3] or 0)

            # Semantic facts count
            result = await conn.execute(text("SELECT COUNT(*) FROM assistant_semantic_facts"))
            stats["semantic_facts"] = result.scalar() or 0

            # Top intents
            result = await conn.execute(text("""
                SELECT intent, COUNT(*) as cnt
                FROM assistant_episodes
                WHERE created_at > NOW() - INTERVAL '30 days' AND intent IS NOT NULL
                GROUP BY intent ORDER BY cnt DESC LIMIT 10
            """))
            stats["top_intents"] = [{"intent": r[0], "count": r[1]} for r in result.fetchall()]

            # Top failure reasons
            result = await conn.execute(text("""
                SELECT failure_reason, COUNT(*) as cnt
                FROM assistant_episodes
                WHERE success = 0 AND failure_reason IS NOT NULL
                  AND created_at > NOW() - INTERVAL '30 days'
                GROUP BY failure_reason ORDER BY cnt DESC LIMIT 5
            """))
            stats["top_failure_reasons"] = [{"reason": r[0], "count": r[1]} for r in result.fetchall()]

            # Improvement trend (compare last 7 days vs prior 7 days)
            result = await conn.execute(text("""
                SELECT
                    AVG(CASE WHEN created_at > NOW() - INTERVAL '7 days' AND success = 1 THEN 1.0 ELSE 0.0 END) as recent,
                    AVG(CASE WHEN created_at BETWEEN NOW() - INTERVAL '14 days' AND NOW() - INTERVAL '7 days' AND success = 1 THEN 1.0 ELSE 0.0 END) as prior
                FROM assistant_episodes
                WHERE success >= 0 AND created_at > NOW() - INTERVAL '14 days'
            """))
            trend_row = result.fetchone()
            if trend_row and trend_row[0] and trend_row[1]:
                recent = float(trend_row[0])
                prior = float(trend_row[1])
                if recent > prior + 0.05:
                    stats["improvement_trend"] = "improving"
                elif recent < prior - 0.05:
                    stats["improvement_trend"] = "declining"

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[HEALTH] Learning stats failed: {exc}")

    return stats


# ---------------------------------------------------------------------------
# Comprehensive Health Check
# ---------------------------------------------------------------------------

async def get_comprehensive_health(engine=None) -> SystemHealth:
    """
    Run all health checks and return comprehensive system health.

    This is the main entry point for health monitoring.
    """
    health = SystemHealth(timestamp=datetime.now(timezone.utc).isoformat())

    # Run all checks concurrently
    checks = [check_ollama(), check_chromadb(), check_redis(), check_search_optimizer(), check_disk_usage()]
    if engine:
        checks.insert(0, check_postgres(engine))
    try:
        from chat_app.settings import get_settings as _gs
        if _gs().docling.enabled:
            checks.append(check_docling())
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    results = await asyncio.gather(*checks, return_exceptions=True)

    for result in results:
        if isinstance(result, ServiceHealth):
            health.services.append(result)
        elif isinstance(result, Exception):
            health.services.append(ServiceHealth(
                name="unknown", status="unhealthy", error=str(result),
                last_check=datetime.now(timezone.utc).isoformat(),
            ))

    # Determine overall status
    critical_services = {"postgres", "ollama", "chromadb"}
    critical_health = [s for s in health.services if s.name in critical_services]

    if all(s.status == "healthy" for s in critical_health):
        health.overall = "healthy"
    elif any(s.status == "unhealthy" for s in critical_health):
        health.overall = "unhealthy"
    else:
        health.overall = "degraded"

    # Add internal metrics
    health.metrics = get_internal_metrics().get_all()

    # Add learning stats
    if engine:
        try:
            health.learning = await get_learning_stats(engine)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

    return health


# ---------------------------------------------------------------------------
# Health Alerts
# ---------------------------------------------------------------------------

async def check_for_alerts(engine=None) -> List[HealthAlert]:
    """Check for conditions that should trigger alerts."""
    alerts = []
    now = datetime.now(timezone.utc).isoformat()

    health = await get_comprehensive_health(engine)

    # Service-level alerts
    for service in health.services:
        if service.status == "unhealthy":
            alerts.append(HealthAlert(
                severity="critical",
                service=service.name,
                message=f"{service.name} is unhealthy: {service.error}",
                timestamp=now,
            ))
        elif service.status == "degraded":
            alerts.append(HealthAlert(
                severity="warning",
                service=service.name,
                message=f"{service.name} is degraded: {service.error or 'unknown reason'}",
                timestamp=now,
            ))

    # Performance alerts
    metrics = health.metrics
    counters = metrics.get("counters", {})
    total = counters.get("queries_total", 0)
    failed = counters.get("queries_failed", 0)

    if total > 10 and failed / total > 0.3:
        alerts.append(HealthAlert(
            severity="warning",
            service="pipeline",
            message=f"High failure rate: {failed}/{total} queries failed ({failed/total:.0%})",
            timestamp=now,
        ))

    # Learning alerts
    learning = health.learning
    if learning.get("improvement_trend") == "declining":
        alerts.append(HealthAlert(
            severity="warning",
            service="learning",
            message="Learning effectiveness is declining — success rate dropping week-over-week",
            timestamp=now,
        ))

    if learning.get("avg_confidence", 0) < 0.3 and learning.get("episodes_total", 0) > 20:
        alerts.append(HealthAlert(
            severity="warning",
            service="quality",
            message=f"Low average confidence: {learning['avg_confidence']:.2f} — may need knowledge base expansion",
            timestamp=now,
        ))

    return alerts


# ---------------------------------------------------------------------------
# Grafana Dashboard Config Generator
# ---------------------------------------------------------------------------

def generate_grafana_dashboard() -> Dict[str, Any]:
    """Generate a Grafana dashboard JSON for the assistant's internal metrics."""
    return {
        "dashboard": {
            "title": "ObsAI - Internal Health",
            "uid": "obsai-health",
            "tags": ["obsai", "assistant", "health"],
            "timezone": "browser",
            "panels": [
                {
                    "title": "Query Success Rate",
                    "type": "gauge",
                    "gridPos": {"h": 6, "w": 6, "x": 0, "y": 0},
                    "targets": [{"expr": "rate(obsai_queries_success[5m]) / rate(obsai_queries_total[5m])", "legendFormat": "Success Rate"}],
                    "fieldConfig": {"defaults": {"thresholds": {"steps": [{"color": "red", "value": 0}, {"color": "yellow", "value": 0.7}, {"color": "green", "value": 0.9}]}}},
                },
                {
                    "title": "Response Latency (p95)",
                    "type": "timeseries",
                    "gridPos": {"h": 6, "w": 12, "x": 6, "y": 0},
                    "targets": [{"expr": "obsai_response_latency_ms{quantile=\"0.95\"}", "legendFormat": "p95 Latency"}],
                },
                {
                    "title": "Cache Hit Rate",
                    "type": "stat",
                    "gridPos": {"h": 6, "w": 6, "x": 18, "y": 0},
                    "targets": [{"expr": "obsai_cache_hits / (obsai_cache_hits + obsai_cache_misses)", "legendFormat": "Hit Rate"}],
                },
                {
                    "title": "Quality Score Trend",
                    "type": "timeseries",
                    "gridPos": {"h": 6, "w": 12, "x": 0, "y": 6},
                    "targets": [{"expr": "obsai_avg_quality_score", "legendFormat": "Avg Quality"}],
                },
                {
                    "title": "Learning Effectiveness",
                    "type": "stat",
                    "gridPos": {"h": 6, "w": 6, "x": 12, "y": 6},
                    "targets": [
                        {"expr": "obsai_facts_learned", "legendFormat": "Facts Learned"},
                        {"expr": "obsai_qa_pairs_generated", "legendFormat": "Q&A Pairs"},
                    ],
                },
                {
                    "title": "Tool Executions",
                    "type": "timeseries",
                    "gridPos": {"h": 6, "w": 6, "x": 18, "y": 6},
                    "targets": [
                        {"expr": "rate(obsai_tool_executions[5m])", "legendFormat": "Executions"},
                        {"expr": "rate(obsai_tool_failures[5m])", "legendFormat": "Failures"},
                    ],
                },
            ],
            "time": {"from": "now-6h", "to": "now"},
            "refresh": "30s",
        },
    }
