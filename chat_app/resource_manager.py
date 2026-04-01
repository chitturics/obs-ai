"""
Resource Manager — Adaptive scheduling, auto-heal, and system health awareness.

Provides:
1. Resource-aware job gating (check CPU/memory before heavy tasks)
2. Job overlap prevention (track running jobs, skip if busy)
3. Auto-heal: detect failures, attempt recovery, track healing history
4. Health-aware routing: expose service status for query pipeline
5. Learning history tracking across cycles
"""
import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resource Checks
# ---------------------------------------------------------------------------

@dataclass
class ResourceSnapshot:
    """Current system resource usage."""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_available_mb: float = 0.0
    disk_percent: float = 0.0
    timestamp: str = ""


def get_resource_snapshot() -> ResourceSnapshot:
    """
    Get current system resource usage.

    Uses /proc/meminfo and /proc/loadavg as lightweight alternatives to psutil.
    Falls back gracefully if unavailable.
    """
    snap = ResourceSnapshot(timestamp=datetime.now(timezone.utc).isoformat())

    # Memory from /proc/meminfo (Linux)
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    meminfo[key] = int(val)

            total = meminfo.get("MemTotal", 1)
            available = meminfo.get("MemAvailable", total)
            snap.memory_percent = ((total - available) / total) * 100
            snap.memory_available_mb = available / 1024
    except (FileNotFoundError, KeyError, ValueError) as _exc:
        logger.debug("Could not read /proc/meminfo for resource snapshot: %s", _exc)

    # CPU load from /proc/loadavg (Linux) — 1-minute average
    try:
        with open("/proc/loadavg") as f:
            load_1min = float(f.read().split()[0])
            cpu_count = os.cpu_count() or 1
            snap.cpu_percent = min(100, (load_1min / cpu_count) * 100)
    except (FileNotFoundError, ValueError) as _exc:
        logger.debug("Could not read /proc/loadavg for resource snapshot: %s", _exc)

    # Disk usage
    try:
        statvfs = os.statvfs("/")
        total = statvfs.f_blocks * statvfs.f_frsize
        free = statvfs.f_bfree * statvfs.f_frsize
        snap.disk_percent = ((total - free) / total) * 100 if total else 0
    except (OSError, AttributeError) as _exc:
        logger.debug("Could not read disk usage via statvfs: %s", _exc)

    return snap


def can_run_heavy_task(
    max_cpu: float = 75.0,
    max_memory: float = 80.0,
    min_memory_mb: float = 500.0,
    max_disk: float = 90.0,
) -> tuple:
    """
    Check if resources allow running a heavy task.

    Returns (allowed: bool, reason: str).
    """
    snap = get_resource_snapshot()

    if snap.cpu_percent > max_cpu:
        return False, f"CPU too high ({snap.cpu_percent:.0f}% > {max_cpu}%)"

    if snap.memory_percent > max_memory:
        return False, f"Memory too high ({snap.memory_percent:.0f}% > {max_memory}%)"

    if snap.memory_available_mb < min_memory_mb and snap.memory_available_mb > 0:
        return False, f"Memory low ({snap.memory_available_mb:.0f}MB < {min_memory_mb}MB)"

    if snap.disk_percent > max_disk:
        return False, f"Disk usage too high ({snap.disk_percent:.0f}% > {max_disk}%)"

    return True, "OK"


# ---------------------------------------------------------------------------
# Job Overlap Prevention
# ---------------------------------------------------------------------------

_running_jobs: Dict[str, float] = {}  # job_name -> start_time
_job_lock: Optional[asyncio.Lock] = None


def is_job_running(job_name: str, max_duration_s: float = 3600) -> bool:
    """Check if a job is currently running (with stale detection)."""
    start = _running_jobs.get(job_name)
    if start is None:
        return False
    elapsed = time.monotonic() - start
    if elapsed > max_duration_s:
        # Job is stale — force release
        logger.warning(f"[RESOURCE] Job '{job_name}' stale ({elapsed:.0f}s > {max_duration_s}s), releasing")
        _running_jobs.pop(job_name, None)
        return False
    return True


def acquire_job(job_name: str) -> bool:
    """Try to acquire a job slot. Returns True if acquired."""
    if is_job_running(job_name):
        return False
    _running_jobs[job_name] = time.monotonic()
    return True


def release_job(job_name: str):
    """Release a job slot."""
    _running_jobs.pop(job_name, None)


