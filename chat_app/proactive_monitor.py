"""
Proactive Monitoring and Assistance.

Background task that periodically checks Splunk health, service connectivity,
and surfaces actionable alerts to the user's chat session.

Usage::

    from chat_app.proactive_monitor import start_monitoring, stop_monitoring

    # In on_chat_start:
    await start_monitoring()

    # In on_chat_end:
    stop_monitoring()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import chainlit as cl

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)

# Default check interval (seconds)
_DEFAULT_INTERVAL = 300  # 5 minutes
_MIN_INTERVAL = 60

# Background task handle per session
_monitor_tasks: Dict[str, asyncio.Task] = {}

# Cached SplunkClient per monitor (avoids reconnecting every cycle)
_splunk_client = None


def _get_splunk_client():
    """Get or create a cached SplunkClient instance."""
    global _splunk_client
    if _splunk_client is not None and _splunk_client.service is not None:
        return _splunk_client

    cfg = get_settings().splunk
    if not cfg.is_configured:
        return None

    try:
        from chat_app.splunk_client import SplunkClient
        client = SplunkClient()
        client.connect()
        _splunk_client = client
        return client
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("Could not create SplunkClient: %s", exc)
        _splunk_client = None
        return None


# ---------------------------------------------------------------------------
# Individual health checks
# ---------------------------------------------------------------------------

async def _check_splunk_health() -> List[Dict[str, Any]]:
    """Check Splunk instance health via the REST API."""
    alerts: List[Dict[str, Any]] = []

    client = _get_splunk_client()
    if client is None:
        return alerts

    try:
        # Check Splunk messages (license warnings, errors, etc.)
        try:
            if client.service:
                for msg in client.service.messages:
                    severity = msg.content.get("severity", "info")
                    if severity in ("warn", "error"):
                        alerts.append({
                            "level": "warning" if severity == "warn" else "error",
                            "source": "splunk",
                            "title": msg.name,
                            "detail": msg.content.get("message", "No details"),
                        })
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("Could not check Splunk messages: %s", exc)

        # Check license usage for near-limit warnings
        try:
            lic = client.get_license_usage()
            if lic and lic.get("usage_percent", 0) > 90:
                alerts.append({
                    "level": "warning",
                    "source": "splunk",
                    "title": "License usage above 90%",
                    "detail": f"Currently at {lic['usage_percent']}% ({lic.get('used_gb', '?')} GB / {lic.get('quota_gb', '?')} GB)",
                    "action": "Review data ingestion volume",
                })
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("Could not check license usage: %s", exc)

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("Splunk health check skipped: %s", exc)
        # Connection may have gone stale — clear cached client
        global _splunk_client
        _splunk_client = None

    return alerts


async def _check_service_connectivity() -> List[Dict[str, Any]]:
    """Check connectivity to Ollama, ChromaDB, and Redis."""
    from chat_app.health import check_ollama, check_chroma, check_redis

    alerts: List[Dict[str, Any]] = []

    checks = await asyncio.gather(
        check_ollama(),
        check_chroma(),
        check_redis(),
        return_exceptions=True,
    )

    service_names = ["Ollama LLM", "ChromaDB Vector Store", "Redis Cache"]
    for name, result in zip(service_names, checks):
        if isinstance(result, Exception):
            alerts.append({
                "level": "error",
                "source": "infrastructure",
                "title": f"{name} unreachable",
                "detail": str(result),
            })
        elif isinstance(result, dict) and result.get("status") == "unhealthy":
            alerts.append({
                "level": "warning",
                "source": "infrastructure",
                "title": f"{name} degraded",
                "detail": result.get("message", "Unknown issue"),
            })

    return alerts


async def _check_disk_and_index_health() -> List[Dict[str, Any]]:
    """Check for index-related issues via Splunk internal logs."""
    alerts: List[Dict[str, Any]] = []

    client = _get_splunk_client()
    if client is None:
        return alerts

    try:
        # Check for recent indexing errors (last hour)
        try:
            results = client.run_search(
                "index=_internal sourcetype=splunkd log_level=ERROR "
                "component=TailingProcessor OR component=LineBreakingProcessor "
                "earliest=-1h | stats count by component, message | head 5",
                max_results=5,
            )
            for row in results:
                count = int(row.get("count", 0))
                if count > 10:
                    alerts.append({
                        "level": "warning",
                        "source": "splunk_indexing",
                        "title": f"Indexing errors: {row.get('component', 'unknown')}",
                        "detail": f"{count} errors in the last hour: {row.get('message', '')[:200]}",
                    })
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("Could not check indexing health: %s", exc)

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("Disk/index health check skipped: %s", exc)

    return alerts


# ---------------------------------------------------------------------------
# Alert formatting and delivery
# ---------------------------------------------------------------------------

def _format_alerts(alerts: List[Dict[str, Any]]) -> str:
    """Format alerts into a Chainlit-friendly markdown message."""
    if not alerts:
        return ""

    level_icons = {"error": "!!!", "warning": "**!", "info": ""}
    lines = ["**Proactive Health Check**\n"]

    for alert in alerts[:5]:  # Cap at 5 alerts per check
        icon = level_icons.get(alert["level"], "")
        lines.append(f"- {icon} **{alert['title']}** ({alert['source']})")
        lines.append(f"  {alert['detail']}")
        if action := alert.get("action"):
            lines.append(f"  *Suggested:* {action}")
        lines.append("")

    lines.append(f"*Last checked: {datetime.now(timezone.utc).strftime('%H:%M UTC')}*")
    return "\n".join(lines)


async def _deliver_alerts(alerts: List[Dict[str, Any]]) -> None:
    """Send alert summary to the user's chat session."""
    if not alerts:
        return

    formatted = _format_alerts(alerts)
    if formatted:
        try:
            await cl.Message(
                content=formatted,
                author="Health Monitor",
            ).send()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("Could not deliver health alerts: %s", exc)


