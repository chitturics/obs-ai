"""
HTTP health check routes for Kubernetes/Docker probes.

Mounted on the Chainlit FastAPI app for:
  /health  - Full health status (existing)
  /live    - Liveness probe (is the process alive?)
  /ready   - Readiness probe (are all services connected?)
  /metrics - Prometheus metrics endpoint
"""
import asyncio
import logging
import socket
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse
from health import check_chroma
from metrics import get_metrics

try:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter()

_start_time = time.time()


def _find_ollama_url() -> str:
    """Find a reachable Ollama URL, with IPv6 fallback for podman rootless."""
    from chat_app.settings import get_settings
    base_url = get_settings().ollama.base_url

    # Try to reuse the already-probed URL from the LLM instance
    try:
        from llm_utils import LLM
        if LLM and hasattr(LLM, 'base_url'):
            base_url = str(LLM.base_url)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11430
    scheme = parsed.scheme or "http"

    # Build candidate list
    candidates = [(host, port, base_url)]
    if host in ("localhost", "127.0.0.1"):
        candidates.append(("::1", port, f"{scheme}://[::1]:{port}"))
    elif host == "::1":
        candidates.append(("localhost", port, f"{scheme}://localhost:{port}"))

    # Socket probe to find a reachable candidate
    for h, p, url in candidates:
        try:
            s = socket.create_connection((h, p), timeout=2)
            s.close()
            return url
        except (ConnectionRefusedError, OSError, socket.timeout):
            continue

    return base_url


async def _check_ollama_ready() -> dict:
    """Readiness check for Ollama with IPv6 fallback."""
    url = _find_ollama_url()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/api/tags")
            if response.status_code == 200:
                return {"status": "healthy"}
            return {
                "status": "unhealthy",
                "message": f"Ollama returned status {response.status_code}",
            }
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
        return {
            "status": "unhealthy",
            "message": f"Ollama unreachable at {url}: {e}",
        }


@router.get("/live")
async def liveness():
    """Liveness probe - returns 200 if the process is alive."""
    return JSONResponse(
        {"status": "alive", "uptime_seconds": round(time.time() - _start_time, 1)},
        status_code=200,
    )


@router.get("/ready")
async def readiness():
    """
    Readiness probe - returns 200 only when critical services are connected.
    Returns 503 if any critical service is unavailable.
    """
    try:
        # Check all critical services (aligned with Prometheus alerts)
        checks = [
            _check_ollama_ready(),
            check_chroma(),
        ]
        service_names = ["ollama", "chromadb"]

        # Add PostgreSQL check if engine available
        try:
            from chat_app.database import get_engine
            engine = get_engine()
            if engine:
                async def _check_pg():
                    from sqlalchemy import text
                    async with engine.begin() as conn:
                        await conn.execute(text("SELECT 1"))
                    return {"status": "healthy"}
                checks.append(_check_pg())
                service_names.append("postgres")
        except Exception as _exc:  # broad catch — resilience against all failures
            logger.debug("Postgres health-check setup skipped: %s", _exc)

        results = await asyncio.gather(*checks, return_exceptions=True)

        services = {}
        all_ready = True

        for result, name in zip(results, service_names):
            if isinstance(result, Exception):
                services[name] = {"status": "unhealthy", "error": str(result)}
                all_ready = False
            elif isinstance(result, dict) and result.get("status") != "healthy":
                services[name] = result
                all_ready = False
            else:
                services[name] = {"status": "healthy"}

            # Record to Prometheus metrics (aligned with alert_rules.yml)
            try:
                from chat_app.prometheus_metrics import record_service_health
                is_healthy = services[name].get("status") == "healthy"
                record_service_health(name, is_healthy)
            except Exception as _exc:  # broad catch — resilience against all failures
                logger.debug("Prometheus metrics unavailable: %s", _exc)

        status_code = 200 if all_ready else 503
        return JSONResponse(
            {"status": "ready" if all_ready else "not_ready", "services": services},
            status_code=status_code,
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        return JSONResponse(
            {"status": "not_ready", "error": str(e)},
            status_code=503,
        )


@router.get("/metrics")
async def prometheus_metrics():
    """Expose Prometheus metrics endpoint."""
    if _PROMETHEUS_AVAILABLE:
        return PlainTextResponse(
            generate_latest().decode("utf-8"),
            media_type=CONTENT_TYPE_LATEST,
        )
    # Fallback: custom metrics summary
    summary = get_metrics().get_prometheus_summary()
    return PlainTextResponse(summary, media_type="text/plain")


# Startup state tracking
_startup_complete = False


def mark_startup_complete():
    """Call after all initialization is done (LLM loaded, collections ready)."""
    global _startup_complete
    _startup_complete = True
    logger.info("[HEALTH] Startup marked complete after %.1fs", time.time() - _start_time)


@router.get("/startup")
async def startup_probe():
    """Startup probe — returns 503 until initialization is complete, then 200.

    Use with Kubernetes startupProbe or Docker HEALTHCHECK --start-period.
    Checks:
    - LLM model loaded
    - ChromaDB collections accessible
    - Settings loaded
    """
    if _startup_complete:
        return JSONResponse(
            {"status": "started", "uptime_seconds": round(time.time() - _start_time, 1)},
            status_code=200,
        )

    # Check if critical init steps are done
    checks_passed = 0
    checks_total = 3

    # Check 1: Settings loaded
    try:
        from chat_app.settings import get_settings
        get_settings()
        checks_passed += 1
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # Check 2: LLM available
    try:
        from llm_utils import LLM
        if LLM is not None:
            checks_passed += 1
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # Check 3: ChromaDB reachable
    try:
        result = await check_chroma()
        if result.get("status") == "healthy":
            checks_passed += 1
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    if checks_passed >= checks_total:
        mark_startup_complete()
        return JSONResponse(
            {"status": "started", "checks": f"{checks_passed}/{checks_total}",
             "uptime_seconds": round(time.time() - _start_time, 1)},
            status_code=200,
        )

    return JSONResponse(
        {"status": "initializing", "checks": f"{checks_passed}/{checks_total}",
         "uptime_seconds": round(time.time() - _start_time, 1)},
        status_code=503,
    )
