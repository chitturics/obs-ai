"""
Observability Skill — System health checks, resource monitoring,
metric analysis, and alert suggestions.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful imports from the existing codebase
# ---------------------------------------------------------------------------
try:
    from chat_app.health_monitor import (
        get_comprehensive_health,
        get_internal_metrics,
        check_for_alerts,
        check_ollama,
        check_chromadb,
        check_redis,
        check_search_optimizer,
        ServiceHealth,
        SystemHealth,
        InternalMetrics,
    )
    _HEALTH_MONITOR_AVAILABLE = True
except ImportError:
    _HEALTH_MONITOR_AVAILABLE = False
    logger.debug("chat_app.health_monitor not available — health checks use fallback")

try:
    from chat_app.resource_manager import get_resource_snapshot, ResourceSnapshot
    _RESOURCE_MANAGER_AVAILABLE = True
except ImportError:
    _RESOURCE_MANAGER_AVAILABLE = False
    logger.debug("chat_app.resource_manager not available — resource checks use /proc fallback")

try:
    from chat_app.prometheus_metrics import (
        RESPONSE_LATENCY,
        REQUEST_COUNT,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    logger.debug("chat_app.prometheus_metrics not available — Prometheus metrics disabled")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_proc_meminfo() -> Dict[str, float]:
    """Read /proc/meminfo for memory statistics."""
    result: Dict[str, float] = {}
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    result[key] = float(val)
    except (FileNotFoundError, ValueError, PermissionError):
        pass
    return result


def _read_proc_loadavg() -> Dict[str, float]:
    """Read /proc/loadavg for CPU load averages."""
    result: Dict[str, float] = {}
    try:
        with open("/proc/loadavg") as fh:
            parts = fh.read().strip().split()
            if len(parts) >= 3:
                result["load_1m"] = float(parts[0])
                result["load_5m"] = float(parts[1])
                result["load_15m"] = float(parts[2])
    except (FileNotFoundError, ValueError, PermissionError):
        pass
    return result


def _get_disk_usage(path: str = "/") -> Dict[str, Any]:
    """Get disk usage for a given path."""
    try:
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bfree * stat.f_frsize
        used = total - free
        return {
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "usage_percent": round((used / total) * 100, 1) if total > 0 else 0,
        }
    except (OSError, ZeroDivisionError):
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "usage_percent": 0}


def _run_async(coro):
    """Run an async coroutine from a sync context, handling nested event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We are inside an event loop — create a task and use a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=15)
    else:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def check_system_health() -> str:
    """
    Returns overall system health status including service connectivity
    (Postgres, Ollama, ChromaDB, Redis), internal metrics, and active alerts.

    Returns:
        JSON string with health status summary.
    """
    now = datetime.now(timezone.utc).isoformat()

    if _HEALTH_MONITOR_AVAILABLE:
        try:
            health = _run_async(get_comprehensive_health())
            services = []
            for svc in health.services:
                services.append({
                    "name": svc.name,
                    "status": svc.status,
                    "latency_ms": round(svc.latency_ms, 2),
                    "error": svc.error,
                    "details": svc.details,
                })

            # Get alerts
            alerts = []
            try:
                alert_list = _run_async(check_for_alerts())
                for alert in alert_list:
                    alerts.append({
                        "severity": alert.severity,
                        "service": alert.service,
                        "message": alert.message,
                    })
            except Exception:
                pass

            return json.dumps({
                "status": "ok",
                "timestamp": now,
                "overall_health": health.overall,
                "services": services,
                "internal_metrics": health.metrics,
                "learning_stats": health.learning,
                "active_alerts": alerts,
            }, indent=2)
        except Exception as exc:
            logger.warning(f"Health monitor check failed: {exc}")

    # Fallback: basic health checks without the full health monitor
    services = []

    # Check Ollama
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    try:
        import urllib.request
        req = urllib.request.Request(f"{ollama_host}/api/tags", method="GET")
        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=5) as resp:
            latency = (time.monotonic() - start) * 1000
            services.append({"name": "ollama", "status": "healthy", "latency_ms": round(latency, 2), "error": None})
    except Exception as exc:
        services.append({"name": "ollama", "status": "unhealthy", "latency_ms": 0, "error": str(exc)})

    # Check ChromaDB
    chroma_host = os.getenv("CHROMA_HOST", "localhost")
    chroma_port = os.getenv("CHROMA_PORT", "8100")
    try:
        import urllib.request
        req = urllib.request.Request(f"http://{chroma_host}:{chroma_port}/api/v1/heartbeat", method="GET")
        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=5) as resp:
            latency = (time.monotonic() - start) * 1000
            services.append({"name": "chromadb", "status": "healthy", "latency_ms": round(latency, 2), "error": None})
    except Exception as exc:
        services.append({"name": "chromadb", "status": "unhealthy", "latency_ms": 0, "error": str(exc)})

    # Determine overall status
    unhealthy = sum(1 for s in services if s["status"] == "unhealthy")
    if unhealthy == 0:
        overall = "healthy"
    elif unhealthy == len(services):
        overall = "unhealthy"
    else:
        overall = "degraded"

    return json.dumps({
        "status": "ok",
        "timestamp": now,
        "overall_health": overall,
        "services": services,
        "internal_metrics": {},
        "learning_stats": {},
        "active_alerts": [],
        "note": "Using fallback health checks — install chat_app.health_monitor for full monitoring",
    }, indent=2)