# ---------------------------------------------------------------------------
# Background monitoring loop
# ---------------------------------------------------------------------------

async def _trigger_self_improvement() -> Optional[Dict[str, Any]]:
    """
    Trigger self-improvement tasks: learn from feedback, apply patterns.
    Called periodically by the monitor to keep the system learning.
    """
    results = {}
    try:
        from search_opt_client import trigger_learning
        learn_result = await trigger_learning()
        if learn_result:
            results["learning"] = learn_result
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("Self-improvement learning trigger skipped: %s", exc)

    try:
        from self_adaptive_rag import SelfAdaptiveRAG
        rag = SelfAdaptiveRAG()
        if hasattr(rag, "decay_weights"):
            rag.decay_weights()
            results["weight_decay"] = True
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("Self-adaptive RAG decay skipped: %s", exc)

    if results:
        logger.info("Self-improvement cycle: %s", results)
    return results or None


async def _monitor_loop(interval: int = _DEFAULT_INTERVAL) -> None:
    """Run periodic health checks, deliver alerts, and trigger self-improvement."""
    # Initial delay to let services stabilize after startup
    await asyncio.sleep(30)

    # Track previously-seen alerts to avoid repeat noise
    seen_titles: set[str] = set()
    # Self-improvement runs every 3rd cycle to avoid overhead
    cycle_count = 0

    while True:
        try:
            cycle_count += 1

            # Gather all health checks concurrently
            splunk_alerts, service_alerts, index_alerts = await asyncio.gather(
                _check_splunk_health(),
                _check_service_connectivity(),
                _check_disk_and_index_health(),
                return_exceptions=True,
            )

            all_alerts: List[Dict[str, Any]] = []
            for result in (splunk_alerts, service_alerts, index_alerts):
                if isinstance(result, list):
                    all_alerts.extend(result)

            # De-duplicate: only show new alerts
            new_alerts = [a for a in all_alerts if a["title"] not in seen_titles]
            if new_alerts:
                await _deliver_alerts(new_alerts)
                seen_titles.update(a["title"] for a in new_alerts)

            # Expire old alerts after 3 cycles so they can resurface
            if len(seen_titles) > 50:
                seen_titles.clear()

            # Trigger self-improvement every 3rd cycle (~15 min with default interval)
            if cycle_count % 3 == 0:
                try:
                    await _trigger_self_improvement()
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                    logger.debug("Self-improvement cycle failed: %s", exc)

        except asyncio.CancelledError:
            logger.info("Health monitor cancelled")
            return
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("Health monitor cycle error: %s", exc)

        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def start_monitoring(
    interval: int = _DEFAULT_INTERVAL,
) -> None:
    """
    Start background health monitoring for the current chat session.

    Args:
        interval: Seconds between checks (default 300 = 5 min).
    """
    session_id = getattr(cl.user_session, "id", "default")

    # Don't start if already running
    if session_id in _monitor_tasks and not _monitor_tasks[session_id].done():
        return

    effective_interval = max(_MIN_INTERVAL, interval)
    task = asyncio.create_task(_monitor_loop(effective_interval))
    _monitor_tasks[session_id] = task
    logger.info("Health monitor started (interval=%ss, session=%s)", effective_interval, session_id)


def stop_monitoring() -> None:
    """Stop background health monitoring for the current chat session."""
    session_id = getattr(cl.user_session, "id", "default")
    task = _monitor_tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()
        logger.info("Health monitor stopped (session=%s)", session_id)


async def run_health_check_now() -> str:
    """
    Run all health checks immediately and return formatted results.

    Useful for on-demand `/health` or `/status` commands.
    """
    splunk_alerts, service_alerts, index_alerts = await asyncio.gather(
        _check_splunk_health(),
        _check_service_connectivity(),
        _check_disk_and_index_health(),
        return_exceptions=True,
    )

    all_alerts: List[Dict[str, Any]] = []
    for result in (splunk_alerts, service_alerts, index_alerts):
        if isinstance(result, list):
            all_alerts.extend(result)

    if not all_alerts:
        return "All systems healthy. No issues detected."

    return _format_alerts(all_alerts)
