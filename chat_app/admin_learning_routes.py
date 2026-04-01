"""Admin sub-router: Learning, feedback, knowledge graph, splunkbase, guardrails.

Handles these endpoint groups:
- GET  /api/admin/learning/dashboard    — Learning process visibility
- GET  /api/admin/retrieval/rerank-stats — Reranking quality metrics
- POST /api/admin/learn/trigger         — Trigger a learning cycle
- GET  /api/admin/feedback              — User feedback
- POST /api/admin/feedback/feature-request — Submit feature request
- GET  /api/admin/feedback/feature-requests — List feature requests
- GET  /api/admin/agent-tasks           — Agent task types and status
- GET  /api/admin/knowledge-graph/*     — Knowledge graph endpoints (6)
- GET  /api/admin/splunkbase/*          — Splunkbase catalog endpoints (5)
- GET  /api/admin/guardrails/*          — Guardrails endpoints (2)
- GET  /api/admin/memory/archival/*     — Archival memory endpoints (3)

Mount with:
    from chat_app.admin_learning_routes import learning_router
"""

import logging
import uuid

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.admin_shared import (
    _csrf_check,
    _now_iso,
    _rate_limit,
    _track_audit_user,
)

# Knowledge graph, splunkbase, guardrails, and archival memory extracted
from chat_app.admin_learning_ext_routes import (  # noqa: F401
    learning_ext_router,
)

logger = logging.getLogger(__name__)

learning_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-learning"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)

# Public feedback router — accessible to ANY authenticated user (not just admins)
learning_public_router = APIRouter(
    prefix="/api/admin/public-feedback",
    tags=["feedback-public"],
    dependencies=[Depends(_rate_limit)],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class FeatureRequestModel(BaseModel):
    """Submit a feature request."""
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10)
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical|Low|Medium|High|Critical)$")
    category: str = Field(default="general")


# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

_FEATURE_REQUESTS_PATH = Path("/app/data/feature_requests.json")

