"""
Observability API — REST endpoints for tracing, SLOs, alerting, and metrics.

Mount with:
    from chat_app.observability_api import router as obs_router
    app.include_router(obs_router)
"""
import logging

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/observability", tags=["observability"])


def _get_obs():
    from chat_app.observability import get_observability_manager
    return get_observability_manager()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/dashboard", summary="Full observability dashboard")
async def obs_dashboard():
    """Return comprehensive observability data (traces, SLOs, alerts, metrics)."""
    return _get_obs().get_dashboard_data()


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------

@router.get("/traces", summary="Get recent traces")
async def get_traces(limit: int = Query(default=20, ge=1, le=100)):
    """Return recent completed request traces."""
    return {
        "traces": _get_obs().get_recent_traces(limit=limit),
        "active": len(_get_obs()._active_traces),
    }


@router.get("/traces/{trace_id}", summary="Get a specific trace")
async def get_trace(trace_id: str):
    """Return a specific trace by ID."""
    obs = _get_obs()
    trace = obs.get_trace(trace_id)
    if not trace:
        return {"error": f"Trace '{trace_id}' not found"}
    return trace.to_dict()


# ---------------------------------------------------------------------------
# SLOs
# ---------------------------------------------------------------------------

@router.get("/slos", summary="Get SLO definitions and status")
async def get_slos():
    """Return all SLO definitions and their current status."""
    obs = _get_obs()
    statuses = obs.get_slo_status()
    return {
        "slos": [s.to_dict() for s in statuses],
        "all_met": all(s.is_met for s in statuses if s.sample_count > 0),
        "total": len(statuses),
    }


@router.get("/slos/{name}", summary="Get a specific SLO status")
async def get_slo(name: str):
    """Return status for a specific SLO."""
    obs = _get_obs()
    if name not in obs._slo_definitions:
        return {"error": f"SLO '{name}' not found"}
    statuses = obs.get_slo_status(slo_name=name)
    if not statuses:
        return {"error": f"SLO '{name}' not found"}
    return statuses[0].to_dict()


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@router.get("/alerts", summary="Get alert rules and recent fires")
async def get_alerts(limit: int = Query(default=50, ge=1, le=200)):
    """Return alert rules and recent fired alerts."""
    obs = _get_obs()
    return {
        "rules": [
            {
                "name": r.name,
                "severity": r.severity.value,
                "condition": r.condition,
                "metric": r.metric,
                "threshold": r.threshold,
                "fire_count": r.fire_count,
                "cooldown_seconds": r.cooldown_seconds,
            }
            for r in obs._alert_rules.values()
        ],
        "fired_alerts": obs.get_fired_alerts(limit=limit),
    }


@router.post("/alerts/evaluate", summary="Evaluate all alert rules now")
async def evaluate_alerts():
    """Manually evaluate all alert rules against current metrics."""
    obs = _get_obs()
    fired = obs.evaluate_alerts()
    return {
        "evaluated": len(obs._alert_rules),
        "fired": [
            {
                "alert_name": a.alert_name,
                "severity": a.severity.value,
                "message": a.message,
            }
            for a in fired
        ],
        "total_fired": len(fired),
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@router.get("/metrics", summary="Get all metrics summary")
async def get_metrics():
    """Return aggregated metrics (counters, gauges, histograms)."""
    return _get_obs().get_metrics_summary()
