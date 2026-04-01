"""
Health check endpoints and service status monitoring.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)


async def check_postgres(engine: AsyncEngine) -> Dict[str, Any]:
    """Check PostgreSQL database connectivity."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            _ = result.scalar()
            return {
                "status": "healthy",
                "message": "Database connection successful",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        return {
            "status": "unhealthy",
            "message": f"Database error: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


async def check_ollama() -> Dict[str, Any]:
    """Check Ollama API availability.

    Uses the probed URL from llm_utils (which handles IPv6 fallback for podman).
    Falls back to settings.ollama.base_url if llm_utils isn't available.
    Always tries IPv6 [::1] as a fallback for podman rootless networking.
    """
    import socket
    from urllib.parse import urlparse

    settings_url = get_settings().ollama.base_url
    ollama_url = settings_url

    # Try to get the already-probed URL from the LLM instance
    try:
        from llm_utils import LLM
        if LLM and hasattr(LLM, 'base_url'):
            ollama_url = str(LLM.base_url)
            logger.debug("[HEALTH] Using LLM.base_url: %s", ollama_url)
        else:
            logger.debug("[HEALTH] LLM unavailable, using settings URL: %s", settings_url)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[HEALTH] LLM import failed (%s), using settings URL: %s", exc, settings_url)

    # Build list of URLs to try — always include IPv6 fallback for podman
    parsed = urlparse(ollama_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11430
    scheme = parsed.scheme or "http"

    urls_to_try = [ollama_url]
    # Always add IPv6 fallback for localhost-like addresses
    if host in ("localhost", "127.0.0.1"):
        urls_to_try.append(f"{scheme}://[::1]:{port}")
    # If URL is already IPv6, also try localhost as fallback
    elif host == "::1":
        urls_to_try.append(f"{scheme}://localhost:{port}")

    logger.debug("[HEALTH] Ollama URLs to try: %s", urls_to_try)

    # Quick socket pre-check to find a reachable host (faster than httpx timeouts)
    working_url = None
    for url in urls_to_try:
        p = urlparse(url)
        h = p.hostname or "localhost"
        pt = p.port or 11430
        try:
            s = socket.create_connection((h, pt), timeout=2)
            s.close()
            working_url = url
            break
        except (ConnectionRefusedError, OSError, socket.timeout):
            continue

    if working_url:
        urls_to_try = [working_url]

    last_error = None
    for url in urls_to_try:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{url}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    return {
                        "status": "healthy",
                        "message": f"Ollama API reachable at {url}",
                        "models": models,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                else:
                    last_error = f"Ollama returned status {response.status_code}"
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            last_error = str(e)
            logger.debug("[HEALTH] Ollama check failed for %s: %s", url, last_error)

    return {
        "status": "unhealthy",
        "message": f"Ollama unreachable: {last_error}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def check_chroma() -> Dict[str, Any]:
    """Check ChromaDB API availability."""
    chroma_url = get_settings().chroma.http_url
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{chroma_url}/api/v2/heartbeat")
            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "message": "ChromaDB API reachable",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            else:
                return {
                    "status": "unhealthy",
                    "message": f"ChromaDB returned status {response.status_code}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
        return {
            "status": "unhealthy",
            "message": f"ChromaDB unreachable: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


async def check_redis() -> Dict[str, Any]:
    """Check Redis availability (if enabled)."""
    cfg = get_settings().cache
    if not cfg.enabled:
        return {
            "status": "disabled",
            "message": "Redis caching not enabled",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    try:
        import redis.asyncio as redis

        client = redis.Redis(
            host=cfg.host,
            port=cfg.port,
            decode_responses=True,
            socket_connect_timeout=5,
        )

        await client.ping()
        info = await client.info("stats")
        await client.close()

        return {
            "status": "healthy",
            "message": "Redis connection successful",
            "total_commands": info.get("total_commands_processed", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        return {
            "status": "unhealthy",
            "message": f"Redis error: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


async def get_health_status(engine: AsyncEngine) -> Dict[str, Any]:
    """
    Aggregate health status from all services.

    Returns:
        Dictionary with overall status and individual service checks.
    """
    cfg = get_settings()

    # Run all checks concurrently
    postgres_check, ollama_check, chroma_check, redis_check = await asyncio.gather(
        check_postgres(engine),
        check_ollama(),
        check_chroma(),
        check_redis(),
        return_exceptions=True
    )

    # Handle exceptions from gather
    def safe_result(check_result, service_name):
        if isinstance(check_result, Exception):
            return {
                "status": "unhealthy",
                "message": f"{service_name} check failed: {str(check_result)}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        return check_result

    services = {
        "postgres": safe_result(postgres_check, "PostgreSQL"),
        "ollama": safe_result(ollama_check, "Ollama"),
        "chroma": safe_result(chroma_check, "ChromaDB"),
        "redis": safe_result(redis_check, "Redis"),
    }

    # Determine overall status
    critical_services = ["postgres", "ollama", "chroma"]
    all_critical_healthy = all(
        services[svc]["status"] == "healthy"
        for svc in critical_services
    )

    overall_status = "healthy" if all_critical_healthy else "degraded"

    # If any critical service is down, mark as unhealthy
    any_critical_down = any(
        services[svc]["status"] == "unhealthy"
        for svc in critical_services
    )
    if any_critical_down:
        overall_status = "unhealthy"

    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": services,
        "version": cfg.app.version,
        "environment": cfg.app.environment,
    }
