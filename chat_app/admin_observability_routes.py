"""Admin sub-router: Observability, monitoring, evolution, and GCI endpoints.

Handles these endpoint groups:
- GET  /api/admin/observability-summary     — Quick observability summary
- GET  /api/admin/observability/alerts/active — Active alerts within time window
- GET  /api/admin/observability/slos/status — All SLO statuses
- GET  /api/admin/observability/dashboard  — Unified observability dashboard
- GET  /api/admin/monitoring/realtime      — Real-time monitoring data
- POST /api/admin/monitoring/log-level     — Change runtime log level
- GET  /api/admin/monitoring/pipeline-traces — Pipeline trace history
- GET  /api/admin/monitoring/pipeline-traces/{request_id} — Specific trace
- GET  /api/admin/agents/metrics           — Per-agent performance metrics
- GET  /api/admin/agents/metrics/{agent_name} — Single agent metrics
- GET  /api/admin/skills/execution-metrics — Skill executor performance
- GET  /api/admin/evolution/*              — Evolution engine endpoints (8)
- GET  /api/admin/gci/*                    — GCI agent endpoints (5)
- GET  /api/admin/lineage/*               — Pipeline lineage endpoints (3)
- GET  /api/admin/execution-journal/*     — Execution journal endpoints (3)

Mount with:
    from chat_app.admin_observability_routes import observability_router
    app.include_router(observability_router)
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from chat_app.auth_dependencies import require_admin
from chat_app.admin_shared import (
    _csrf_check,
    _now_iso,
    _rate_limit,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

observability_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-observability"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Observability Summary
# ---------------------------------------------------------------------------

@observability_router.get("/observability-summary", summary="Quick observability summary")
async def observability_summary():
    """Return a quick observability summary for the admin dashboard."""
    try:
        from chat_app.observability import get_observability_manager
        obs = get_observability_manager()
        slo_statuses = obs.get_slo_status()
        return {
            "slos": {
                "total": len(slo_statuses),
                "met": sum(1 for s in slo_statuses if s.is_met),
                "breached": sum(1 for s in slo_statuses if not s.is_met and s.sample_count > 0),
                "status": [s.to_dict() for s in slo_statuses],
            },
            "alerts": {
                "total_rules": len(obs._alert_rules),
                "total_fired": sum(r.fire_count for r in obs._alert_rules.values()),
                "recent": obs.get_fired_alerts(limit=5),
            },
            "traces": {
                "total": len(obs._traces),
                "active": len(obs._active_traces),
            },
            "metrics_summary": obs.get_metrics_summary(),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/observability/alerts/active", summary="Active alerts within time window")
async def get_active_alerts(window_minutes: int = Query(60, ge=1, le=1440)):
    """Return persisted alerts from alerts.jsonl within *window_minutes*."""
    try:
        from chat_app.observability import (
            get_observability_manager,
            get_active_alerts as _get_active,
        )
        obs = get_observability_manager()
        newly_fired = obs.evaluate_alerts()
        active = _get_active(window_minutes=window_minutes)
        return {
            "window_minutes": window_minutes,
            "newly_fired": len(newly_fired),
            "active_count": len(active),
            "active_alerts": active,
            "total_rules": len(obs._alert_rules),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/observability/slos/status", summary="All SLO statuses")
async def get_slo_status():
    """Return current status of all SLO definitions."""
    try:
        from chat_app.observability import get_observability_manager
        obs = get_observability_manager()
        slo_statuses = obs.get_slo_status()
        return {
            "total": len(slo_statuses),
            "met": sum(1 for s in slo_statuses if s.is_met),
            "breached": sum(1 for s in slo_statuses if not s.is_met and s.sample_count > 0),
            "slos": [s.to_dict() for s in slo_statuses],
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Evolution Engine
# ---------------------------------------------------------------------------

@observability_router.get("/evolution/status", summary="Evolution engine status")
async def get_evolution_status():
    """Get comprehensive evolution status: targets, staleness, diagnosis, agent competition."""
    try:
        from chat_app.evolution_engine import get_evolution_engine
        engine = get_evolution_engine()
        return engine.get_status()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/evolution/targets", summary="Adaptive quality targets")
async def get_evolution_targets():
    """Get all adaptive targets with current values, gaps, and trends."""
    try:
        from chat_app.evolution_engine import get_evolution_engine
        engine = get_evolution_engine()
        return {"targets": engine.get_targets(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/evolution/staleness", summary="Component staleness report")
async def get_evolution_staleness():
    """Detect staleness across all knowledge components."""
    try:
        from chat_app.evolution_engine import get_evolution_engine, StalenessLevel
        engine = get_evolution_engine()
        reports = await engine.detect_staleness()
        return {
            "total": len(reports),
            "by_level": {level.value: sum(1 for r in reports if r.level == level)
                        for level in StalenessLevel},
            "reports": [{"component": r.component, "level": r.level.value,
                        "age_hours": r.age_hours, "diagnosis": r.diagnosis}
                       for r in reports],
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/evolution/diagnosis", summary="Root cause diagnosis")
async def get_evolution_diagnosis():
    """Run root cause analysis on current quality gaps."""
    try:
        from chat_app.evolution_engine import get_evolution_engine
        engine = get_evolution_engine()
        diagnosis = await engine.diagnose_root_causes()
        return {
            "primary_cause": diagnosis.primary_cause.value,
            "confidence": round(diagnosis.confidence, 2),
            "evidence": diagnosis.evidence,
            "secondary_causes": [c.value for c in diagnosis.secondary_causes],
            "recommended_actions": diagnosis.recommended_actions,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/evolution/strategy-matrix", summary="Strategy payoff matrix")
async def get_strategy_matrix():
    """Get game-theoretic strategy payoff matrix with Nash equilibria."""
    try:
        from chat_app.evolution_engine import get_evolution_engine
        engine = get_evolution_engine()
        return engine.get_strategy_payoff_matrix()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/evolution/agent-rankings", summary="Agent competition rankings")
async def get_agent_competition_rankings():
    """Get agent reputation rankings with UCB1 exploration scores."""
    try:
        from chat_app.evolution_engine import get_evolution_engine
        engine = get_evolution_engine()
        return {
            "rankings": engine.get_agent_rankings(),
            "ucb1_scores": engine.get_agent_ucb1_scores(),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/evolution/improvements", summary="Improvement action queue")
async def get_improvement_queue():
    """Get the prioritized queue of improvement actions."""
    try:
        from chat_app.evolution_engine import get_evolution_engine
        engine = get_evolution_engine()
        return {"actions": engine.get_improvement_queue(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.post("/evolution/assess", summary="Trigger evolution assessment")
async def trigger_evolution_assessment_obs():
    """Trigger a full evolution assessment cycle (normally runs during idle time)."""
    try:
        from chat_app.evolution_engine import get_evolution_engine
        engine = get_evolution_engine()
        result = await engine.run_assessment()
        if isinstance(result, dict) and result.get("error"):
            from fastapi import HTTPException as _HTTPExc
            raise _HTTPExc(status_code=500, detail=result["error"])
        return result
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        from fastapi import HTTPException as _HTTPExc
        raise _HTTPExc(status_code=500, detail=f"Evolution assessment failed: {exc}")


# ---------------------------------------------------------------------------
# GCI Agent (Governance & Continuous Improvement)
# ---------------------------------------------------------------------------

@observability_router.get("/gci/status", summary="GCI agent status")
async def get_gci_status():
    """Get GCI agent status: interactions reviewed, intercept rate, directives."""
    try:
        from chat_app.gci_agent import get_gci_agent
        return get_gci_agent().get_status()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/gci/agent-trends", summary="Per-agent quality trends")
async def get_gci_agent_trends():
    """Get per-agent performance trends from the GCI agent."""
    try:
        from chat_app.gci_agent import get_gci_agent
        return {"trends": get_gci_agent().get_agent_trends(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/gci/directives", summary="Improvement directives")
async def get_gci_directives(agent_id: Optional[str] = None):
    """Get GCI improvement directives, optionally filtered by agent."""
    try:
        from chat_app.gci_agent import get_gci_agent
        return {"directives": get_gci_agent().get_directives(agent_id), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/gci/trend-reports", summary="GCI trend reports")
async def get_gci_trend_reports():
    """Get historical GCI trend reports (generated every 50 interactions)."""
    try:
        from chat_app.gci_agent import get_gci_agent
        return {"reports": get_gci_agent().get_trend_reports(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/gci/interactions", summary="Recent interactions with quality scores")
async def get_gci_interactions(limit: int = 20, agent_id: Optional[str] = None):
    """Get recent interaction records with GCI quality scores."""
    try:
        from chat_app.gci_agent import get_gci_agent
        return {"interactions": get_gci_agent().get_recent_interactions(limit, agent_id), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Real-time Monitoring
# ---------------------------------------------------------------------------

@observability_router.get("/monitoring/realtime", summary="Real-time monitoring dashboard data")
async def get_realtime_monitoring():
    """Comprehensive real-time monitoring: counters, pipeline traces, agent metrics, service health, warmup status."""
    result = {"timestamp": _now_iso()}

    # 1. Counters (now Redis-persisted, survive restarts)
    try:
        from chat_app.health_monitor import get_internal_metrics
        metrics = get_internal_metrics().get_all()
        result["counters"] = metrics.get("counters", {})
        result["gauges"] = metrics.get("gauges", {})
        result["latency_p50"] = metrics.get("latency_p50", 0)
        result["latency_p95"] = metrics.get("latency_p95", 0)
    except Exception as _exc:  # broad catch — resilience against all failures
        result["counters"] = {}

    # 2. Recent pipeline traces with stage breakdown
    try:
        from chat_app.pipeline_lineage import get_recent_traces, get_stage_stats
        traces = get_recent_traces(10)
        result["recent_traces"] = [t.to_summary() if hasattr(t, 'to_summary') else t for t in traces]
        result["stage_stats"] = get_stage_stats()
    except Exception as _exc:  # broad catch — resilience against all failures
        result["recent_traces"] = []

    # 3. Agent dispatch summary with reasoning
    try:
        from chat_app.agent_dispatcher import get_agent_dispatcher
        dispatcher = get_agent_dispatcher()
        result["agent_summary"] = dispatcher.get_summary()
        result["agent_metrics"] = dispatcher.get_agent_metrics()
        result["recent_dispatches"] = dispatcher.get_dispatch_log(limit=5)
    except Exception as _exc:  # broad catch — resilience against all failures
        result["agent_summary"] = {}

    # 4. Skill execution stats
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        exec_stats = executor.get_metrics()
        result["skill_stats"] = {
            "total_skills": exec_stats.get("available_skills", 84),
            "total_executions": exec_stats.get("total_executions", 0),
            "error_rate": exec_stats.get("error_rate", 0),
        }
    except Exception as _exc:  # broad catch — resilience against all failures
        result["skill_stats"] = {}

    # 5. Collection status
    try:
        import chromadb
        client = chromadb.HttpClient(host="localhost", port=8001)
        cols = client.list_collections()
        result["collections"] = {c.name: c.count() for c in cols}
        result["total_documents"] = sum(c.count() for c in cols)
    except Exception as _exc:  # broad catch — resilience against all failures
        result["collections"] = {}

    # 6. Startup warmup status
    try:
        from chat_app.startup_warmup import get_warmup_result, is_warmup_complete
        result["warmup"] = {
            "complete": is_warmup_complete(),
            "result": get_warmup_result(),
        }
    except Exception as _exc:  # broad catch — resilience against all failures
        result["warmup"] = {"complete": False}

    # 7. Current log level
    try:
        from chat_app.logging_utils import get_log_level
        result["log_level"] = get_log_level()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[%s] %%s", "admin_observability_routes.py", _exc)

    return result


@observability_router.post("/monitoring/log-level", summary="Change runtime log level")
async def set_log_level_endpoint(request: Request):
    """Change log level at runtime. Body: {"level": "DEBUG|INFO|WARNING|ERROR"}"""
    body = await request.json()
    level = body.get("level", "INFO")
    if level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise HTTPException(400, f"Invalid log level: {level}")
    from chat_app.logging_utils import set_log_level
    new_level = set_log_level(level)
    logger.info("[ADMIN] Log level changed to %s", new_level)
    return {"status": "ok", "level": new_level}


@observability_router.get("/monitoring/pipeline-traces", summary="Get pipeline trace history")
async def get_pipeline_traces(limit: int = Query(default=50, le=200)):
    """Get recent pipeline traces with full stage breakdown."""
    try:
        from chat_app.pipeline_lineage import get_recent_traces, get_stage_stats
        return {
            "traces": get_recent_traces(limit),
            "stage_stats": get_stage_stats(),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"traces": [], "error": str(exc)}


@observability_router.get("/monitoring/pipeline-traces/{request_id}", summary="Get a specific pipeline trace")
async def get_pipeline_trace_by_id(request_id: str):
    """Get full pipeline trace for a specific request ID."""
    try:
        from chat_app.pipeline_lineage import get_trace_by_id
        trace = get_trace_by_id(request_id)
        if not trace:
            raise HTTPException(404, f"Trace {request_id} not found")
        return trace
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


# ---------------------------------------------------------------------------
# Agent & Skill Performance Metrics
# ---------------------------------------------------------------------------

@observability_router.get("/agents/metrics", summary="Per-agent performance metrics")
async def get_agent_performance_metrics():
    """Return per-agent dispatch success rate, latency, quality, and recent activity."""
    try:
        from chat_app.agent_dispatcher import get_agent_dispatcher
        disp = get_agent_dispatcher()
        return {
            "summary": disp.get_summary(),
            "per_agent": disp.get_agent_metrics(),
            "quality_data": {
                agent: {
                    intent: {"count": len(scores), "avg": round(sum(scores) / len(scores), 3) if scores else 0,
                             "recent_5": [round(s, 3) for s in scores[-5:]]}
                    for intent, scores in intents.items()
                }
                for agent, intents in disp._agent_quality.items()
            },
            "recent_dispatches": disp.get_dispatch_log(limit=20),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/agents/metrics/{agent_name}", summary="Detailed metrics for one agent")
async def get_single_agent_metrics(agent_name: str):
    """Return detailed metrics for one specific agent."""
    try:
        from chat_app.agent_dispatcher import get_agent_dispatcher
        disp = get_agent_dispatcher()
        all_metrics = disp.get_agent_metrics()
        agent_data = all_metrics.get(agent_name)
        if not agent_data:
            raise HTTPException(404, f"Agent '{agent_name}' not found")
        quality = disp._agent_quality.get(agent_name, {})
        return {
            "agent_name": agent_name,
            "metrics": agent_data,
            "quality": {
                intent: {"count": len(scores), "avg": round(sum(scores) / len(scores), 3) if scores else 0,
                         "scores": [round(s, 3) for s in scores[-20:]]}
                for intent, scores in quality.items()
            },
            "recent_dispatches": [
                d for d in disp.get_dispatch_log(limit=50)
                if d.get("agent_name") == agent_name
            ][:20],
            "timestamp": _now_iso(),
        }
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@observability_router.get("/skills/execution-metrics", summary="Skill executor performance metrics")
async def get_skill_execution_metrics():
    """Return per-skill execution stats: success rate, latency, error patterns."""
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        stats = executor.get_metrics()
        log = executor.get_execution_log(100)

        # Aggregate per-skill metrics from execution log
        skill_metrics = {}
        for entry in log:
            name = entry.get("skill_name", "unknown")
            if name not in skill_metrics:
                skill_metrics[name] = {"total": 0, "success": 0, "errors": 0, "latencies": []}
            skill_metrics[name]["total"] += 1
            if entry.get("success"):
                skill_metrics[name]["success"] += 1
            else:
                skill_metrics[name]["errors"] += 1
            if "duration_ms" in entry:
                skill_metrics[name]["latencies"].append(entry["duration_ms"])

        # Compute summary stats
        for name, m in skill_metrics.items():
            lats = m.pop("latencies", [])
            m["success_rate"] = round(m["success"] / m["total"] * 100, 1) if m["total"] > 0 else 0
            m["avg_latency_ms"] = round(sum(lats) / len(lats), 1) if lats else 0
            m["p95_latency_ms"] = round(sorted(lats)[int(len(lats) * 0.95)] if lats else 0, 1)

        return {
            "status": "ok",
            "summary": stats,
            "per_skill": skill_metrics,
            "recent_executions": log[:20],
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Pipeline Lineage
# ---------------------------------------------------------------------------

@observability_router.get("/lineage/recent/list", summary="Recent pipeline traces")
async def get_recent_lineage(limit: int = Query(50, ge=1, le=200)):
    """Get recent pipeline traces with summaries."""
    try:
        from chat_app.pipeline_lineage import get_recent_traces
        traces = get_recent_traces(limit)
        return {"status": "ok", "count": len(traces), "traces": traces}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@observability_router.get("/lineage/stats", summary="Pipeline lineage statistics")
async def get_lineage_stats():
    """Get stage-level latency and success rate statistics."""
    try:
        from chat_app.pipeline_lineage import get_stage_stats, get_recent_traces
        stats = get_stage_stats()
        recent = get_recent_traces(10)
        return {"status": "ok", "stage_stats": stats, "recent_count": len(recent)}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@observability_router.get("/lineage/{request_id}", summary="Pipeline trace by request ID")
async def get_lineage_trace(request_id: str):
    """Get full pipeline trace for a specific request."""
    try:
        from chat_app.pipeline_lineage import get_trace_by_id
        trace = get_trace_by_id(request_id)
        if not trace:
            raise HTTPException(404, f"Trace {request_id} not found")
        return {"status": "ok", "trace": trace}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


# ---------------------------------------------------------------------------
# Execution Journal
# ---------------------------------------------------------------------------

@observability_router.get("/execution-journal/files", summary="List execution journal files")
async def list_journal_files():
    """List execution journal files with sizes."""
    try:
        from chat_app.execution_journal import get_journal
        journal = get_journal()
        files = journal.list_files()
        return {"status": "ok", "files": files, "count": len(files)}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@observability_router.get("/execution-journal/query", summary="Query execution journal")
async def query_journal(
    event_type: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
):
    """Query execution journal events by type and date."""
    try:
        from chat_app.execution_journal import get_journal
        journal = get_journal()
        events = journal.query_events(event_type=event_type, date=date, limit=limit)
        return {"status": "ok", "count": len(events), "events": events}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@observability_router.get("/execution-journal/stats", summary="Execution journal statistics")
async def journal_stats():
    """Get execution journal statistics."""
    try:
        from chat_app.execution_journal import get_journal
        journal = get_journal()
        return {"status": "ok", **journal.get_stats()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


# ---------------------------------------------------------------------------
# GET /api/admin/observability/dashboard — unified observability dashboard
# ---------------------------------------------------------------------------

@observability_router.get("/observability/dashboard", summary="Unified observability dashboard")
async def get_observability_dashboard():
    """Return a comprehensive observability snapshot for the dashboard page.

    Aggregates SLO status, alert counts, recent traces, metrics summary,
    agent dispatch stats, and skill execution metrics into a single response
    so the frontend can render the full observability page in one request.
    """
    result: dict = {"status": "ok", "timestamp": _now_iso()}

    # SLO / alert summary
    try:
        from chat_app.observability import get_observability_manager
        obs = get_observability_manager()
        slo_statuses = obs.get_slo_status()
        result["slos"] = {
            "total": len(slo_statuses),
            "met": sum(1 for s in slo_statuses if s.is_met),
            "breached": sum(1 for s in slo_statuses if not s.is_met and s.sample_count > 0),
            "items": [s.to_dict() for s in slo_statuses],
        }
        result["alerts"] = {
            "total_rules": len(obs._alert_rules),
            "total_fired": sum(r.fire_count for r in obs._alert_rules.values()),
            "recent": obs.get_fired_alerts(limit=10),
        }
        result["traces_summary"] = {
            "total": len(obs._traces),
            "active": len(obs._active_traces),
        }
        result["metrics_summary"] = obs.get_metrics_summary()
    except Exception as exc:  # broad catch — resilience at boundary
        result["slos"] = {"error": str(exc)}
        result["alerts"] = {}

    # Internal metrics (counters, latency)
    try:
        from chat_app.health_monitor import get_internal_metrics
        metrics = get_internal_metrics().get_all()
        result["counters"] = metrics.get("counters", {})
        result["latency_p50"] = metrics.get("latency_p50", 0)
        result["latency_p95"] = metrics.get("latency_p95", 0)
    except Exception:  # broad catch — resilience at boundary
        result["counters"] = {}

    # Agent dispatch stats
    try:
        from chat_app.agent_dispatcher import get_agent_dispatcher
        dispatcher = get_agent_dispatcher()
        result["agent_summary"] = dispatcher.get_summary()
    except Exception:  # broad catch — resilience at boundary
        result["agent_summary"] = {}

    # Skill execution stats
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        exec_stats = executor.get_metrics()
        result["skill_stats"] = {
            "total_skills": exec_stats.get("available_skills", 0),
            "total_executions": exec_stats.get("total_executions", 0),
            "error_rate": exec_stats.get("error_rate", 0),
        }
    except Exception:  # broad catch — resilience at boundary
        result["skill_stats"] = {}

    # Recent pipeline traces (top 5 for overview)
    try:
        from chat_app.pipeline_lineage import get_recent_traces
        traces = get_recent_traces(5)
        result["recent_traces"] = [t.to_summary() if hasattr(t, "to_summary") else t for t in traces]
    except Exception:  # broad catch — resilience at boundary
        result["recent_traces"] = []

    return result


# ---------------------------------------------------------------------------
# GET /api/admin/traces — recent query pipeline traces
# ---------------------------------------------------------------------------

@observability_router.get("/traces", summary="Recent query traces")
async def get_traces(limit: int = Query(default=50, ge=1, le=200)):
    """Return recent query pipeline traces with stage-level latency breakdown.

    Delegates to the pipeline_lineage module which records per-request traces
    as queries flow through the retrieval → rerank → LLM pipeline.
    """
    try:
        from chat_app.pipeline_lineage import get_recent_traces, get_stage_stats
        raw_traces = get_recent_traces(limit)
        traces = [t.to_summary() if hasattr(t, "to_summary") else t for t in raw_traces]
        return {
            "status": "ok",
            "count": len(traces),
            "traces": traces,
            "stage_stats": get_stage_stats(),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {
            "status": "ok",
            "count": 0,
            "traces": [],
            "stage_stats": {},
            "note": f"Pipeline lineage unavailable: {exc}",
            "timestamp": _now_iso(),
        }


# ---------------------------------------------------------------------------
# GET /api/admin/analytics — query analytics and usage metrics
# ---------------------------------------------------------------------------

@observability_router.get("/analytics", summary="Query analytics and usage metrics")
async def get_analytics():
    """Return aggregated query analytics: intent distribution, volume trends, collection usage.

    Combines in-memory activity data (intent counts, per-minute query volume,
    per-collection hit counts) with LLM cost data when available, giving a
    comprehensive usage overview for the analytics dashboard page.
    """
    from chat_app.admin_shared import (
        _intent_counts,
        _query_volume,
        _recent_queries,
        _collection_hit_counts,
    )

    # Intent distribution
    total_queries = sum(_intent_counts.values()) or 0
    intent_dist = [
        {
            "intent": intent,
            "count": count,
            "pct": round(count / total_queries * 100, 1) if total_queries else 0,
        }
        for intent, count in sorted(_intent_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    # Per-minute query volume (last 60 minutes)
    recent_volume = list(_query_volume[-60:])

    # Collection hit counts
    collection_usage = [
        {"collection": name, "hits": count}
        for name, count in sorted(_collection_hit_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    # Average latency from recent queries
    latencies = [q.get("duration_ms", 0) for q in _recent_queries if q.get("duration_ms")]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0

    # Top queries by frequency (last 200)
    query_freq: dict = {}
    for q in _recent_queries:
        text = q.get("query", "")[:120]
        query_freq[text] = query_freq.get(text, 0) + 1
    top_queries = [
        {"query": q, "count": c}
        for q, c in sorted(query_freq.items(), key=lambda x: x[1], reverse=True)[:20]
    ]

    # LLM cost analytics (best-effort)
    cost_data: dict = {}
    try:
        from chat_app.llm_cost_tracker import get_cost_summary
        cost_data = get_cost_summary()
    except Exception:  # broad catch — resilience at boundary
        pass

    return {
        "status": "ok",
        "total_queries": total_queries,
        "avg_latency_ms": avg_latency,
        "intent_distribution": intent_dist,
        "query_volume_per_minute": recent_volume,
        "collection_usage": collection_usage,
        "top_queries": top_queries,
        "cost_summary": cost_data,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Prometheus Time-Series Query Endpoint
# ---------------------------------------------------------------------------

@observability_router.get("/observability/metrics/timeseries", summary="Query Prometheus time-series data")
async def prometheus_timeseries(
    metric: str = Query(default="process_resident_memory_bytes", description="Prometheus metric name"),
    hours: int = Query(default=1, ge=1, le=168, description="Hours of history (1-168)"),
    step: int = Query(default=60, ge=15, le=3600, description="Step interval in seconds"),
):
    """Query Prometheus for time-series data. Used by frontend charts."""
    import httpx
    import time as _time

    prom_url = os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090")
    end = int(_time.time())
    start = end - (hours * 3600)

    # Allowlist of safe metrics (prevent arbitrary queries)
    safe_prefixes = [
        "process_", "python_gc_", "http_request_", "obsai_",
        "promhttp_", "up", "scrape_",
    ]
    if not any(metric.startswith(p) for p in safe_prefixes):
        raise HTTPException(status_code=400, detail=f"Metric '{metric}' not in allowlist. Use process_*, python_gc_*, http_request_*, obsai_*")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{prom_url}/api/v1/query_range",
                params={"query": metric, "start": start, "end": end, "step": step},
            )
            data = resp.json()

        if data.get("status") != "success":
            return {"series": [], "error": data.get("error", "Query failed")}

        series = []
        for result in data.get("data", {}).get("result", []):
            labels = result.get("metric", {})
            values = [{"timestamp": int(v[0]), "value": float(v[1])} for v in result.get("values", [])]
            series.append({
                "labels": labels,
                "job": labels.get("job", "unknown"),
                "values": values,
            })

        return {
            "metric": metric,
            "hours": hours,
            "step": step,
            "series": series,
            "total_points": sum(len(s["values"]) for s in series),
            "timestamp": _now_iso(),
        }
    except Exception as exc:
        return {"series": [], "error": str(exc), "timestamp": _now_iso()}


@observability_router.get("/observability/metrics/available", summary="List available Prometheus metrics")
async def prometheus_metrics_list():
    """List available Prometheus metrics for the time-series chart selector."""
    return {
        "metrics": [
            {"name": "process_resident_memory_bytes", "label": "Memory Usage (bytes)", "category": "resource"},
            {"name": "process_cpu_seconds_total", "label": "CPU Time (seconds)", "category": "resource"},
            {"name": "process_open_fds", "label": "Open File Descriptors", "category": "resource"},
            {"name": "python_gc_objects_collected_total", "label": "GC Objects Collected", "category": "runtime"},
            {"name": "python_gc_collections_total", "label": "GC Collections", "category": "runtime"},
            {"name": "process_start_time_seconds", "label": "Process Start Time", "category": "system"},
        ],
        "timestamp": _now_iso(),
    }
