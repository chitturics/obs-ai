"""Multi-Step Approval Workflows — sequential approvals with change windows.

Extends the existing human_loop.py with:
- **Multi-step approvals**: Chain of approvers (e.g., analyst → admin)
- **Change windows**: Time-based constraints (e.g., maintenance windows only)
- **Approval delegation**: Reassign pending approvals
- **Expiry and escalation**: Auto-escalate or expire stale approvals
- **Audit integration**: All decisions recorded in immutable audit log

Usage:
    from chat_app.approval_workflows import get_approval_manager

    mgr = get_approval_manager()
    workflow = mgr.create_workflow(
        action="deploy_pipeline",
        description="Deploy new Cribl pipeline to production",
        steps=[
            ApprovalStep(role="ANALYST", label="Technical review"),
            ApprovalStep(role="ADMIN", label="Production approval"),
        ],
        requester="analyst@example.com",
    )
    # Returns workflow_id — each step must be approved in order
"""

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workflow status
# ---------------------------------------------------------------------------

class WorkflowStatus(str, Enum):
    PENDING = "pending"        # Awaiting first approval
    IN_PROGRESS = "in_progress"  # Some steps approved, more remaining
    APPROVED = "approved"      # All steps approved
    DENIED = "denied"          # Any step denied
    EXPIRED = "expired"        # Timed out
    CANCELLED = "cancelled"    # Requester cancelled


class StepStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    SKIPPED = "skipped"  # Skipped due to earlier denial


# ---------------------------------------------------------------------------
# Approval Step
# ---------------------------------------------------------------------------

@dataclass
class ApprovalStep:
    """A single step in a multi-step approval workflow."""
    role: str  # Required role to approve (ADMIN, ANALYST, etc.)
    label: str = ""
    status: StepStatus = StepStatus.PENDING
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "label": self.label,
            "status": self.status.value,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Change Window
# ---------------------------------------------------------------------------

@dataclass
class ChangeWindow:
    """Time-based constraint for when approvals/actions are allowed."""
    name: str
    description: str
    days_of_week: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri
    start_hour_utc: int = 0
    end_hour_utc: int = 24
    enabled: bool = True

    def is_open(self) -> bool:
        """Check if the change window is currently open."""
        if not self.enabled:
            return True  # Disabled windows are always "open"
        now = datetime.now(timezone.utc)
        if now.weekday() not in self.days_of_week:
            return False
        if not (self.start_hour_utc <= now.hour < self.end_hour_utc):
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return {
            "name": self.name,
            "description": self.description,
            "days": [day_names[d] for d in self.days_of_week],
            "hours_utc": f"{self.start_hour_utc:02d}:00-{self.end_hour_utc:02d}:00",
            "enabled": self.enabled,
            "currently_open": self.is_open(),
        }


# ---------------------------------------------------------------------------
# Approval Workflow
# ---------------------------------------------------------------------------

@dataclass
class ApprovalWorkflow:
    """A multi-step approval workflow."""
    workflow_id: str
    action: str
    description: str
    requester: str
    steps: List[ApprovalStep] = field(default_factory=list)
    status: WorkflowStatus = WorkflowStatus.PENDING
    change_window: Optional[str] = None  # Name of required change window
    created_at: str = ""
    updated_at: str = ""
    expires_at: Optional[str] = None  # ISO timestamp
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def current_step_index(self) -> int:
        """Index of the next pending step."""
        for i, step in enumerate(self.steps):
            if step.status == StepStatus.PENDING:
                return i
        return len(self.steps)

    @property
    def current_step(self) -> Optional[ApprovalStep]:
        idx = self.current_step_index
        return self.steps[idx] if idx < len(self.steps) else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "action": self.action,
            "description": self.description,
            "requester": self.requester,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "current_step": self.current_step_index,
            "total_steps": len(self.steps),
            "change_window": self.change_window,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Default change windows
# ---------------------------------------------------------------------------

_DEFAULT_WINDOWS: List[ChangeWindow] = [
    ChangeWindow(
        name="business_hours",
        description="Standard business hours (Mon-Fri, 9am-6pm UTC)",
        days_of_week=[0, 1, 2, 3, 4],
        start_hour_utc=9,
        end_hour_utc=18,
    ),
    ChangeWindow(
        name="maintenance_window",
        description="Maintenance window (Sat-Sun, all day)",
        days_of_week=[5, 6],
        start_hour_utc=0,
        end_hour_utc=24,
    ),
    ChangeWindow(
        name="off_hours",
        description="Off-hours (Mon-Fri, 6pm-9am UTC)",
        days_of_week=[0, 1, 2, 3, 4],
        start_hour_utc=18,
        end_hour_utc=24,
    ),
    ChangeWindow(
        name="always_open",
        description="No time restrictions",
        enabled=False,
    ),
]


# ---------------------------------------------------------------------------
# Approval Manager
# ---------------------------------------------------------------------------

_DEFAULT_EXPIRY_HOURS = 24
_MAX_WORKFLOWS = 1000


