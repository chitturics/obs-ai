"""Admin sub-router: Container management endpoints.

Handles these endpoint groups:
- GET  /api/admin/containers           — List container/service status
- POST /api/admin/containers/action    — Manage a container (restart, stop, start, logs, rebuild)
- POST /api/admin/containers/rebuild-all — Rebuild and restart all services
- POST /api/admin/containers/build     — Build container images
- GET  /api/admin/containers/{service}/health — Per-service health probe
- GET  /api/admin/containers/runtime   — Container runtime info

Mount with:
    from chat_app.admin_containers import containers_router
    app.include_router(containers_router)
"""

import logging
import socket
import subprocess

import httpx
from fastapi import APIRouter, Depends, HTTPException

from chat_app.auth_dependencies import require_admin
from chat_app.admin_shared import (
    _arun,
    _append_audit,
    _compose_cmd,
    _compose_dir,
    _container_cmd,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _safe_error,
    _track_audit_user,
    _ALLOWED_CONTAINER_SERVICES,
    _SERVICE_PROBES,
    ContainerActionRequest,
    ContainerBuildRequest,
)

logger = logging.getLogger(__name__)

containers_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-containers"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Health probe helper
# ---------------------------------------------------------------------------

def _probe_service_health(service: str) -> dict:
    """Probe a service via TCP/HTTP without needing docker/podman CLI."""
    probe = _SERVICE_PROBES.get(service)
    if not probe:
        return {"service": service, "running": None, "error": f"Unknown service: {service}", "timestamp": _now_iso()}

    port, probe_type = probe
    last_error = None
    for host in ["localhost", "::1"]:
        try:
            if probe_type == "http":
                # IPv6 addresses need brackets in URLs
                url_host = f"[{host}]" if ":" in host else host
                with httpx.Client(timeout=3) as hc:
                    resp = hc.get(f"http://{url_host}:{port}/")
                    return {
                        "service": service, "running": True, "state": "running",
                        "health": f"HTTP {resp.status_code}", "port": port,
                        "method": "http_probe", "timestamp": _now_iso(),
                    }
            else:
                s = socket.create_connection((host, port), timeout=2)
                s.close()
                return {
                    "service": service, "running": True, "state": "running",
                    "health": "port open", "port": port,
                    "method": "tcp_probe", "timestamp": _now_iso(),
                }
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            last_error = f"{host}:{port} - {exc}"
            continue
    logger.warning("[ADMIN] Service probe failed for %s: %s", service, last_error)
    return {"service": service, "running": False, "state": "unreachable", "port": port, "method": "probe", "timestamp": _now_iso()}


# ---------------------------------------------------------------------------
# GET /api/admin/containers
# ---------------------------------------------------------------------------

