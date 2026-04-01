"""
Human-in-the-Loop — Interactive approval gates, feedback, and oversight.

Implements the "5 senses" of the AI agent:
1. SIGHT  — Observes user queries, context, and system state
2. SOUND  — Listens to user feedback (thumbs up/down, corrections, preferences)
3. TOUCH  — Feels the quality of responses (self-evaluation, confidence scoring)
4. SMELL  — Detects anomalies (knowledge gaps, anti-patterns, drift)
5. TASTE  — Judges outcomes (tool effectiveness, learning quality, user satisfaction)

Human-in-the-middle ensures:
- Critical actions require explicit approval
- User feedback shapes future behavior
- Transparency in agent reasoning
- Escalation paths for uncertain decisions
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ActionSeverity(str, Enum):
    """How impactful an action is — determines approval requirements."""
    LOW = "low"           # Read-only, no side effects
    MEDIUM = "medium"     # Modifies local state
    HIGH = "high"         # Modifies external systems
    CRITICAL = "critical" # Destructive or irreversible


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    AUTO_APPROVED = "auto_approved"


@dataclass
class ApprovalRequest:
    """A request for human approval before executing an action."""
    request_id: str
    action_name: str
    description: str
    severity: ActionSeverity
    parameters: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None
    expires_at: Optional[float] = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at and time.time() > self.expires_at:
            return True
        return False


@dataclass
class UserFeedback:
    """Feedback from the user on an agent response/action."""
    feedback_id: str
    query: str
    response_summary: str
    rating: int  # 1-5
    correction: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentInsight:
    """An insight from the agent's "senses" — anomaly detection, quality drift, etc."""
    insight_type: str  # anomaly, drift, gap, improvement, warning
    message: str
    severity: ActionSeverity = ActionSeverity.LOW
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False


