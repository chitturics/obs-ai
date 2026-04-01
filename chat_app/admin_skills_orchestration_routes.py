"""Admin sub-router: Orchestration, Action Engine, Director Graph, and Workflow endpoints.

Extracted from admin_skills_routes.py to keep file sizes manageable.
All routes use the same prefix/tags/dependencies as skills_router.

Endpoints:
- GET  /api/admin/orchestration/strategies      — List orchestration strategies
- GET  /api/admin/orchestration/stats           — Execution statistics
- POST /api/admin/orchestration/strategy        — Set default strategy
- GET  /api/admin/orchestration/quality         — Strategy quality metrics
- POST /api/admin/orchestration/reset-stats     — Reset quality stats
- POST /api/admin/orchestration/test            — Run test orchestration
- GET  /api/admin/action-engine/status          — Action engine status
- GET  /api/admin/action-engine/history         — Recent action engine executions
- GET  /api/admin/director-graph/templates      — List director graph templates
- GET  /api/admin/director-graph/visualize/{t}  — Graph structure for visualization
- GET  /api/admin/workflows/history             — Persisted workflow history
- POST /api/admin/workflows/recover             — Recover interrupted workflows
- POST /api/admin/workflows/{id}/pause          — Pause a running workflow
- POST /api/admin/workflows/{id}/resume         — Resume a paused workflow
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from chat_app.auth_dependencies import require_admin
from chat_app.settings import get_settings
from chat_app.admin_shared import (
    _append_audit,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _safe_error,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router — same prefix/tags/dependencies as skills_router so routes merge
# ---------------------------------------------------------------------------

skills_orch_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-skills"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Orchestration Strategies
# ---------------------------------------------------------------------------

@skills_orch_router.get("/orchestration/strategies", summary="List available orchestration strategies")
async def list_orchestration_strategies():
    """Return all registered orchestration strategies with metadata."""
    try:
        from chat_app.orchestration_strategies import (
            list_strategies, FALLBACK_CHAIN,
        )
        strategies = []
        for s in list_strategies():
            name = s["name"]
            strategies.append({
                "name": name,
                "resource_weight": s["resource_weight"],
                "fallback_chain": FALLBACK_CHAIN.get(name, []),
                "description": s.get("description", ""),
            })
        settings = get_settings()
        orch = getattr(settings, "orchestration", None)
        return {
            "strategies": strategies,
            "current_default": orch.default_strategy if orch else "adaptive",
            "strategy_overrides": orch.strategy_overrides if orch else {},
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@skills_orch_router.get("/orchestration/stats", summary="Get orchestration execution statistics")
async def get_orchestration_stats(limit: int = Query(50, ge=1, le=500)):
    """Return execution log and summary statistics."""
    try:
        from chat_app.orchestration_strategies import (
            get_execution_log, get_orchestration_summary,
        )
        summary = get_orchestration_summary()
        return {
            **summary,
            "summary": summary,
            "recent_executions": get_execution_log(limit),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@skills_orch_router.post("/orchestration/strategy", summary="Change the default orchestration strategy")
async def set_orchestration_strategy(request: Request):
    """Set the default orchestration strategy at runtime."""
    body = await request.json()
    strategy_name = body.get("strategy")
    if not strategy_name:
        raise HTTPException(status_code=400, detail="Missing 'strategy' field")

    valid = [
        "single_agent", "parallel", "hierarchical", "iterative",
        "coordinator", "voting", "react", "review_critique",
        "workflow", "swarm", "human_in_loop", "adaptive",
    ]
    if strategy_name not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid strategy '{strategy_name}'. Valid: {valid}",
        )

    try:
        settings = get_settings()
        orch = getattr(settings, "orchestration", None)
        previous = orch.default_strategy if orch else "adaptive"

        if orch:
            orch.default_strategy = strategy_name

        try:
            from chat_app.config_manager import get_config_manager
            mgr = get_config_manager()
            mgr.update_section("orchestration", {"default_strategy": strategy_name})
        except Exception as _exc:  # broad catch — resilience against all failures
            logger.debug("[ORCH] Config file not writable -- in-memory update only")

        _append_audit(
            section="orchestration", action="set_strategy",
            changes={"default_strategy": strategy_name},
            previous={"default_strategy": previous},
        )
        return {
            "status": "ok",
            "strategy": strategy_name,
            "previous": previous,
            "persisted": False,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@skills_orch_router.get("/orchestration/quality", summary="Get strategy quality metrics")
async def get_orchestration_quality():
    """Return quality scores and trends for each orchestration strategy."""
    try:
        from chat_app.orchestration_strategies import get_strategy_quality_stats
        return {
            "status": "ok",
            "strategies": get_strategy_quality_stats(),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@skills_orch_router.post("/orchestration/reset-stats", summary="Reset orchestration quality stats")
async def reset_orchestration_stats():
    """Reset quality tracking statistics."""
    try:
        from chat_app.orchestration_strategies import _strategy_quality, _strategy_quality_lock
        with _strategy_quality_lock:
            _strategy_quality.clear()
        _append_audit(section="orchestration", action="reset_stats", changes={"cleared": True})
        return {"status": "ok", "message": "Quality stats reset", "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@skills_orch_router.post("/orchestration/test", summary="Run a test orchestration query")
async def test_orchestration():
    """Run a sample query through the orchestration pipeline to generate stats."""
    try:
        from chat_app.orchestration_strategies import execute_orchestration

        test_queries = [
            ("What is the stats command?", "spl_help"),
            ("Check system health", "config_health_check"),
            ("How to optimize a slow search?", "spl_optimization"),
        ]

        results = []
        for query, intent in test_queries:
            try:
                result = await execute_orchestration(
                    user_input=query,
                    intent=intent,
                    plan=type("Plan", (), {"intent": intent, "confidence": 0.9, "profile": "default"})(),
                    context=None,
                )
                results.append({
                    "query": query,
                    "intent": intent,
                    "strategy": result.strategy_used,
                    "success": result.success,
                    "quality": round(result.quality_score, 2),
                    "duration_ms": round(result.duration_ms, 0),
                    "iterations": result.iterations,
                })
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                results.append({"query": query, "error": str(exc)})

        _append_audit(section="orchestration", action="test_run", changes={"queries": len(results)})
        return {
            "status": "ok",
            "results": results,
            "message": f"Ran {len(results)} test queries through orchestration",
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


# ---------------------------------------------------------------------------
# Action Engine & Director Graph
# ---------------------------------------------------------------------------

@skills_orch_router.get("/action-engine/status", summary="Action engine status and action types")
async def action_engine_status():
    """Return available action types and skill mappings."""
    try:
        from chat_app.action_engine import ActionType, ActionState, ACTION_SKILL_MAP
        return {
            "status": "ok",
            "action_types": [
                {"name": t.name, "value": t.value, "skill": ACTION_SKILL_MAP.get(t, "")}
                for t in ActionType
            ],
            "action_states": [s.value for s in ActionState],
            "total_types": len(ActionType),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "action_engine_status"))


@skills_orch_router.get("/action-engine/history", summary="Recent action engine executions")
async def action_engine_history(limit: int = Query(50, ge=1, le=200)):
    """Return recent action engine and two-stage pipeline executions."""
    try:
        from chat_app.orchestration_strategies import get_execution_log
        log = get_execution_log(limit=limit)
        filtered = [
            e for e in log
            if e.get("strategy_used") in ("action_engine", "two_stage") or e.get("action_type")
        ]
        return {
            "status": "ok",
            "count": len(filtered),
            "entries": filtered,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "action_engine_history"))


@skills_orch_router.get("/director-graph/templates", summary="List director graph templates")
async def list_director_templates():
    """List available director graph templates."""
    try:
        from chat_app.director_graph import get_templates_summary
        templates = get_templates_summary()
        return {"status": "ok", "templates": templates, "count": len(templates)}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "director_graph_templates"))


@skills_orch_router.get("/director-graph/visualize/{template_name}", summary="Get graph structure for visualization")
async def visualize_director_graph(template_name: str):
    """Get node/edge structure of a director graph template for rendering."""
    try:
        from chat_app.director_graph import get_template_graph
        graph = get_template_graph(template_name)
        if not graph:
            raise HTTPException(404, f"Template '{template_name}' not found")
        return {"status": "ok", "template": template_name, **graph}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "director_graph_visualize"))


# ---------------------------------------------------------------------------
# Workflow Management
# ---------------------------------------------------------------------------

@skills_orch_router.get("/workflows/history", summary="Get persisted workflow history")
async def get_workflow_history(
    user_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """List persisted workflow executions from the database."""
    try:
        from chat_app.workflow_orchestrator import get_workflow_orchestrator
        orch = get_workflow_orchestrator()
        workflows = await orch.get_persisted_workflows(user_id=user_id, status=status, limit=limit)
        return {"status": "ok", "workflows": workflows, "count": len(workflows), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[ADMIN] Workflow history error: {exc}")
        return {"status": "ok", "workflows": [], "count": 0, "timestamp": _now_iso()}


@skills_orch_router.post("/workflows/recover", summary="Recover interrupted workflows")
async def recover_interrupted_workflows():
    """Mark any running workflows (from before restart) as interrupted."""
    try:
        from chat_app.workflow_orchestrator import get_workflow_orchestrator
        orch = get_workflow_orchestrator()
        interrupted = await orch.recover_interrupted()
        return {
            "status": "ok",
            "interrupted_count": len(interrupted),
            "workflow_ids": interrupted,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[ADMIN] Workflow recovery error: {exc}")
        return {"status": "ok", "interrupted_count": 0, "workflow_ids": [], "timestamp": _now_iso()}


@skills_orch_router.post("/workflows/{workflow_id}/pause", summary="Pause a running workflow")
async def pause_workflow(workflow_id: str, reason: str = "user_request"):
    """Pause an active workflow at the next task boundary."""
    try:
        from chat_app.workflow_orchestrator import get_workflow_orchestrator
        orch = get_workflow_orchestrator()
        success = await orch.pause_workflow(workflow_id, reason)
        if not success:
            raise HTTPException(404, f"Workflow {workflow_id} not found or not active")
        return {"status": "ok", "workflow_id": workflow_id, "paused": True, "timestamp": _now_iso()}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_orch_router.post("/workflows/{workflow_id}/resume", summary="Resume a paused workflow")
async def resume_workflow(workflow_id: str):
    """Resume a paused or waiting workflow."""
    try:
        from chat_app.workflow_orchestrator import get_workflow_orchestrator
        orch = get_workflow_orchestrator()
        result = await orch.resume_workflow(workflow_id)
        return {
            "status": "ok",
            "workflow_id": workflow_id,
            "resumed": True,
            "result": result.to_dict() if result else None,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))