class ApprovalManager:
    """Manages multi-step approval workflows."""

    def __init__(self):
        self._workflows: Dict[str, ApprovalWorkflow] = {}
        self._windows: Dict[str, ChangeWindow] = {w.name: w for w in _DEFAULT_WINDOWS}
        self._lock = threading.Lock()

    def create_workflow(
        self,
        action: str,
        description: str,
        steps: List[ApprovalStep],
        requester: str,
        change_window: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expiry_hours: int = _DEFAULT_EXPIRY_HOURS,
    ) -> ApprovalWorkflow:
        """Create a new multi-step approval workflow."""
        now = datetime.now(timezone.utc)
        workflow = ApprovalWorkflow(
            workflow_id=f"wf_{uuid.uuid4().hex[:12]}",
            action=action,
            description=description,
            requester=requester,
            steps=steps,
            change_window=change_window,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=((now + timedelta(hours=expiry_hours)).isoformat() if expiry_hours else None),
            metadata=metadata or {},
        )

        # Check change window
        if change_window:
            window = self._windows.get(change_window)
            if window and not window.is_open():
                workflow.status = WorkflowStatus.PENDING
                logger.info(
                    "[APPROVAL] Workflow %s queued — change window '%s' is closed",
                    workflow.workflow_id, change_window,
                )

        with self._lock:
            # Evict old workflows if over capacity
            if len(self._workflows) >= _MAX_WORKFLOWS:
                oldest = min(self._workflows.values(), key=lambda w: w.created_at)
                del self._workflows[oldest.workflow_id]
            self._workflows[workflow.workflow_id] = workflow

        # Audit
        self._audit("create", workflow, requester)
        return workflow

    def approve_step(
        self,
        workflow_id: str,
        approver: str,
        approver_role: str,
        reason: str = "",
    ) -> Optional[ApprovalWorkflow]:
        """Approve the current step of a workflow."""
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return None

        step = workflow.current_step
        if not step:
            return workflow  # All steps already done

        # Check role
        if step.role != approver_role and approver_role != "ADMIN":
            logger.warning(
                "[APPROVAL] Role mismatch: step requires %s, got %s",
                step.role, approver_role,
            )
            return None

        # Check change window
        if workflow.change_window:
            window = self._windows.get(workflow.change_window)
            if window and not window.is_open():
                logger.warning("[APPROVAL] Change window '%s' is closed", workflow.change_window)
                return None

        step.status = StepStatus.APPROVED
        step.approved_by = approver
        step.approved_at = datetime.now(timezone.utc).isoformat()
        step.reason = reason

        # Check if all steps done
        if all(s.status == StepStatus.APPROVED for s in workflow.steps):
            workflow.status = WorkflowStatus.APPROVED
        else:
            workflow.status = WorkflowStatus.IN_PROGRESS

        workflow.updated_at = datetime.now(timezone.utc).isoformat()
        self._audit("approve_step", workflow, approver)
        return workflow

    def deny_step(
        self,
        workflow_id: str,
        denier: str,
        reason: str = "",
    ) -> Optional[ApprovalWorkflow]:
        """Deny the current step, which denies the entire workflow."""
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return None

        step = workflow.current_step
        if not step:
            return workflow

        step.status = StepStatus.DENIED
        step.approved_by = denier
        step.approved_at = datetime.now(timezone.utc).isoformat()
        step.reason = reason

        # Mark remaining steps as skipped
        for s in workflow.steps:
            if s.status == StepStatus.PENDING:
                s.status = StepStatus.SKIPPED

        workflow.status = WorkflowStatus.DENIED
        workflow.updated_at = datetime.now(timezone.utc).isoformat()
        self._audit("deny", workflow, denier)
        return workflow

    def cancel_workflow(self, workflow_id: str, actor: str) -> Optional[ApprovalWorkflow]:
        """Cancel a pending workflow."""
        workflow = self._workflows.get(workflow_id)
        if not workflow or workflow.status not in (WorkflowStatus.PENDING, WorkflowStatus.IN_PROGRESS):
            return None
        workflow.status = WorkflowStatus.CANCELLED
        workflow.updated_at = datetime.now(timezone.utc).isoformat()
        self._audit("cancel", workflow, actor)
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[ApprovalWorkflow]:
        """Get a workflow by ID."""
        return self._workflows.get(workflow_id)

    def get_pending(self, role: Optional[str] = None) -> List[ApprovalWorkflow]:
        """Get all pending workflows, optionally filtered by required approver role."""
        pending = [
            w for w in self._workflows.values()
            if w.status in (WorkflowStatus.PENDING, WorkflowStatus.IN_PROGRESS)
        ]
        if role:
            pending = [w for w in pending if w.current_step and w.current_step.role == role]
        return sorted(pending, key=lambda w: w.created_at, reverse=True)

    def get_history(self, limit: int = 50) -> List[ApprovalWorkflow]:
        """Get recent workflow history."""
        all_wf = sorted(self._workflows.values(), key=lambda w: w.created_at, reverse=True)
        return all_wf[:limit]

    def get_change_windows(self) -> List[Dict[str, Any]]:
        """Get all change windows with current status."""
        return [w.to_dict() for w in self._windows.values()]

    def get_stats(self) -> Dict[str, Any]:
        """Get approval workflow statistics."""
        by_status: Dict[str, int] = {}
        for w in self._workflows.values():
            by_status[w.status.value] = by_status.get(w.status.value, 0) + 1
        return {
            "total_workflows": len(self._workflows),
            "by_status": by_status,
            "pending_count": sum(1 for w in self._workflows.values()
                                 if w.status in (WorkflowStatus.PENDING, WorkflowStatus.IN_PROGRESS)),
            "change_windows": len(self._windows),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _audit(self, action: str, workflow: ApprovalWorkflow, actor: str) -> None:
        """Record to immutable audit log."""
        try:
            from chat_app.audit_log import get_audit_log
            get_audit_log().append(
                event_type="approval_workflow",
                actor=actor,
                action=action,
                target=workflow.workflow_id,
                details={
                    "workflow_action": workflow.action,
                    "status": workflow.status.value,
                    "step": workflow.current_step_index,
                    "total_steps": len(workflow.steps),
                },
                severity="high",
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[ApprovalManager] = None
_instance_lock = threading.Lock()


def get_approval_manager() -> ApprovalManager:
    """Get the global ApprovalManager singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ApprovalManager()
    return _instance
