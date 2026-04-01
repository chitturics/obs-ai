"""Admin sub-router extension 2: Cache, Containers, Idle Worker, Utilities.

Extracted from admin_operations_routes.py to keep file sizes manageable.
Routes are registered on the same operations_router via import.

Endpoint groups in this file:
- GET  /api/admin/cache/*              -- Cache management (4)
- GET  /api/admin/containers/*         -- Container management (6)
- GET  /api/admin/idle-worker/*        -- Idle worker management (5)
- POST /api/admin/utilities/*          -- Utility operations (1)
"""

import json
import logging
import subprocess

from fastapi import HTTPException, Request

from chat_app.admin_operations_routes import (
    operations_router,
    CacheSearchRequest,
    CacheInvalidateRequest,
    ContainerActionRequest,
    ContainerBuildRequest,
    IdleWorkerConfigRequest,
    _UTILITY_OPS,
)
from chat_app.admin_shared import (
    _append_audit,
    _arun,
    _container_cmd,
    _compose_cmd,
    _compose_dir,
    _now_iso,
    _safe_error,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache Management
# ---------------------------------------------------------------------------

@operations_router.get("/cache/stats", summary="Get cache statistics")
async def get_cache_stats():
    """Get Redis cache and semantic cache statistics."""
    result = {"redis": {"enabled": False}, "semantic": {}, "timestamp": _now_iso()}

    try:
        from chat_app.cache import get_cache
        cache = get_cache()
        if cache.enabled and cache.client:
            info_mem = await cache.client.info("memory")
            info_stats = await cache.client.info("stats")
            db_size = await cache.client.dbsize()
            hits = info_stats.get("keyspace_hits", 0)
            misses = info_stats.get("keyspace_misses", 0)
            total = hits + misses
            result["redis"] = {
                "enabled": True,
                "total_keys": db_size,
                "memory_used": info_mem.get("used_memory_human", "0B"),
                "memory_used_bytes": info_mem.get("used_memory", 0),
                "peak_memory": info_mem.get("used_memory_peak_human", "0B"),
                "hits": hits,
                "misses": misses,
                "hit_rate": round(hits / total * 100, 1) if total > 0 else 0,
                "ttl_default": cache.ttl,
            }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        result["redis"]["error"] = str(exc)

    try:
        import chat_app.semantic_cache as _sc_mod
        sc = getattr(_sc_mod, "_semantic_cache_instance", None)
        if sc:
            total = sc.hits + sc.misses
            result["semantic"] = {
                "size": len(sc.cache),
                "max_size": sc.max_size,
                "hits": sc.hits,
                "misses": sc.misses,
                "hit_rate": round(sc.hits / total * 100, 1) if total > 0 else 0,
            }
        else:
            result["semantic"] = {"size": 0, "hits": 0, "misses": 0, "note": "Not initialized"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        result["semantic"]["error"] = str(exc)

    return result


@operations_router.post("/cache/search", summary="Search cache keys")
async def search_cache_keys(body: CacheSearchRequest):
    """Search Redis cache keys by pattern."""
    try:
        from chat_app.cache import get_cache
        cache = get_cache()
        if not cache.enabled or not cache.client:
            return {"keys": [], "count": 0, "timestamp": _now_iso()}

        keys = []
        count = 0
        async for key in cache.client.scan_iter(match=body.pattern, count=200):
            if count >= body.limit:
                break
            try:
                ttl = await cache.client.ttl(key)
                key_type = await cache.client.type(key)
                keys.append({"key": key, "type": key_type, "ttl": ttl})
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.debug("[ADMIN] Failed to inspect cache key: %s", exc)
                keys.append({"key": key, "type": "unknown", "ttl": -1})
            count += 1

        return {"keys": keys, "count": len(keys), "pattern": body.pattern, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@operations_router.post("/cache/invalidate", summary="Invalidate cache keys by pattern")
async def invalidate_cache_keys(body: CacheInvalidateRequest):
    """Delete all cache keys matching a pattern."""
    try:
        from chat_app.cache import get_cache
        cache = get_cache()
        if not cache.enabled or not cache.client:
            return {"deleted": 0, "error": "Cache not enabled", "timestamp": _now_iso()}

        deleted = await cache.delete_pattern(body.pattern)
        _append_audit(
            section="cache",
            action="invalidate",
            changes={"pattern": body.pattern, "deleted": deleted},
        )
        return {"deleted": deleted, "pattern": body.pattern, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@operations_router.post("/cache/clear", summary="Clear all cache")
async def clear_all_cache():
    """Flush all Redis cache and reset semantic cache."""
    results = {"redis": False, "semantic": False}

    try:
        from chat_app.cache import get_cache
        cache = get_cache()
        if cache.enabled and cache.client:
            await cache.client.flushdb()
            results["redis"] = True
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[CACHE] Redis flush failed: %s", exc)

    try:
        import chat_app.semantic_cache as _sc_mod
        sc = getattr(_sc_mod, "_semantic_cache_instance", None)
        if sc:
            sc.cache.clear()
            sc.hits = 0
            sc.misses = 0
            results["semantic"] = True
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[CACHE] Semantic cache clear failed: %s", exc)

    _append_audit(section="cache", action="clear_all", changes=results)
    return {"status": "ok", "cleared": results, "timestamp": _now_iso()}


# ---------------------------------------------------------------------------
# Container / Service Management
# ---------------------------------------------------------------------------

@operations_router.get("/containers", summary="List container/service status")
async def list_containers():
    """List all docker-compose services and their status."""
    try:
        from chat_app.admin_containers import list_containers as _list_containers
        return await _list_containers()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("Container list failed: %s", exc)
        return {"services": [], "total": 0, "runtime": None, "timestamp": _now_iso()}


@operations_router.post("/containers/action", summary="Manage a container/service")
async def manage_container_proxy(body: ContainerActionRequest):
    """Restart, stop, start, or rebuild a container service."""
    try:
        from chat_app.admin_containers import manage_container as _manage
        return await _manage(body)
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "container action"))


@operations_router.post("/containers/rebuild-all", summary="Rebuild and restart all services")
async def rebuild_all():
    """Rebuild and restart all docker-compose services."""
    if _container_cmd() is None:
        raise HTTPException(status_code=503, detail="No container runtime available. Run rebuild from host.")
    compose = _compose_cmd()
    cwd = _compose_dir()

    try:
        result = await _arun(
            compose + ["up", "-d", "--build", "--force-recreate"],
            capture_output=True, text=True, timeout=300, cwd=cwd,
        )
        _append_audit(section="containers", action="rebuild_all", changes={"exit_code": result.returncode})
        return {
            "action": "rebuild_all",
            "success": result.returncode == 0,
            "stdout": result.stdout[-3000:] if result.stdout else "",
            "stderr": result.stderr[-3000:] if result.stderr else "",
            "exit_code": result.returncode,
            "timestamp": _now_iso(),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Full rebuild timed out after 300s")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@operations_router.post("/containers/build", summary="Build container images")
async def build_containers(body: ContainerBuildRequest):
    """Build one or more container images without starting them."""
    if _container_cmd() is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No container runtime (podman/docker) available inside this container. "
                "To build images, run commands from the host: "
                f"podman compose build {' '.join(body.services) if body.services else ''}"
            ),
        )
    compose = _compose_cmd()
    cwd = _compose_dir()

    cmd = compose + ["build"]
    if body.no_cache:
        cmd.append("--no-cache")
    if body.services:
        cmd.extend(body.services)

    try:
        result = await _arun(cmd, capture_output=True, text=True, timeout=600, cwd=cwd)
        _append_audit(section="containers", action="build", changes={"services": body.services or ["all"], "no_cache": body.no_cache, "exit_code": result.returncode})
        return {
            "action": "build",
            "services": body.services or ["all"],
            "no_cache": body.no_cache,
            "success": result.returncode == 0,
            "stdout": result.stdout[-3000:] if result.stdout else "",
            "stderr": result.stderr[-3000:] if result.stderr else "",
            "exit_code": result.returncode,
            "timestamp": _now_iso(),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Build timed out after 600s")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@operations_router.get("/containers/{service}/health", summary="Per-service health probe")
async def container_health(service: str):
    """Check health of a specific container service."""
    from chat_app.admin_operations_routes import _probe_service_health
    runtime = _container_cmd()

    if runtime is None:
        if service == "chat_ui_app":
            return {
                "service": service, "running": True, "state": "running",
                "health": "self (serving requests)", "port": 8090,
                "method": "self_check", "timestamp": _now_iso(),
            }
        return _probe_service_health(service)

    compose = _compose_cmd()
    cwd = _compose_dir()

    try:
        result = await _arun(
            compose + ["ps", "--format", "json", service],
            capture_output=True, text=True, timeout=10, cwd=cwd,
        )
        if result.returncode != 0:
            return _probe_service_health(service)

        svc_info = {}
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    svc_info = json.loads(line)
                    break
                except json.JSONDecodeError:
                    pass

        state = svc_info.get("State", "unknown")
        health_status = svc_info.get("Health", "")
        container_name = svc_info.get("Name", service)
        stats = {}
        try:
            stats_result = await _arun(
                [runtime, "stats", "--no-stream", "--format",
                 '{"cpu":"{{.CPUPerc}}","mem":"{{.MemUsage}}","mem_pct":"{{.MemPerc}}","net":"{{.NetIO}}"}',
                 container_name],
                capture_output=True, text=True, timeout=10,
            )
            if stats_result.returncode == 0 and stats_result.stdout.strip():
                stats = json.loads(stats_result.stdout.strip())
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.debug("[ADMIN] Failed to get container stats: %s", exc)

        return {
            "service": service,
            "container": container_name,
            "running": state == "running",
            "state": state,
            "health": health_status or "no healthcheck",
            "status": svc_info.get("Status", "unknown"),
            "ports": svc_info.get("Ports", ""),
            "stats": stats,
            "timestamp": _now_iso(),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Health check timed out")
    except FileNotFoundError:
        return _probe_service_health(service)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@operations_router.get("/containers/runtime", summary="Container runtime info")
async def container_runtime_info():
    """Return information about the detected container runtime."""
    runtime = _container_cmd()
    version_info = ""

    if runtime is not None:
        try:
            result = await _arun([runtime, "--version"], capture_output=True, text=True, timeout=5)
            version_info = result.stdout.strip()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[ADMIN] Failed to get runtime version: %s", exc)
            version_info = "unavailable"
    else:
        version_info = "no CLI available (running inside container)"

    compose_version = ""
    if runtime is not None:
        try:
            result = await _arun(_compose_cmd() + ["version"], capture_output=True, text=True, timeout=5)
            compose_version = result.stdout.strip()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[ADMIN] Failed to get compose version: %s", exc)
            compose_version = "unavailable"
    else:
        compose_version = "no CLI available"

    return {
        "runtime": runtime or "none (service probes used)",
        "version": version_info,
        "compose_version": compose_version,
        "compose_dir": _compose_dir(),
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Idle Worker Management
# ---------------------------------------------------------------------------

@operations_router.get("/idle-worker", summary="Get idle worker status")
async def get_idle_worker_status():
    """Return idle worker status, configuration, and improvement history."""
    try:
        from chat_app.idle_worker import get_idle_worker
        worker = get_idle_worker()
        return {
            "status": "ok",
            **worker.get_status(),
            "config": {
                "idle_threshold_seconds": worker._idle_threshold,
                "min_cycle_interval": worker._min_cycle_interval,
                "max_tasks_per_cycle": worker._max_tasks_per_cycle,
            },
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[ADMIN] Idle worker status failed: %s", exc)
        return {
            "running": False, "is_idle": False, "cycles_completed": 0,
            "improvements_made": 0, "recent_improvements": [],
            "config": {"idle_threshold_seconds": 60, "min_cycle_interval": 300, "max_tasks_per_cycle": 5},
            "timestamp": _now_iso(),
        }


@operations_router.get("/idle-worker/status", summary="Get idle worker status (alias)")
async def get_idle_worker_status_alias():
    return await get_idle_worker_status()


@operations_router.patch("/idle-worker", summary="Configure idle worker")
async def configure_idle_worker(body: IdleWorkerConfigRequest):
    """Update idle worker configuration."""
    try:
        from chat_app.idle_worker import get_idle_worker
        worker = get_idle_worker()
        updates = body.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update.")

        for key, value in updates.items():
            setattr(worker, f"_{key}", value)

        _append_audit(section="idle_worker", action="configure", changes=updates)

        return {
            "updated": updates,
            "config": {
                "idle_threshold_seconds": worker._idle_threshold,
                "min_cycle_interval": worker._min_cycle_interval,
                "max_tasks_per_cycle": worker._max_tasks_per_cycle,
            },
            "timestamp": _now_iso(),
        }
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@operations_router.post("/idle-worker/trigger", summary="Trigger idle worker cycle manually")
async def trigger_idle_cycle():
    """Manually trigger an idle worker improvement cycle."""
    try:
        from chat_app.idle_worker import get_idle_worker
        worker = get_idle_worker()
        await worker._run_improvement_cycle()
        return {
            "status": "completed",
            "cycles_completed": worker._cycle_count,
            "improvements_made": len(worker._improvements_made),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "error": str(exc)}


@operations_router.get("/idle-worker/results", summary="Get idle worker job results")
async def get_idle_worker_results():
    """Return persisted results from all idle worker jobs."""
    try:
        from chat_app.idle_worker import get_idle_worker
        worker = get_idle_worker()
        return {
            "status": "ok",
            "results": worker.get_job_results(),
            "jobs": [j.to_dict() for j in worker._jobs] if hasattr(worker, "_jobs") else [],
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[ADMIN] Idle worker results failed: %s", exc)
        return {"status": "error", "results": {}, "jobs": [], "timestamp": _now_iso()}


# ---------------------------------------------------------------------------
# Utility operations
# ---------------------------------------------------------------------------

@operations_router.post("/utilities/{operation}", summary="Execute a utility operation")
async def execute_utility(operation: str, request: Request):
    """Execute a utility operation (encoding, hashing, data transform)."""
    body = await request.json()
    input_text = body.get("input", "")
    if not input_text:
        raise HTTPException(400, "Missing 'input' field")

    from chat_app.skill_executor import get_internal_handler
    handler = get_internal_handler(operation)
    if not handler:
        raise HTTPException(404, f"Unknown utility: {operation}")

    if operation not in _UTILITY_OPS:
        raise HTTPException(403, f"Operation '{operation}' is not a utility — use /agentic/execute-skill instead")

    try:
        result = handler(user_input=input_text, **body)
        return {"operation": operation, "result": result, "success": True}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        return {"operation": operation, "error": str(e), "success": False}