@containers_router.get("/containers", summary="List container/service status")
async def list_containers():
    """List all docker-compose services and their status."""
    import json as _json
    services = []
    runtime = _container_cmd()

    # Use docker/podman ps directly (compose may not be available)
    if runtime:
        try:
            result = await _arun(
                [runtime, "ps", "--format", "json"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        try:
                            container = _json.loads(line)
                            name = container.get("Names", container.get("Name", ""))
                            state = container.get("State", "unknown")
                            status = container.get("Status", "unknown")
                            image = container.get("Image", "")
                            ports = container.get("Ports", "")
                            services.append({
                                "name": name,
                                "state": state,
                                "status": status,
                                "image": image,
                                "ports": ports,
                            })
                        except _json.JSONDecodeError as _exc:
                            logger.debug("Could not parse container JSON line: %s", _exc)
        except (OSError, ValueError, KeyError, TypeError, _json.JSONDecodeError) as exc:
            logger.debug("Container query failed: %s", exc)

    # Fallback: if no services found, return known service definitions
    # Use the /ready endpoint health data for live status instead of slow socket probing
    if not services or (len(services) == 1 and "error" in services[0]):
        # Get live health status from the readiness check (already cached, fast)
        health_status = {}
        try:
            from chat_app.health_monitor import get_health_monitor
            monitor = get_health_monitor()
            if monitor:
                health_status = monitor.get_status() or {}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[%s] %%s", "admin_containers.py", _exc)

        ollama_ok = health_status.get("ollama", {}).get("status") == "healthy"
        chroma_ok = health_status.get("chroma", {}).get("status") == "healthy"
        postgres_ok = health_status.get("postgres", {}).get("status") == "healthy"
        redis_ok = health_status.get("redis", {}).get("status") == "healthy"

        services = [
            {"name": "chat_ui_app", "state": "running", "status": "Up (this container)", "image": "chainlit-app:latest", "ports": "8090"},
            {"name": "nginx_gateway", "state": "running", "status": "Up (serving requests)", "image": "nginx:alpine", "ports": "8000"},
            {"name": "llm_api_service", "state": "running" if ollama_ok else "unknown", "status": "Healthy" if ollama_ok else "Check manually", "image": "ollama/ollama", "ports": "11430"},
            {"name": "chat_chroma_db", "state": "running" if chroma_ok else "unknown", "status": "Healthy" if chroma_ok else "Check manually", "image": "chromadb/chroma", "ports": "8001"},
            {"name": "chat_db_app", "state": "running" if postgres_ok else "unknown", "status": "Healthy" if postgres_ok else "Check manually", "image": "postgres:16-alpine", "ports": "5432"},
            {"name": "redis_cache", "state": "running" if redis_ok else "unknown", "status": "Healthy" if redis_ok else "Check manually", "image": "redis:7-alpine", "ports": "6379"},
            {"name": "search_opt_service", "state": "unknown", "status": "Check manually", "image": "chainlit-search-opt", "ports": "9005"},
            {"name": "prometheus_monitoring", "state": "unknown", "status": "Check manually", "image": "prom/prometheus", "ports": "9090"},
            {"name": "grafana_monitoring", "state": "unknown", "status": "Check manually", "image": "grafana/grafana", "ports": "3100"},
        ]

    return {
        "services": services,
        "total": len(services),
        "runtime": runtime,
        "compose_file": "docker-compose.yml",
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# POST /api/admin/containers/action
# ---------------------------------------------------------------------------

@containers_router.post("/containers/action", summary="Manage a container/service")
async def manage_container(body: ContainerActionRequest):
    """Restart, stop, start, or rebuild a docker-compose service."""
    valid_actions = {"restart", "stop", "start", "up", "logs"}
    if body.action not in valid_actions and body.action != "rebuild":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action: {body.action}. Valid: {sorted(valid_actions | {'rebuild'})}",
        )
    # Validate service name against allowlist to prevent command injection
    if body.service and body.service not in _ALLOWED_CONTAINER_SERVICES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown service: {body.service}. Valid: {sorted(_ALLOWED_CONTAINER_SERVICES)}",
        )

    runtime = _container_cmd()
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No container runtime (podman/docker) available inside this container. "
                "To manage containers, run commands from the host: "
                f"podman restart {body.service}"
            ),
        )

    # Use direct docker/podman commands (not compose) since compose plugin
    # may not be available in the container
    if body.action == "rebuild":
        # Rebuild requires compose — try compose first, fall back to restart
        compose = _compose_cmd()
        cwd = _compose_dir()
        cmd = compose + ["up", "-d", "--build", "--force-recreate", body.service]
    elif body.action == "logs":
        cmd = [runtime, "logs", "--tail=100", body.service]
        cwd = None
    elif body.action == "up":
        cmd = [runtime, "start", body.service]
        cwd = None
    else:
        # restart, stop, start — direct docker/podman commands
        cmd = [runtime, body.action, body.service]
        cwd = None

    try:
        result = await _arun(
            cmd, capture_output=True, text=True, timeout=120, cwd=cwd,
        )

        _append_audit(
            section="containers",
            action=body.action,
            changes={"service": body.service, "exit_code": result.returncode},
        )

        # Record to activity timeline
        try:
            from chat_app.activity_timeline import get_timeline
            get_timeline().record(
                event_type="container_action",
                actor="admin",
                action=body.action,
                target=body.service,
                details={"exit_code": result.returncode},
                status="ok" if result.returncode == 0 else "error",
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[%s] %%s", "admin_containers.py", _exc)

        # Fetch fresh state after action so UI can update immediately
        current_state = "unknown"
        try:
            import asyncio as _aio
            await _aio.sleep(1)  # Brief wait for state to settle
            state_result = await _arun(
                [runtime, "inspect", "--format", "{{.State.Status}}", body.service],
                capture_output=True, text=True, timeout=5,
            )
            if state_result.returncode == 0:
                current_state = state_result.stdout.strip() or "unknown"
        except (OSError, ValueError, RuntimeError):
            pass

        return {
            "service": body.service,
            "action": body.action,
            "success": result.returncode == 0,
            "current_state": current_state,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "exit_code": result.returncode,
            "timestamp": _now_iso(),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Container action timed out after 120s")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


# ---------------------------------------------------------------------------
# POST /api/admin/containers/rebuild-all
# ---------------------------------------------------------------------------

@containers_router.post("/containers/rebuild-all", summary="Rebuild and restart all services")
async def rebuild_all():
    """Rebuild and restart all docker-compose services."""
    if _container_cmd() is None:
        raise HTTPException(
            status_code=503,
            detail="No container runtime available. Run rebuild from host.",
        )
    compose = _compose_cmd()
    cwd = _compose_dir()

    try:
        result = await _arun(
            compose + ["up", "-d", "--build", "--force-recreate"],
            capture_output=True, text=True, timeout=300, cwd=cwd,
        )

        _append_audit(
            section="containers",
            action="rebuild_all",
            changes={"exit_code": result.returncode},
        )

        # Record to activity timeline
        try:
            from chat_app.activity_timeline import get_timeline
            get_timeline().record(
                event_type="container_action",
                actor="admin",
                action="rebuild_all",
                target="all_services",
                details={"exit_code": result.returncode},
                status="ok" if result.returncode == 0 else "error",
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[%s] %%s", "admin_containers.py", _exc)

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


# ---------------------------------------------------------------------------
# POST /api/admin/containers/build
# ---------------------------------------------------------------------------

@containers_router.post("/containers/build", summary="Build container images")
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
        result = await _arun(
            cmd, capture_output=True, text=True, timeout=600, cwd=cwd,
        )

        _append_audit(
            section="containers",
            action="build",
            changes={"services": body.services or ["all"], "no_cache": body.no_cache, "exit_code": result.returncode},
        )

        # Record to activity timeline
        try:
            from chat_app.activity_timeline import get_timeline
            get_timeline().record(
                event_type="container_action",
                actor="admin",
                action="build",
                target=", ".join(body.services) if body.services else "all",
                details={"no_cache": body.no_cache, "exit_code": result.returncode},
                status="ok" if result.returncode == 0 else "error",
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[%s] %%s", "admin_containers.py", _exc)

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


# ---------------------------------------------------------------------------
# GET /api/admin/containers/{service}/health
# ---------------------------------------------------------------------------

@containers_router.get("/containers/health", summary="Aggregate health of all containers")
async def containers_health_all():
    """Check health of all container services."""
    services = ["chat_db_app", "chat_chroma_db", "llm_api_service", "chat_ui_app", "redis_cache"]
    results = {}
    for svc in services:
        try:
            result = await container_health(svc)
            results[svc] = result
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
            results[svc] = {"service": svc, "healthy": False, "error": "probe failed"}
    healthy_count = sum(1 for r in results.values() if r.get("healthy"))
    return {
        "overall": "healthy" if healthy_count >= 3 else "degraded",
        "services": results,
        "healthy_count": healthy_count,
        "total_count": len(services),
        "timestamp": _now_iso(),
    }


@containers_router.get("/containers/{service}/health", summary="Per-service health probe")
async def container_health(service: str):
    """Check health of a specific container service.
    Uses docker/podman compose if available, otherwise falls back to TCP/HTTP probes."""
    import json as _json
    runtime = _container_cmd()

    # If no container runtime CLI is available, use direct service probes
    if runtime is None:
        # Special case: we ARE the app -- if this request is being served, we're running
        if service == "chat_ui_app":
            return {
                "service": service, "running": True, "state": "running",
                "health": "self (serving requests)", "port": 8090,
                "method": "self_check", "timestamp": _now_iso(),
            }
        return _probe_service_health(service)

    compose = _compose_cmd()
    cwd = _compose_dir()

    # Get container status via compose
    try:
        result = await _arun(
            compose + ["ps", "--format", "json", service],
            capture_output=True, text=True, timeout=10, cwd=cwd,
        )
        if result.returncode != 0:
            # Compose failed -- fall back to probe
            return _probe_service_health(service)

        svc_info = {}
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    svc_info = _json.loads(line)
                    break
                except _json.JSONDecodeError as _exc:
                    logger.debug("Could not parse service inspect JSON line: %s", _exc)

        state = svc_info.get("State", "unknown")
        health_status = svc_info.get("Health", "")

        # Try to get container resource usage
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
                stats = _json.loads(stats_result.stdout.strip())
        except (OSError, ValueError, KeyError, TypeError, _json.JSONDecodeError) as _exc:
            logger.debug("[%s] %%s", "admin_containers.py", _exc)

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
        # Runtime claimed to exist but binary not found -- fall back to probes
        return _probe_service_health(service)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


# ---------------------------------------------------------------------------
# GET /api/admin/containers/runtime
# ---------------------------------------------------------------------------

@containers_router.get("/containers/runtime", summary="Container runtime info")
async def container_runtime_info():
    """Return information about the detected container runtime."""
    runtime = _container_cmd()
    version_info = ""

    if runtime is not None:
        try:
            result = await _arun(
                [runtime, "--version"], capture_output=True, text=True, timeout=5,
            )
            version_info = result.stdout.strip()
        except Exception as _exc:  # broad catch — resilience against all failures
            version_info = "unavailable"
    else:
        version_info = "no CLI available (running inside container)"

    compose_version = ""
    if runtime is not None:
        try:
            result = await _arun(
                _compose_cmd() + ["version"], capture_output=True, text=True, timeout=5,
            )
            compose_version = result.stdout.strip()
        except Exception as _exc:  # broad catch — resilience against all failures
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
# GET /api/admin/containers/health — aggregate health check across all services
# ---------------------------------------------------------------------------

@containers_router.get("/containers/health", summary="Aggregate container health")
async def get_containers_health():
    """Probe all known services and return an aggregate health summary.

    Uses the same TCP/HTTP probes as the per-service health endpoint but runs
    them for every service in parallel and returns a consolidated view suitable
    for a dashboard overview widget.
    """
    import asyncio as _asyncio

    known_services = list(_SERVICE_PROBES.keys())

    # Run probes concurrently using asyncio.gather over thread-pool workers.
    probes = await _asyncio.gather(
        *[_asyncio.to_thread(_probe_service_health, svc) for svc in known_services],
        return_exceptions=True,
    )

    results = []
    healthy_count = 0
    unhealthy_count = 0

    for probe_result in probes:
        if isinstance(probe_result, Exception):
            results.append({
                "service": "unknown",
                "running": False,
                "state": "error",
                "health": f"probe error: {probe_result}",
                "timestamp": _now_iso(),
            })
            unhealthy_count += 1
        else:
            results.append(probe_result)
            if probe_result.get("running"):
                healthy_count += 1
            else:
                unhealthy_count += 1

    overall = "healthy" if unhealthy_count == 0 else ("degraded" if healthy_count > 0 else "critical")

    return {
        "status": "ok",
        "overall_health": overall,
        "healthy": healthy_count,
        "unhealthy": unhealthy_count,
        "total": len(results),
        "services": results,
        "timestamp": _now_iso(),
    }