def _load_feature_requests() -> List[Dict[str, Any]]:
    """Load feature requests from disk (persistent across restarts)."""
    try:
        if _FEATURE_REQUESTS_PATH.is_file():
            import json as _json
            return _json.loads(_FEATURE_REQUESTS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[ADMIN] Failed to load feature requests: %s", exc)
    return []

def _save_feature_requests(requests: List[Dict[str, Any]]) -> None:
    """Persist feature requests to disk."""
    try:
        import json as _json
        _FEATURE_REQUESTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _FEATURE_REQUESTS_PATH.write_text(
            _json.dumps(requests, indent=2, default=str), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("[ADMIN] Failed to save feature requests: %s", exc)

_feature_requests: List[Dict[str, Any]] = _load_feature_requests()


# ---------------------------------------------------------------------------
# Learning Dashboard
# ---------------------------------------------------------------------------

@learning_router.get("/learning/dashboard", summary="Learning process visibility")
async def get_learning_dashboard():
    """Learning job schedule, execution history, improvement trends."""
    history = []
    trend = {}
    try:
        from chat_app.resource_manager import get_learning_history, get_learning_trend
        history = get_learning_history(limit=20)
        trend = get_learning_trend(window=10)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _lh_err:
        logger.debug(f"[ADMIN] Failed to load learning history: {_lh_err}")

    job_history = []
    try:
        from containers.search_opt.scheduler import _job_history
        job_history = list(_job_history[-20:])
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _jh_err:
        logger.debug(f"[ADMIN] Failed to load job history: {_jh_err}")

    reports = []
    try:
        import json as _json
        report_dir = Path("/app/data/learning_reports")
        if report_dir.is_dir():
            for f in sorted(report_dir.glob("learning_*.json"), reverse=True)[:10]:
                try:
                    data = _json.loads(f.read_text())
                    reports.append({
                        "file": f.name,
                        "timestamp": data.get("timestamp"),
                        "qa_pairs": data.get("qa_pairs_generated", 0),
                        "facts_learned": data.get("facts_learned", 0),
                        "duration_seconds": data.get("duration_seconds", 0),
                    })
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                    logger.debug(f"[ADMIN] Failed to parse learning report: {exc}")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to scan learning reports: {exc}")

    learning_stats = {}
    try:
        from chat_app.health_monitor import get_learning_stats
        from chat_app.settings import get_settings as _gs
        s = _gs()
        if hasattr(s, "get_db_engine"):
            engine = s.get_db_engine()
            if engine:
                learning_stats = await get_learning_stats(engine)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to load learning stats: {exc}")

    job_schedule = [
        {"name": "auto_heal", "frequency": "Every 5 minutes", "description": "Service health checks and auto-recovery"},
        {"name": "hourly_learn", "frequency": "Every hour (minute 15)", "description": "Learn from recent feedback patterns"},
        {"name": "daily_analyze", "frequency": "Daily at 2:00 AM", "description": "Re-analyze saved searches, refresh knowledge"},
        {"name": "weekly_assessment", "frequency": "Sunday at 3:00 AM", "description": "Feedback trends, pattern effectiveness review"},
        {"name": "monthly_audit", "frequency": "1st of month at 4:00 AM", "description": "Full audit, model customization, pattern pruning"},
    ]

    return {
        "job_schedule": job_schedule,
        "job_history": job_history,
        "learning_history": history,
        "learning_trend": trend,
        "learning_stats": learning_stats,
        "reports": reports,
        "timestamp": _now_iso(),
    }


@learning_router.get("/retrieval/rerank-stats", summary="Reranking quality metrics")
async def get_rerank_stats():
    """Cross-encoder reranking quality statistics."""
    try:
        from chat_app.reranker import get_rerank_stats as _rerank_stats
        stats = _rerank_stats()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to get rerank stats: {exc}")
        stats = {"error": str(exc)}

    intent_weights = {}
    try:
        from chat_app.self_adaptive_rag import get_adaptive_rag
        rag = get_adaptive_rag()
        intent_weights = rag.intent_collection_stats
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[%s] %%s", "admin_learning_routes.py", _exc)

    return {
        "rerank_stats": stats,
        "intent_collection_tracking": intent_weights,
        "timestamp": _now_iso(),
    }


@learning_router.post("/learn/trigger", summary="Trigger a learning cycle")
async def trigger_learning_cycle():
    """Proxy to trigger a manual learning cycle."""
    try:
        from chat_app.self_learning import run_learning_cycle
        from chat_app.admin_users_routes import _get_engine
        engine = _get_engine()
        from chat_app.vectorstore import get_vector_store
        vector_store = get_vector_store()
        report = await run_learning_cycle(engine=engine, vector_store=vector_store)
        return {
            "status": "completed",
            "qa_pairs_generated": getattr(report, "qa_pairs_generated", 0),
            "answers_reassessed": getattr(report, "answers_reassessed", 0),
            "facts_learned": getattr(report, "facts_learned", 0),
            "duration_seconds": getattr(report, "duration_seconds", 0),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[ADMIN] Learning trigger failed: {exc}")
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Agent Tasks
# ---------------------------------------------------------------------------

def _get_skills_manager():
    try:
        from chat_app.skills_manager import SkillsManager
        return SkillsManager()
    except Exception as _exc:  # broad catch — resilience against all failures
        return None


@learning_router.get("/agent-tasks", summary="List agent task types and status")
async def list_agent_tasks(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all registered agent tasks and their execution stats."""
    tasks = []

    try:
        from chat_app.tool_effectiveness import get_effectiveness_tracker
        tracker = get_effectiveness_tracker()
        tool_stats = tracker.get_tool_stats()
        for tool_name, stats in tool_stats.items():
            tasks.append({
                "name": tool_name,
                "type": "tool",
                "executions": stats["total_executions"],
                "success_rate": stats["success_rate"],
                "avg_latency_ms": stats["avg_latency_ms"],
            })
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to load tool registry tasks: {exc}")

    try:
        mgr = _get_skills_manager()
        if mgr:
            for skill_info in mgr.list_skills():
                for action in skill_info.get("actions", []):
                    tasks.append({
                        "name": f"{skill_info['name']}.{action}",
                        "type": "skill_action",
                        "skill": skill_info["name"],
                        "status": skill_info["status"],
                    })
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to load skill actions: {exc}")

    builtin = [
        {"name": "spl_analysis", "type": "builtin", "description": "Analyze SPL queries for issues"},
        {"name": "spl_optimization", "type": "builtin", "description": "Optimize SPL queries"},
        {"name": "config_lookup", "type": "builtin", "description": "Look up Splunk config references"},
        {"name": "knowledge_gap_detection", "type": "builtin", "description": "Detect knowledge gaps"},
        {"name": "self_learning", "type": "builtin", "description": "Self-learning pipeline"},
        {"name": "quality_evaluation", "type": "builtin", "description": "Response quality scoring"},
        {"name": "proactive_insights", "type": "builtin", "description": "Proactive optimization suggestions"},
    ]

    all_tasks = tasks + builtin
    total = len(all_tasks)
    page = all_tasks[offset:offset + limit]
    return {
        "tasks": page,
        "total": total,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Feedback & Feature Requests
# ---------------------------------------------------------------------------

@learning_router.get("/feedback", summary="Get user feedback and feature requests")
async def get_feedback(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    rating_filter: Optional[int] = Query(default=None, ge=1, le=5),
):
    """Return collected user feedback and feature requests."""
    feedback_items = []

    try:
        from chat_app.human_loop import get_human_loop_manager
        hlm = get_human_loop_manager()
        for fb in hlm.get_recent_feedback(limit=500):
            feedback_items.append({**fb, "source": "human_loop"})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to load human loop feedback: {exc}")

    try:
        from feedback_logger import get_recent_interactions
        interactions = await get_recent_interactions(limit=500)
        for item in interactions:
            if isinstance(item, dict) and item.get("feedback"):
                feedback_items.append({
                    "query": item.get("query", "")[:100],
                    "rating": item.get("rating"),
                    "feedback": item.get("feedback"),
                    "timestamp": item.get("timestamp"),
                    "source": "feedback_logger",
                })
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to load feedback logger data: {exc}")

    if rating_filter:
        feedback_items = [f for f in feedback_items if f.get("rating") == rating_filter]

    try:
        from chat_app.human_loop import get_human_loop_manager
        hlm = get_human_loop_manager()
        metrics = hlm.get_metrics()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to load satisfaction metrics: {exc}")
        metrics = {}

    total = len(feedback_items)
    page = feedback_items[offset:offset + limit]
    return {
        "feedback": page,
        "total": total,
        "satisfaction_score": metrics.get("satisfaction_score", 0),
        "avg_rating": metrics.get("avg_feedback_rating", 0),
        "timestamp": _now_iso(),
    }


@learning_router.post("/feedback/feature-request", summary="Submit a feature request")
async def submit_feature_request(body: FeatureRequestModel):
    """Submit a feature request or enhancement suggestion."""
    request = {
        "id": str(uuid.uuid4()),
        "title": body.title,
        "description": body.description,
        "priority": body.priority,
        "category": body.category,
        "status": "open",
        "created_at": _now_iso(),
    }
    _feature_requests.append(request)
    _save_feature_requests(_feature_requests)
    logger.info("[ADMIN] Feature request submitted: %s (priority=%s)", body.title, body.priority)
    return {"request": request, "timestamp": _now_iso()}


@learning_router.get("/feedback/feature-requests", summary="List feature requests")
async def list_feature_requests(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all submitted feature requests."""
    all_requests = list(reversed(_feature_requests))
    total = len(all_requests)
    page = all_requests[offset:offset + limit]
    return {
        "requests": page,
        "total": total,
        "timestamp": _now_iso(),
    }


@learning_router.get("/feedback/feature-requests/export", summary="Export feature requests as CSV")
async def export_feature_requests_csv():
    """Export all feature requests as CSV for transfer to development environments."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "title", "description", "category", "priority", "status", "created_at", "source"])

    for req in _feature_requests:
        writer.writerow([
            req.get("id", ""),
            req.get("title", ""),
            req.get("description", ""),
            req.get("category", ""),
            req.get("priority", ""),
            req.get("status", "open"),
            req.get("created_at", ""),
            req.get("source", "admin"),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=feature_requests_{_now_iso()[:10]}.csv"},
    )


@learning_router.get("/feedback/feature-requests/export-json", summary="Export feature requests as JSON")
async def export_feature_requests_json():
    """Export all feature requests as JSON for programmatic transfer."""
    return {
        "requests": list(_feature_requests),
        "total": len(_feature_requests),
        "exported_at": _now_iso(),
        "format": "json",
    }


# Knowledge Graph, Splunkbase, Guardrails, and Archival Memory endpoints are in
# admin_learning_ext_routes.py (learning_ext_router imported above).


# ---------------------------------------------------------------------------
# PUBLIC FEEDBACK ENDPOINTS — accessible to any user (no admin required)
# Mounted at /api/feedback/* (not /api/admin/*)
# ---------------------------------------------------------------------------

@learning_public_router.post("/submit", summary="Submit user feedback")
async def public_submit_feedback(body: FeatureRequestModel):
    """Submit feedback, feature request, or issue report. Available to all users."""
    request = {
        "id": str(uuid.uuid4()),
        "title": body.title,
        "description": body.description,
        "priority": body.priority,
        "category": body.category,
        "status": "open",
        "created_at": _now_iso(),
        "source": "user",
    }
    _feature_requests.append(request)
    _save_feature_requests(_feature_requests)
    logger.info("[FEEDBACK] User submitted: %s (category=%s)", body.title, body.category)
    return {"request": request, "timestamp": _now_iso()}


@learning_public_router.get("/list", summary="List feedback items")
async def public_list_feedback(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List feedback and feature requests. Available to all users (read-only)."""
    all_requests = list(reversed(_feature_requests))
    return {
        "requests": all_requests[offset:offset + limit],
        "total": len(all_requests),
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# GET /api/admin/learning/stats — learning pipeline statistics
# ---------------------------------------------------------------------------

@learning_router.get("/learning/stats", summary="Learning pipeline statistics")
async def get_learning_stats():
    """Return statistics for the self-learning pipeline.

    Aggregates QA pair counts, feedback loop stats, collection quality scores,
    and recent learning cycle outcomes.  This endpoint targets the LearningStat
    widget on the admin dashboard.
    """
    stats: dict = {"status": "ok", "timestamp": _now_iso()}

    # QA pair counts from vector store
    qa_counts: dict = {}
    try:
        import chromadb
        client = chromadb.HttpClient(host="localhost", port=8001)
        for col_name in ["self_learned_qa", "qa_pairs", "learned_facts"]:
            try:
                col = client.get_collection(col_name)
                qa_counts[col_name] = col.count()
            except Exception:  # broad catch — resilience at boundary
                qa_counts[col_name] = 0
    except Exception:  # broad catch — resilience at boundary
        pass
    stats["qa_pair_counts"] = qa_counts
    stats["total_qa_pairs"] = sum(qa_counts.values())

    # Recent learning history from resource manager
    try:
        from chat_app.resource_manager import get_learning_history, get_learning_trend
        stats["history"] = get_learning_history(limit=10)
        stats["trend"] = get_learning_trend(window=10)
    except Exception:  # broad catch — resilience at boundary
        stats["history"] = []
        stats["trend"] = {}

    # Collection quality scores (boost weights from self-adaptive RAG)
    try:
        from chat_app.self_adaptive_rag import get_adaptive_rag
        rag = get_adaptive_rag()
        weights = getattr(rag, "_collection_weights", {})
        stats["collection_quality"] = {
            name: round(float(score), 4) for name, score in weights.items()
        }
    except Exception:  # broad catch — resilience at boundary
        stats["collection_quality"] = {}

    # Feedback-driven learning stats
    try:
        from chat_app.self_learning import get_self_learning
        sl = get_self_learning()
        if hasattr(sl, "get_stats"):
            stats["self_learning"] = sl.get_stats()
    except Exception:  # broad catch — resilience at boundary
        stats["self_learning"] = {}

    # Most recent report file
    try:
        report_dir = Path("/app/data/learning_reports")
        if report_dir.is_dir():
            import json as _json
            reports = sorted(report_dir.glob("learning_*.json"), reverse=True)[:5]
            stats["recent_reports"] = []
            for rp in reports:
                try:
                    data = _json.loads(rp.read_text())
                    stats["recent_reports"].append({
                        "file": rp.name,
                        "timestamp": data.get("timestamp"),
                        "qa_pairs": data.get("qa_pairs_generated", 0),
                        "facts_learned": data.get("facts_learned", 0),
                        "duration_seconds": data.get("duration_seconds", 0),
                    })
                except Exception:  # broad catch — resilience at boundary
                    pass
    except Exception:  # broad catch — resilience at boundary
        stats["recent_reports"] = []

    return stats