class HumanLoopManager:
    """Manages human-in-the-loop interactions for the agent."""

    def __init__(self, auto_approve_low: bool = True, approval_timeout_seconds: int = 300):
        self._pending_approvals: Dict[str, ApprovalRequest] = {}
        self._approval_history: List[ApprovalRequest] = []
        self._feedback_history: List[UserFeedback] = []
        self._insights: List[AgentInsight] = []
        self._auto_approve_low = auto_approve_low
        self._approval_timeout = approval_timeout_seconds
        self._approval_callbacks: Dict[str, Callable] = {}
        # Counters
        self._total_approvals = 0
        self._total_denials = 0
        self._total_auto_approvals = 0

    def request_approval(
        self,
        action_name: str,
        description: str,
        severity: ActionSeverity,
        parameters: Dict[str, Any] = None,
        reason: str = "",
        callback: Callable = None,
    ) -> ApprovalRequest:
        """
        Request human approval for an action.

        LOW severity actions are auto-approved if configured.
        MEDIUM+ require explicit approval.
        """
        request_id = f"apr_{int(time.time() * 1000)}_{action_name}"

        # Auto-approve low severity actions
        if severity == ActionSeverity.LOW and self._auto_approve_low:
            self._total_auto_approvals += 1
            request = ApprovalRequest(
                request_id=request_id,
                action_name=action_name,
                description=description,
                severity=severity,
                parameters=parameters or {},
                reason=reason,
                status=ApprovalStatus.AUTO_APPROVED,
                resolved_at=time.time(),
            )
            self._approval_history.append(request)
            return request

        request = ApprovalRequest(
            request_id=request_id,
            action_name=action_name,
            description=description,
            severity=severity,
            parameters=parameters or {},
            reason=reason,
            expires_at=time.time() + self._approval_timeout,
        )
        self._pending_approvals[request_id] = request
        if callback:
            self._approval_callbacks[request_id] = callback

        logger.info(f"[HUMAN-LOOP] Approval requested: {action_name} (severity={severity.value})")
        return request

    def approve(self, request_id: str, approved_by: str = "user") -> bool:
        """Approve a pending request."""
        request = self._pending_approvals.pop(request_id, None)
        if not request:
            return False

        if request.is_expired:
            request.status = ApprovalStatus.EXPIRED
            self._approval_history.append(request)
            return False

        request.status = ApprovalStatus.APPROVED
        request.resolved_at = time.time()
        request.resolved_by = approved_by
        self._approval_history.append(request)
        self._total_approvals += 1

        # Execute callback if registered
        callback = self._approval_callbacks.pop(request_id, None)
        if callback:
            try:
                callback(request)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.error(f"[HUMAN-LOOP] Approval callback failed: {exc}")

        logger.info(f"[HUMAN-LOOP] Approved: {request.action_name} by {approved_by}")
        return True

    def deny(self, request_id: str, denied_by: str = "user") -> bool:
        """Deny a pending request."""
        request = self._pending_approvals.pop(request_id, None)
        if not request:
            return False

        request.status = ApprovalStatus.DENIED
        request.resolved_at = time.time()
        request.resolved_by = denied_by
        self._approval_history.append(request)
        self._total_denials += 1
        self._approval_callbacks.pop(request_id, None)

        logger.info(f"[HUMAN-LOOP] Denied: {request.action_name} by {denied_by}")
        return True

    def record_feedback(
        self,
        query: str,
        response_summary: str,
        rating: int,
        correction: str = None,
        tags: List[str] = None,
    ) -> UserFeedback:
        """Record user feedback on a response."""
        feedback = UserFeedback(
            feedback_id=f"fb_{int(time.time() * 1000)}",
            query=query,
            response_summary=response_summary[:500],
            rating=min(max(rating, 1), 5),
            correction=correction,
            tags=tags or [],
        )
        self._feedback_history.append(feedback)
        if len(self._feedback_history) > 1000:
            self._feedback_history = self._feedback_history[-1000:]

        logger.info(f"[HUMAN-LOOP] Feedback recorded: rating={rating}/5")
        return feedback

    def add_insight(
        self,
        insight_type: str,
        message: str,
        severity: ActionSeverity = ActionSeverity.LOW,
        data: Dict[str, Any] = None,
    ) -> AgentInsight:
        """Add an agent insight (anomaly, drift, gap detection)."""
        insight = AgentInsight(
            insight_type=insight_type,
            message=message,
            severity=severity,
            data=data or {},
        )
        self._insights.append(insight)
        if len(self._insights) > 500:
            self._insights = self._insights[-500:]
        return insight

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """Get all pending approval requests."""
        # Clean up expired
        expired = [
            rid for rid, req in self._pending_approvals.items()
            if req.is_expired
        ]
        for rid in expired:
            req = self._pending_approvals.pop(rid)
            req.status = ApprovalStatus.EXPIRED
            self._approval_history.append(req)

        return [
            {
                "request_id": req.request_id,
                "action": req.action_name,
                "description": req.description,
                "severity": req.severity.value,
                "parameters": req.parameters,
                "reason": req.reason,
                "created_at": req.created_at,
                "expires_at": req.expires_at,
            }
            for req in self._pending_approvals.values()
        ]

    def get_recent_feedback(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent user feedback."""
        return [
            {
                "feedback_id": fb.feedback_id,
                "query": fb.query[:100],
                "rating": fb.rating,
                "has_correction": fb.correction is not None,
                "tags": fb.tags,
                "timestamp": fb.timestamp,
            }
            for fb in self._feedback_history[-limit:]
        ]

    def get_insights(self, unacknowledged_only: bool = False) -> List[Dict[str, Any]]:
        """Get agent insights."""
        insights = self._insights
        if unacknowledged_only:
            insights = [i for i in insights if not i.acknowledged]
        return [
            {
                "type": i.insight_type,
                "message": i.message,
                "severity": i.severity.value,
                "data": i.data,
                "timestamp": i.timestamp,
                "acknowledged": i.acknowledged,
            }
            for i in insights[-50:]
        ]

    def acknowledge_insight(self, index: int) -> bool:
        """Acknowledge an insight."""
        if 0 <= index < len(self._insights):
            self._insights[index].acknowledged = True
            return True
        return False

    def get_satisfaction_score(self) -> float:
        """Calculate overall user satisfaction from feedback."""
        if not self._feedback_history:
            return 0.0
        recent = self._feedback_history[-50:]
        return sum(fb.rating for fb in recent) / (len(recent) * 5)

    def get_metrics(self) -> Dict[str, Any]:
        """Get human-in-the-loop metrics."""
        return {
            "pending_approvals": len(self._pending_approvals),
            "total_approvals": self._total_approvals,
            "total_denials": self._total_denials,
            "total_auto_approvals": self._total_auto_approvals,
            "total_feedback": len(self._feedback_history),
            "satisfaction_score": round(self.get_satisfaction_score(), 3),
            "unacknowledged_insights": sum(1 for i in self._insights if not i.acknowledged),
            "avg_feedback_rating": round(
                sum(fb.rating for fb in self._feedback_history[-50:]) / max(len(self._feedback_history[-50:]), 1), 2
            ),
        }


# Singleton
_manager: Optional[HumanLoopManager] = None


def get_human_loop_manager() -> HumanLoopManager:
    """Get or create the singleton HumanLoopManager."""
    global _manager
    if _manager is None:
        _manager = HumanLoopManager()
    return _manager