def get_resource_usage() -> str:
    """
    Returns current CPU, memory, and disk usage for the system.

    Returns:
        JSON string with resource usage data.
    """
    now = datetime.now(timezone.utc).isoformat()

    if _RESOURCE_MANAGER_AVAILABLE:
        try:
            snap = get_resource_snapshot()
            return json.dumps({
                "status": "ok",
                "timestamp": now,
                "cpu_percent": round(snap.cpu_percent, 1),
                "memory_percent": round(snap.memory_percent, 1),
                "memory_available_mb": round(snap.memory_available_mb, 1),
                "disk": _get_disk_usage("/"),
            }, indent=2)
        except Exception as exc:
            logger.warning(f"Resource manager snapshot failed: {exc}")

    # Fallback: read from /proc directly
    meminfo = _read_proc_meminfo()
    loadavg = _read_proc_loadavg()
    disk = _get_disk_usage("/")

    total_kb = meminfo.get("MemTotal", 1)
    available_kb = meminfo.get("MemAvailable", total_kb)
    memory_percent = ((total_kb - available_kb) / total_kb) * 100 if total_kb > 0 else 0

    # Estimate CPU from load average (normalize by CPU count)
    cpu_count = os.cpu_count() or 1
    load_1m = loadavg.get("load_1m", 0)
    cpu_estimate = min((load_1m / cpu_count) * 100, 100)

    return json.dumps({
        "status": "ok",
        "timestamp": now,
        "cpu_percent": round(cpu_estimate, 1),
        "cpu_load_averages": {
            "1m": loadavg.get("load_1m", 0),
            "5m": loadavg.get("load_5m", 0),
            "15m": loadavg.get("load_15m", 0),
        },
        "cpu_count": cpu_count,
        "memory_percent": round(memory_percent, 1),
        "memory_available_mb": round(available_kb / 1024, 1),
        "memory_total_mb": round(total_kb / 1024, 1),
        "disk": disk,
    }, indent=2)