async def run_guarded_job(
    job_name: str,
    func: Callable,
    *args,
    resource_check: bool = True,
    max_duration_s: float = 3600,
    **kwargs,
) -> Optional[Any]:
    """
    Run a job with resource checks and overlap prevention.

    Returns the job result, or None if skipped.
    """
    # Check overlap
    if not acquire_job(job_name):
        logger.info(f"[RESOURCE] Skipping '{job_name}': previous run still active")
        return None

    # Check resources
    if resource_check:
        allowed, reason = can_run_heavy_task()
        if not allowed:
            release_job(job_name)
            logger.info(f"[RESOURCE] Deferring '{job_name}': {reason}")
            return None

    try:
        logger.info(f"[RESOURCE] Starting '{job_name}'")
        if asyncio.iscoroutinefunction(func):
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=max_duration_s)
        else:
            result = func(*args, **kwargs)
        logger.info(f"[RESOURCE] Completed '{job_name}'")
        return result
    except asyncio.TimeoutError:
        logger.warning(f"[RESOURCE] Job '{job_name}' timed out after {max_duration_s}s")
        return None
    except Exception as exc:  # Broad catch intentional: guards arbitrary scheduler jobs that may raise any type
        logger.error(f"[RESOURCE] Job '{job_name}' failed: {exc}")
        return None
    finally:
        release_job(job_name)


# ---------------------------------------------------------------------------
# Auto-Heal: Service Recovery
# ---------------------------------------------------------------------------

@dataclass
class HealingEvent:
    """Record of an auto-heal attempt."""
    timestamp: str
    service: str
    issue: str
    action: str
    success: bool
    detail: str = ""


_healing_history: List[HealingEvent] = []
_MAX_HEALING_HISTORY = 100

# Service health cache for routing decisions
_service_health: Dict[str, str] = {}  # service -> "healthy"|"degraded"|"unhealthy"


def get_service_health(service: str) -> str:
    """Get cached health status of a service (for fast query-time decisions)."""
    return _service_health.get(service, "unknown")


def is_service_healthy(service: str) -> bool:
    """Quick check if a service is usable."""
    status = _service_health.get(service, "healthy")
    return status in ("healthy", "degraded", "unknown")


def update_service_health(service: str, status: str):
    """Update cached health status."""
    old = _service_health.get(service)
    _service_health[service] = status
    if old and old != status:
        logger.info(f"[HEALTH] Service '{service}' status changed: {old} → {status}")


async def auto_heal_check(engine=None) -> List[HealingEvent]:
    """
    Run auto-heal checks across all services.

    For each unhealthy service:
    1. Detect the issue
    2. Attempt recovery
    3. Log the healing event
    4. Update service health cache
    """
    events = []

    # Check PostgreSQL
    try:
        if engine:
            from sqlalchemy import text
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            update_service_health("postgres", "healthy")
        else:
            update_service_health("postgres", "unknown")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        update_service_health("postgres", "unhealthy")
        event = HealingEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            service="postgres",
            issue=str(exc)[:200],
            action="connection_retry",
            success=False,
        )
        # Attempt reconnect
        try:
            if engine:
                await engine.dispose()
                async with engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                event.success = True
                event.detail = "Reconnected after pool dispose"
                update_service_health("postgres", "healthy")
        except Exception as _exc:  # broad catch — resilience against all failures
            event.detail = "Reconnect failed"
        events.append(event)

    # Check Ollama (try configured URL + IPv6 fallback for podman)
    try:
        from chat_app.settings import get_settings
        from urllib.parse import urlparse
        settings = get_settings()
        import aiohttp

        ollama_url = settings.ollama.base_url
        urls_to_try = [ollama_url]
        parsed = urlparse(ollama_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 11430
        if host in ("localhost", "127.0.0.1"):
            urls_to_try.append(f"{parsed.scheme}://[::1]:{port}")

        ollama_ok = False
        async with aiohttp.ClientSession() as session:
            for url in urls_to_try:
                try:
                    async with session.get(
                        f"{url}/api/version",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            update_service_health("ollama", "healthy")
                            ollama_ok = True
                            break
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                    continue
            if not ollama_ok:
                update_service_health("ollama", "degraded")
    except ImportError:
        update_service_health("ollama", "unknown")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        update_service_health("ollama", "unhealthy")
        events.append(HealingEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            service="ollama",
            issue=str(exc)[:200],
            action="health_check_failed",
            success=False,
            detail="Ollama unreachable — queries will use cached responses",
        ))

    # Check ChromaDB
    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        import aiohttp
        async with aiohttp.ClientSession() as session:
            chroma_url = f"http://{settings.chroma.host}:{settings.chroma.port}/api/v2/heartbeat"
            async with session.get(chroma_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    update_service_health("chromadb", "healthy")
                else:
                    update_service_health("chromadb", "degraded")
    except ImportError:
        update_service_health("chromadb", "unknown")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        update_service_health("chromadb", "unhealthy")
        events.append(HealingEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            service="chromadb",
            issue=str(exc)[:200],
            action="health_check_failed",
            success=False,
            detail="ChromaDB unreachable — using fallback retrieval",
        ))

    # Check Redis
    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        if settings.redis.url:
            import redis.asyncio as _aioredis
            r = _aioredis.from_url(settings.redis.url, socket_timeout=3)
            await r.ping()
            await r.close()
            update_service_health("redis", "healthy")
    except ImportError:
        update_service_health("redis", "unknown")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        update_service_health("redis", "degraded")
        events.append(HealingEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            service="redis",
            issue=str(exc)[:200],
            action="health_check_failed",
            success=False,
            detail="Redis unavailable — cache disabled, using direct queries",
        ))

    # Store healing events
    for event in events:
        _healing_history.append(event)
        if event.success:
            logger.info(f"[AUTO-HEAL] {event.service}: {event.action} succeeded — {event.detail}")
        else:
            logger.warning(f"[AUTO-HEAL] {event.service}: {event.action} failed — {event.detail}")

    # Trim history
    while len(_healing_history) > _MAX_HEALING_HISTORY:
        _healing_history.pop(0)

    return events


