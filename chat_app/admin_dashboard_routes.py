"""Admin sub-router: Dashboard, Activity, Telemetry, Observability, and Approvals.

Handles these endpoint groups:
- GET  /api/admin/dashboard         — Aggregated dashboard data
- GET  /api/admin/activity          — User activity data
- GET  /api/admin/telemetry/report  — Search telemetry report
- GET  /api/admin/observability     — Aggregated observability data
- GET  /api/admin/approvals         — Pending approval requests
- POST /api/admin/approvals/{id}/approve
- POST /api/admin/approvals/{id}/deny

Mount with:
    from chat_app.admin_dashboard_routes import dashboard_router
    router.include_router(dashboard_router)
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from chat_app.auth_dependencies import require_admin
from chat_app.settings import get_settings
from chat_app.admin_shared import (
    ApprovalDecision,
    _append_audit,
    _collection_hit_counts,
    _csrf_check,
    _get_feature_flags,
    _intent_counts,
    _now_iso,
    _query_volume,
    _rate_limit,
    _recent_queries,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

dashboard_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-dashboard"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


def _get_skills_manager():
    """Import and return the SkillsManager singleton."""
    from chat_app.skills_manager import get_skills_manager
    return get_skills_manager()


def _get_engine():
    """Attempt to retrieve the database engine from the app_api module."""
    try:
        from chat_app import app_api
        return getattr(app_api, "engine", None)
    except Exception as _exc:  # broad catch — resilience against all failures
        return None


def _get_chroma_client():
    """Import and return the ChromaDB client."""
    try:
        from chat_app.admin_collections_routes import _get_chroma_client as _gcc
        return _gcc()
    except (ImportError, ModuleNotFoundError, RuntimeError, OSError) as exc:
        logger.debug("[DASHBOARD] ChromaDB not available: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@dashboard_router.get("/dashboard", summary="Aggregated dashboard data")
async def get_dashboard():
    """Return a single aggregated payload for the admin dashboard.

    Response structure matches the frontend DashboardData TypeScript interface.
    """
    result: Dict[str, Any] = {"timestamp": _now_iso(), "collections": [], "activity": []}

    # --- Health (top-level: {overall, services[]}) + extract metrics/learning ---
    health_metrics: Dict[str, Any] = {}
    try:
        from chat_app.health_monitor import get_comprehensive_health
        engine = _get_engine()
        health = await get_comprehensive_health(engine)
        result["health"] = {
            "overall": health.overall,
            "services": [
                {
                    "name": s.name,
                    "status": s.status,
                    "latency_ms": s.latency_ms,
                    "error": s.error,
                }
                for s in health.services
            ],
        }
        if health.metrics and isinstance(health.metrics, dict):
            health_metrics = health.metrics
        if health.learning:
            result["learning"] = health.learning
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        result["health"] = {"overall": "unknown", "services": []}
        logger.debug("[ADMIN] Dashboard health failed: %s", exc)

    # --- Resources ---
    try:
        from chat_app.resource_manager import get_resource_snapshot
        snap = get_resource_snapshot()
        result["resources"] = {
            "cpu_pct": snap.cpu_percent,
            "memory_pct": snap.memory_percent,
            "disk_pct": snap.disk_percent,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ADMIN] Dashboard resources failed: %s", exc)

    # --- Metrics ---
    total_queries_24h = sum(b.get("count", 0) for b in _query_volume)
    qpm = [b.get("count", 0) for b in _query_volume[-60:]]
    result["metrics"] = {
        "counters": health_metrics.get("counters"),
        "latency_p50": health_metrics.get("latency_p50"),
        "latency_p95": health_metrics.get("latency_p95"),
        "quality_p50": health_metrics.get("quality_p50"),
        "total_queries_24h": total_queries_24h,
        "queries_per_minute": qpm,
    }

    # --- Skills ---
    try:
        mgr = _get_skills_manager()
        all_skills = mgr.list_skills() if hasattr(mgr, "list_skills") else []
        active_count = sum(1 for s in all_skills if getattr(s, "enabled", True))
        result["skills"] = {"active": active_count, "total": len(all_skills)}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ADMIN] Failed to load skills manager stats: %s", exc)
        result["skills"] = {"active": 0, "total": 0}
    if result["skills"]["total"] == 0:
        try:
            from chat_app.skill_catalog import get_skill_catalog
            catalog = get_skill_catalog()
            all_s = catalog.list_all()
            result["skills"] = {"active": len(all_s), "total": len(all_s)}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[%s] %%s", "admin_dashboard_routes.py", _exc)

    # --- Feature flags ---
    flags = _get_feature_flags()
    result["features"] = {
        "total": len(flags),
        "enabled": sum(1 for v in flags.values() if v),
    }

    # --- Collections ---
    try:
        client = _get_chroma_client()
        if client is None:
            raise ImportError("ChromaDB not available")
        raw_cols = client.list_collections()
        cols = []
        for c in raw_cols:
            try:
                col_name = c.name if hasattr(c, "name") else str(c)
                col_obj = client.get_collection(col_name) if not hasattr(c, "count") else c
                cols.append({"name": col_name, "count": col_obj.count()})
            except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as exc:
                logger.debug("[ADMIN] Failed to get collection count: %s", exc)
                cols.append({"name": c.name if hasattr(c, "name") else str(c), "count": 0})
        existing_names = {c["name"] for c in cols}
        settings = get_settings()
        chroma_cfg = settings.chroma
        for name in [chroma_cfg.collection, chroma_cfg.secondary_collection,
                     "spl_commands_mxbai", "local_docs_mxbai", "self_learned_qa",
                     "org_repo_mxbai", "cribl_docs_mxbai", "negative_feedback_mxbai_embed_large"]:
            if name and name not in existing_names:
                cols.append({"name": name, "count": 0})
                existing_names.add(name)
        result["collections"] = cols
    except (ImportError, ModuleNotFoundError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as exc:
        logger.debug("[ADMIN] Dashboard collections failed: %s", exc)

    # --- Settings summary ---
    settings = get_settings()
    result["settings"] = {
        "active_profile": settings.app.active_profile,
        "model": settings.ollama.model,
        "embed_model": settings.ollama.embed_model,
        "ui_framework": settings.ui.framework,
        "learning_enabled": settings.learning.enabled,
        "cache_enabled": settings.cache.enabled,
    }

    # --- Version info ---
    from chat_app.admin_shared import _container_cmd
    result["version"] = {
        "current": settings.app.version,
        "runtime": _container_cmd(),
    }

    # --- Activity ---
    result["activity"] = [
        {"intent": name, "count": count}
        for name, count in sorted(
            _intent_counts.items(), key=lambda x: x[1], reverse=True
        )[:10]
    ]

    return result


# ---------------------------------------------------------------------------
# Activity Tracking
# ---------------------------------------------------------------------------

@dashboard_router.get("/activity", summary="User activity data")
async def get_activity(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return user activity data including query volume, intent distribution, and recent queries."""
    all_recent = list(reversed(_recent_queries))
    total = len(all_recent)
    page = all_recent[offset:offset + limit]
    return {
        "query_volume": _query_volume[-60:],
        "intent_distribution": dict(
            sorted(_intent_counts.items(), key=lambda x: x[1], reverse=True)
        ),
        "recent_queries": page,
        "total_tracked": total,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Telemetry Report
# ---------------------------------------------------------------------------

@dashboard_router.get("/telemetry/report", summary="Search telemetry report")
async def get_telemetry_report():
    """Aggregated search telemetry report: query volume, latency by intent,
    top collections, cache stats, quality distribution, and error rate.
    """
    # --- Query volume by hour ---
    hourly: Dict[str, int] = defaultdict(int)
    for bucket in _query_volume:
        hour_key = bucket.get("minute", "")[:13]
        if hour_key:
            hourly[hour_key] += bucket.get("count", 0)
    query_volume_by_hour = [
        {"hour": h, "count": c}
        for h, c in sorted(hourly.items())
    ]

    # --- Average latency by intent ---
    intent_latencies: Dict[str, List[int]] = defaultdict(list)
    error_count = 0
    quality_bins = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
    for q in _recent_queries:
        intent = q.get("intent") or "unknown"
        if q.get("duration_ms"):
            intent_latencies[intent].append(q["duration_ms"])
        conf = q.get("confidence", 0)
        if conf >= 0.8:
            quality_bins["excellent"] += 1
        elif conf >= 0.6:
            quality_bins["good"] += 1
        elif conf >= 0.3:
            quality_bins["fair"] += 1
        else:
            quality_bins["poor"] += 1
        if q.get("chunks_found", 0) == 0 and q.get("confidence", 0) < 0.1:
            error_count += 1

    avg_latency_by_intent = {
        intent: round(sum(lats) / len(lats), 1)
        for intent, lats in sorted(intent_latencies.items())
        if lats
    }

    # --- Top collections hit ---
    top_collections = sorted(
        [{"collection": k, "hits": v} for k, v in _collection_hit_counts.items()],
        key=lambda x: x["hits"],
        reverse=True,
    )[:20]

    # --- Cache stats ---
    cache_stats = {"hits": 0, "misses": 0, "hit_rate_pct": 0.0}
    try:
        from chat_app.response_generator import _cache_stats
        cache_stats = {
            "hits": _cache_stats.get("hits", 0),
            "misses": _cache_stats.get("misses", 0),
            "hit_rate_pct": round(
                _cache_stats["hits"] / max(_cache_stats["hits"] + _cache_stats["misses"], 1) * 100, 1
            ),
        }
    except (ImportError, AttributeError):
        pass

    # --- Common query patterns ---
    pattern_counts: Dict[str, int] = defaultdict(int)
    for q in _recent_queries:
        text = (q.get("query") or "").lower().strip()
        if text:
            words = text.split()[:5]
            pattern = " ".join(words)
            if len(pattern) >= 5:
                pattern_counts[pattern] += 1
    common_patterns = sorted(
        [{"pattern": p, "count": c} for p, c in pattern_counts.items() if c >= 2],
        key=lambda x: x["count"],
        reverse=True,
    )[:20]

    # --- Unique intents ---
    unique_intents = set()
    for q in _recent_queries:
        if q.get("intent"):
            unique_intents.add(q["intent"])

    total_queries = len(_recent_queries)

    return {
        "query_volume_by_hour": query_volume_by_hour,
        "avg_latency_by_intent": avg_latency_by_intent,
        "top_collections_hit": top_collections,
        "cache_stats": cache_stats,
        "quality_distribution": quality_bins,
        "common_query_patterns": common_patterns,
        "error_rate": {
            "total_queries": total_queries,
            "errors": error_count,
            "rate_pct": round(error_count / max(total_queries, 1) * 100, 1),
        },
        "recent_queries_summary": {
            "total_tracked": total_queries,
            "unique_intents": len(unique_intents),
        },
        "intent_distribution": dict(
            sorted(_intent_counts.items(), key=lambda x: x[1], reverse=True)
        ),
        "collection_usage": dict(
            sorted(_collection_hit_counts.items(), key=lambda x: x[1], reverse=True)
        ),
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

@dashboard_router.get("/observability", summary="Aggregated observability data")
async def get_observability():
    """Deep observability data: search metrics, performance, collection usage."""
    try:
        from chat_app.health_monitor import get_internal_metrics
        metrics = get_internal_metrics().get_all()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _m_err:
        logger.debug(f"[ADMIN] Failed to load internal metrics: {_m_err}")
        metrics = {}

    col_usage = dict(sorted(_collection_hit_counts.items(), key=lambda x: x[1], reverse=True))

    recent = list(_recent_queries)
    latencies = [q["duration_ms"] for q in recent if q.get("duration_ms", 0) > 0]
    confidences = [q["confidence"] for q in recent if q.get("confidence", 0) > 0]

    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0
    p95_latency = round(sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 5 else max(latencies, default=0), 1)
    avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0

    episode_stats = {}
    try:
        from chat_app.episodic_memory import get_episode_stats
        from chat_app.settings import get_settings as _gs
        engine = _gs().get_db_engine() if hasattr(_gs(), "get_db_engine") else None
        if engine:
            episode_stats = await get_episode_stats(engine) if engine else {}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _ep_err:
        logger.debug(f"[ADMIN] Failed to load episode stats: {_ep_err}")

    return {
        "search_performance": {
            "total_queries": len(recent),
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "avg_confidence": avg_confidence,
            "queries_per_minute": len(_query_volume),
        },
        "collection_usage": col_usage,
        "intent_distribution": dict(sorted(_intent_counts.items(), key=lambda x: x[1], reverse=True)[:20]),
        "recent_searches": [
            {
                "query": q.get("query", "")[:100],
                "intent": q.get("intent"),
                "collections": q.get("collections_searched", []),
                "chunks": q.get("chunks_found", 0),
                "confidence": q.get("confidence", 0),
                "duration_ms": q.get("duration_ms", 0),
                "profile": q.get("profile"),
                "timestamp": q.get("timestamp"),
            }
            for q in reversed(recent[-50:])
        ],
        "internal_metrics": metrics,
        "episodes": episode_stats,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Human-in-the-Loop Approvals
# ---------------------------------------------------------------------------

@dashboard_router.get("/approvals", summary="Get pending action approvals")
async def get_pending_approvals(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return all pending human-in-the-loop approval requests from the skills manager."""
    mgr = _get_skills_manager()
    pending = mgr.get_pending_approvals()
    total = len(pending)
    page = pending[offset:offset + limit]
    return {
        "pending": page,
        "total": total,
        "timestamp": _now_iso(),
    }


@dashboard_router.post("/approvals/{approval_id}/approve", summary="Approve a pending action")
async def approve_action(approval_id: str, body: Optional[ApprovalDecision] = None):
    """Approve a pending skill action and execute it."""
    mgr = _get_skills_manager()
    pending = mgr.get_pending_approvals()
    match = None
    for item in pending:
        if item["id"] == approval_id:
            match = item
            break

    if match is None:
        raise HTTPException(
            status_code=404,
            detail=f"Approval ID '{approval_id}' not found or already resolved.",
        )

    mgr.approve_action(approval_id)

    action_name = match["action"]
    params = match.get("params")
    result = await mgr.execute_action(action_name, params=params, user_approved=True)

    _append_audit(
        section="approvals",
        action="approve",
        changes={
            "approval_id": approval_id,
            "skill": match.get("skill"),
            "action": action_name,
            "reason": body.reason if body else None,
        },
    )

    return {
        "approval_id": approval_id,
        "approved": True,
        "execution": {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "latency_ms": result.latency_ms,
        },
        "timestamp": _now_iso(),
    }


@dashboard_router.post("/approvals/{approval_id}/deny", summary="Deny a pending action")
async def deny_action(approval_id: str, body: Optional[ApprovalDecision] = None):
    """Deny a pending skill action, removing it from the queue without execution."""
    mgr = _get_skills_manager()
    pending = mgr.get_pending_approvals()
    match = None
    for item in pending:
        if item["id"] == approval_id:
            match = item
            break

    if match is None:
        raise HTTPException(
            status_code=404,
            detail=f"Approval ID '{approval_id}' not found or already resolved.",
        )

    mgr.approve_action(approval_id)

    _append_audit(
        section="approvals",
        action="deny",
        changes={
            "approval_id": approval_id,
            "skill": match.get("skill"),
            "action": match.get("action"),
            "reason": body.reason if body else None,
        },
    )

    return {
        "approval_id": approval_id,
        "denied": True,
        "reason": body.reason if body else None,
        "timestamp": _now_iso(),
    }