def analyze_metrics(metric_name: Optional[str] = None) -> str:
    """
    Analyze collected internal metrics such as response latency, throughput,
    error rates, and learning effectiveness.

    Args:
        metric_name: Optional specific metric name to analyze.

    Returns:
        JSON string with metric analysis.
    """
    now = datetime.now(timezone.utc).isoformat()
    metrics_data: Dict[str, Any] = {}

    if _HEALTH_MONITOR_AVAILABLE:
        try:
            internal = get_internal_metrics()
            metrics_data = internal.get_all() if hasattr(internal, "get_all") else {}
        except Exception as exc:
            logger.debug(f"Failed to get internal metrics: {exc}")

    # Define available metric categories
    metric_definitions = {
        "response_latency": {
            "description": "Average response time for user queries",
            "unit": "ms",
            "thresholds": {"good": 2000, "warning": 5000, "critical": 10000},
        },
        "error_rate": {
            "description": "Percentage of requests resulting in errors",
            "unit": "%",
            "thresholds": {"good": 1, "warning": 5, "critical": 10},
        },
        "throughput": {
            "description": "Number of requests processed per minute",
            "unit": "req/min",
            "thresholds": {"good": 100, "warning": 50, "critical": 10},
        },
        "cache_hit_rate": {
            "description": "Percentage of queries served from cache",
            "unit": "%",
            "thresholds": {"good": 80, "warning": 50, "critical": 20},
        },
        "learning_effectiveness": {
            "description": "Success rate of the self-learning pipeline",
            "unit": "%",
            "thresholds": {"good": 90, "warning": 70, "critical": 50},
        },
        "vector_search_latency": {
            "description": "Average latency for vector similarity searches",
            "unit": "ms",
            "thresholds": {"good": 200, "warning": 500, "critical": 1000},
        },
    }

    # Filter by metric name if provided
    if metric_name:
        if metric_name in metric_definitions:
            metric_definitions = {metric_name: metric_definitions[metric_name]}
        else:
            return json.dumps({
                "status": "error",
                "error": f"Unknown metric: {metric_name}",
                "available_metrics": list(metric_definitions.keys()),
            })

    analysis: List[Dict[str, Any]] = []
    for name, definition in metric_definitions.items():
        value = metrics_data.get(name, None)
        entry: Dict[str, Any] = {
            "name": name,
            "description": definition["description"],
            "unit": definition["unit"],
            "value": value,
            "status": "unknown",
        }

        if value is not None:
            thresholds = definition["thresholds"]
            if name in ("error_rate",):
                # Lower is better
                if value <= thresholds["good"]:
                    entry["status"] = "good"
                elif value <= thresholds["warning"]:
                    entry["status"] = "warning"
                else:
                    entry["status"] = "critical"
            elif name in ("response_latency", "vector_search_latency"):
                # Lower is better
                if value <= thresholds["good"]:
                    entry["status"] = "good"
                elif value <= thresholds["warning"]:
                    entry["status"] = "warning"
                else:
                    entry["status"] = "critical"
            elif name in ("throughput", "cache_hit_rate", "learning_effectiveness"):
                # Higher is better (thresholds are minimums)
                if value >= thresholds["good"]:
                    entry["status"] = "good"
                elif value >= thresholds["warning"]:
                    entry["status"] = "warning"
                else:
                    entry["status"] = "critical"

        analysis.append(entry)

    # Determine overall assessment
    statuses = [a["status"] for a in analysis if a["status"] != "unknown"]
    if not statuses:
        overall = "no_data"
    elif "critical" in statuses:
        overall = "critical"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "healthy"

    return json.dumps({
        "status": "ok",
        "timestamp": now,
        "overall_assessment": overall,
        "metrics": analysis,
        "raw_metrics": metrics_data if metrics_data else None,
    }, indent=2)