def get_healing_history(limit: int = 20) -> List[dict]:
    """Get recent healing events."""
    return [
        {
            "timestamp": e.timestamp,
            "service": e.service,
            "issue": e.issue,
            "action": e.action,
            "success": e.success,
            "detail": e.detail,
        }
        for e in _healing_history[-limit:]
    ]


def get_all_service_health() -> Dict[str, str]:
    """Get health status of all tracked services."""
    return dict(_service_health)


# ---------------------------------------------------------------------------
# Learning History Tracker
# ---------------------------------------------------------------------------

@dataclass
class LearningSnapshot:
    """A point-in-time snapshot of the system's knowledge state."""
    timestamp: str
    version: str
    qa_pairs_total: int = 0
    semantic_facts: int = 0
    episodes_total: int = 0
    model_name: str = ""
    collections: List[str] = field(default_factory=list)
    quality_avg: float = 0.0
    success_rate: float = 0.0
    improvement_notes: List[str] = field(default_factory=list)


_learning_snapshots: List[LearningSnapshot] = []
_current_version = "3.5.0"


def record_learning_snapshot(
    qa_pairs: int = 0,
    facts: int = 0,
    episodes: int = 0,
    model_name: str = "",
    quality_avg: float = 0.0,
    success_rate: float = 0.0,
    notes: List[str] = None,
):
    """Record a learning snapshot for history tracking."""
    snap = LearningSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=_current_version,
        qa_pairs_total=qa_pairs,
        semantic_facts=facts,
        episodes_total=episodes,
        model_name=model_name,
        quality_avg=quality_avg,
        success_rate=success_rate,
        improvement_notes=notes or [],
    )
    _learning_snapshots.append(snap)

    # Keep last 100 snapshots in memory
    while len(_learning_snapshots) > 100:
        _learning_snapshots.pop(0)

    logger.info(
        f"[LEARNING-HISTORY] Snapshot: v{_current_version}, "
        f"qa={qa_pairs}, facts={facts}, quality={quality_avg:.2f}, "
        f"success_rate={success_rate:.2f}"
    )


def get_learning_trend(window: int = 10) -> Dict[str, Any]:
    """
    Get learning trend over recent snapshots.

    Returns quality/success rate trends and improvement summary.
    """
    recent = _learning_snapshots[-window:]
    if not recent:
        return {"status": "no_data", "snapshots": 0}

    qualities = [s.quality_avg for s in recent if s.quality_avg > 0]
    success_rates = [s.success_rate for s in recent if s.success_rate > 0]
    qa_counts = [s.qa_pairs_total for s in recent]

    trend = {
        "snapshots": len(recent),
        "latest_version": recent[-1].version,
        "latest_model": recent[-1].model_name,
        "qa_pairs_latest": recent[-1].qa_pairs_total,
        "facts_latest": recent[-1].semantic_facts,
    }

    if len(qualities) >= 2:
        first_half = qualities[:len(qualities) // 2]
        second_half = qualities[len(qualities) // 2:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        trend["quality_trend"] = "improving" if avg_second > avg_first + 0.02 else (
            "declining" if avg_second < avg_first - 0.02 else "stable"
        )
        trend["quality_avg"] = avg_second

    if len(success_rates) >= 2:
        first_half = success_rates[:len(success_rates) // 2]
        second_half = success_rates[len(success_rates) // 2:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        trend["success_trend"] = "improving" if avg_second > avg_first + 0.02 else (
            "declining" if avg_second < avg_first - 0.02 else "stable"
        )
        trend["success_rate_avg"] = avg_second

    if len(qa_counts) >= 2:
        trend["knowledge_growth"] = qa_counts[-1] - qa_counts[0]

    return trend


def get_learning_history(limit: int = 20) -> List[dict]:
    """Get recent learning snapshots."""
    return [
        {
            "timestamp": s.timestamp,
            "version": s.version,
            "qa_pairs": s.qa_pairs_total,
            "facts": s.semantic_facts,
            "quality": s.quality_avg,
            "success_rate": s.success_rate,
            "model": s.model_name,
            "notes": s.improvement_notes,
        }
        for s in _learning_snapshots[-limit:]
    ]
