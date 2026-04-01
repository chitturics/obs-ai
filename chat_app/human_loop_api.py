"""
Human-in-the-Loop API — REST endpoints for approval gates, feedback, and insights.

Provides:
1. Approval management (list pending, approve, deny)
2. User feedback submission and retrieval
3. Agent insights (anomalies, drift, quality signals)
4. Satisfaction metrics and trends
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hitl", tags=["human-in-the-loop"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    """Submit user feedback."""
    query: str = Field(..., min_length=1)
    response_summary: str = Field(..., min_length=1)
    rating: int = Field(..., ge=1, le=5)
    correction: Optional[str] = None
    tags: Optional[List[str]] = None


class ApprovalDecision(BaseModel):
    """Decision body for approve/deny."""
    reason: Optional[str] = None
    approved_by: str = "admin"


class InsightAck(BaseModel):
    """Acknowledge an insight."""
    index: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_hlm():
    from chat_app.human_loop import get_human_loop_manager
    return get_human_loop_manager()


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

@router.get("/approvals", summary="List pending approval requests")
async def list_approvals():
    """Return all pending human-in-the-loop approval requests."""
    hlm = _get_hlm()
    pending = hlm.get_pending_approvals()
    metrics = hlm.get_metrics()
    return {
        "pending": pending,
        "total_pending": len(pending),
        "total_approvals": metrics["total_approvals"],
        "total_denials": metrics["total_denials"],
        "total_auto_approvals": metrics["total_auto_approvals"],
    }


@router.post("/approvals/{request_id}/approve", summary="Approve a pending request")
async def approve_request(request_id: str, body: Optional[ApprovalDecision] = None):
    """Approve a pending action request."""
    hlm = _get_hlm()
    approved_by = body.approved_by if body else "admin"
    success = hlm.approve(request_id, approved_by=approved_by)
    if not success:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found or expired.")
    return {"request_id": request_id, "approved": True, "approved_by": approved_by}


@router.post("/approvals/{request_id}/deny", summary="Deny a pending request")
async def deny_request(request_id: str, body: Optional[ApprovalDecision] = None):
    """Deny a pending action request."""
    hlm = _get_hlm()
    denied_by = body.approved_by if body else "admin"
    success = hlm.deny(request_id, denied_by=denied_by)
    if not success:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found or already resolved.")
    return {"request_id": request_id, "denied": True, "denied_by": denied_by}


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

@router.post("/feedback", summary="Submit user feedback")
async def submit_feedback(body: FeedbackRequest):
    """Record user feedback on a response."""
    hlm = _get_hlm()
    fb = hlm.record_feedback(
        query=body.query,
        response_summary=body.response_summary,
        rating=body.rating,
        correction=body.correction,
        tags=body.tags,
    )
    return {
        "feedback_id": fb.feedback_id,
        "rating": fb.rating,
        "has_correction": fb.correction is not None,
    }


@router.get("/feedback", summary="Get recent feedback")
async def get_feedback(limit: int = Query(default=20, ge=1, le=200)):
    """Return recent user feedback."""
    hlm = _get_hlm()
    feedback = hlm.get_recent_feedback(limit=limit)
    metrics = hlm.get_metrics()
    return {
        "feedback": feedback,
        "total": metrics["total_feedback"],
        "satisfaction_score": metrics["satisfaction_score"],
        "avg_rating": metrics["avg_feedback_rating"],
    }


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

@router.get("/insights", summary="Get agent insights")
async def get_insights(unacknowledged_only: bool = Query(default=False)):
    """Return agent insights (anomalies, drift, gaps)."""
    hlm = _get_hlm()
    insights = hlm.get_insights(unacknowledged_only=unacknowledged_only)
    return {
        "insights": insights,
        "total": len(insights),
        "unacknowledged": hlm.get_metrics()["unacknowledged_insights"],
    }


@router.post("/insights/acknowledge", summary="Acknowledge an insight")
async def acknowledge_insight(body: InsightAck):
    """Acknowledge an agent insight by index."""
    hlm = _get_hlm()
    success = hlm.acknowledge_insight(body.index)
    if not success:
        raise HTTPException(status_code=404, detail=f"Insight at index {body.index} not found.")
    return {"acknowledged": True, "index": body.index}


# ---------------------------------------------------------------------------
# Metrics & Dashboard
# ---------------------------------------------------------------------------

@router.get("/metrics", summary="Get human-in-the-loop metrics")
async def get_hitl_metrics():
    """Return comprehensive human-in-the-loop metrics."""
    hlm = _get_hlm()
    return hlm.get_metrics()