def suggest_alerts(service: Optional[str] = None) -> str:
    """
    Suggest alerting rules based on current system state and best practices.

    Args:
        service: Optional service name to scope alert suggestions to.

    Returns:
        JSON string with suggested alerting rules.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Define alert templates per service
    alert_templates: Dict[str, List[Dict[str, Any]]] = {
        "postgres": [
            {
                "name": "PostgreSQL Connection Pool Exhaustion",
                "condition": "connection_pool_usage > 90%",
                "severity": "critical",
                "description": "Database connection pool is nearly exhausted",
                "spl": 'index=_internal sourcetype=postgres_metrics pool_usage>90 | stats count',
                "action": "Scale up pool size or investigate long-running queries",
            },
            {
                "name": "PostgreSQL Slow Queries",
                "condition": "query_duration > 5s",
                "severity": "warning",
                "description": "Database queries taking longer than 5 seconds",
                "spl": 'index=_internal sourcetype=postgres_metrics duration>5000 | stats count by query',
                "action": "Review query execution plans and add indexes",
            },
        ],
        "ollama": [
            {
                "name": "Ollama Service Down",
                "condition": "health_check_failed for 2 consecutive checks",
                "severity": "critical",
                "description": "Ollama LLM service is not responding",
                "spl": 'index=_internal sourcetype=health_check service=ollama status=unhealthy | stats count',
                "action": "Restart Ollama service and check GPU availability",
            },
            {
                "name": "Ollama High Latency",
                "condition": "avg_latency > 10s",
                "severity": "warning",
                "description": "LLM inference latency is above threshold",
                "spl": 'index=_internal sourcetype=health_check service=ollama latency_ms>10000 | timechart avg(latency_ms)',
                "action": "Check GPU utilization and model loading status",
            },
        ],
        "chromadb": [
            {
                "name": "ChromaDB Service Down",
                "condition": "health_check_failed for 2 consecutive checks",
                "severity": "critical",
                "description": "ChromaDB vector store is not responding",
                "spl": 'index=_internal sourcetype=health_check service=chromadb status=unhealthy | stats count',
                "action": "Restart ChromaDB and verify data persistence directory",
            },
            {
                "name": "ChromaDB Slow Queries",
                "condition": "search_latency > 1s",
                "severity": "warning",
                "description": "Vector search latency is above acceptable threshold",
                "spl": 'index=_internal sourcetype=vector_search latency_ms>1000 | timechart avg(latency_ms)',
                "action": "Review collection sizes and consider indexing optimizations",
            },
        ],
        "redis": [
            {
                "name": "Redis Service Down",
                "condition": "health_check_failed",
                "severity": "warning",
                "description": "Redis cache service is not responding",
                "spl": 'index=_internal sourcetype=health_check service=redis status=unhealthy | stats count',
                "action": "Restart Redis — system will function with degraded caching",
            },
            {
                "name": "Redis High Memory Usage",
                "condition": "memory_usage > 80%",
                "severity": "warning",
                "description": "Redis memory usage is high — risk of evictions",
                "spl": 'index=_internal sourcetype=redis_metrics used_memory_pct>80 | stats latest(used_memory_pct)',
                "action": "Review key expiry policies or increase maxmemory",
            },
        ],
        "system": [
            {
                "name": "High CPU Usage",
                "condition": "cpu_percent > 80% for 5 minutes",
                "severity": "warning",
                "description": "Sustained high CPU usage detected",
                "spl": 'index=_internal sourcetype=system_metrics cpu_percent>80 | timechart span=1m avg(cpu_percent)',
                "action": "Check for resource-intensive queries or runaway processes",
            },
            {
                "name": "High Memory Usage",
                "condition": "memory_percent > 85%",
                "severity": "critical",
                "description": "System memory usage is critically high",
                "spl": 'index=_internal sourcetype=system_metrics memory_percent>85 | stats latest(memory_percent)',
                "action": "Investigate memory-heavy processes and consider scaling resources",
            },
            {
                "name": "Disk Space Low",
                "condition": "disk_usage > 90%",
                "severity": "critical",
                "description": "Disk space is critically low",
                "spl": 'index=_internal sourcetype=system_metrics disk_percent>90 | stats latest(disk_percent)',
                "action": "Clean up old data, logs, or temporary files. Consider expanding storage.",
            },
            {
                "name": "High Error Rate",
                "condition": "error_rate > 5% over 15 minutes",
                "severity": "warning",
                "description": "Error rate exceeds acceptable threshold",
                "spl": 'index=_internal sourcetype=app_metrics error_rate>5 | timechart span=5m avg(error_rate)',
                "action": "Review error logs for root cause. Check service dependencies.",
            },
        ],
    }

    # Filter by service
    if service:
        service_lower = service.lower()
        if service_lower in alert_templates:
            filtered = {service_lower: alert_templates[service_lower]}
        else:
            return json.dumps({
                "status": "error",
                "error": f"Unknown service: {service}",
                "available_services": list(alert_templates.keys()),
            })
    else:
        filtered = alert_templates

    # Compile suggestions
    all_suggestions: List[Dict[str, Any]] = []
    for svc_name, alerts in filtered.items():
        for alert in alerts:
            all_suggestions.append({
                "service": svc_name,
                **alert,
            })

    # Augment with current health data if available
    current_issues: List[str] = []
    if _HEALTH_MONITOR_AVAILABLE:
        try:
            alerts = _run_async(check_for_alerts())
            for alert in alerts:
                current_issues.append(f"{alert.severity}: {alert.service} — {alert.message}")
        except Exception:
            pass

    return json.dumps({
        "status": "ok",
        "timestamp": now,
        "suggested_alerts": all_suggestions,
        "total_suggestions": len(all_suggestions),
        "current_active_issues": current_issues,
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("observability skill cleaned up")
