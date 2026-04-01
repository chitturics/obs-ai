"""
Workflow Persistence — Database state management mixin for WorkflowOrchestrator.

Extracted from workflow_orchestrator.py for size management.
WorkflowOrchestrator inherits from WorkflowPersistenceMixin.

Provides:
- _save_state() — persist workflow progress to DB (best-effort)
- get_persisted_workflows() — list workflow history from DB
- recover_interrupted() — mark interrupted workflows after restart
- pause_workflow() — pause at next task boundary
- resume_workflow() — resume from saved state
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class WorkflowPersistenceMixin:
    """
    Mixin providing database state persistence for WorkflowOrchestrator.

    Requires the host class to have:
        _active_workflows: Dict[str, WorkflowPlan]
        _save_state() — used by pause/resume (provided by this mixin)
        execute_workflow() — called by resume_workflow
    Also uses module-level _get_db_engine() from workflow_orchestrator.
    """

    async def _save_state(
        self, workflow_id: str, plan, status: str, error: str = ""
    ):
        """Persist workflow state to database (best-effort)."""
        # Lazy imports to avoid circular dependencies at module load time
        from chat_app.workflow_models import TaskStatus
        from chat_app.workflow_state import WorkflowSnapshot, save_workflow_state
        from chat_app.workflow_orchestrator import _get_db_engine
        try:
            engine = _get_db_engine()
            if engine is None:
                return
            steps_completed = []
            for t in plan.tasks:
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    steps_completed.append({
                        "id": t.id,
                        "description": t.description,
                        "status": t.status.value,
                        "agent": t.agent_name,
                        "duration_ms": round(t.duration_ms, 2),
                        "error": t.error or "",
                    })
            snapshot = WorkflowSnapshot(
                workflow_id=workflow_id,
                workflow_name=plan.description,
                status=status,
                current_step=plan.completed_tasks,
                total_steps=plan.total_tasks,
                steps_completed=steps_completed,
                error=error,
            )
            await save_workflow_state(engine, snapshot)

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[ORCHESTRATOR] State persistence failed (non-fatal): %s", exc)

    async def get_persisted_workflows(
        self, user_id: str = None, status: str = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get workflow history from database."""
        from chat_app.workflow_state import list_workflow_states
        from chat_app.workflow_orchestrator import _get_db_engine
        try:
            engine = _get_db_engine()
            if engine is None:
                return []
            result = await list_workflow_states(engine, user_id=user_id, status=status, limit=limit)
            return result
        except Exception as _exc:  # broad catch — resilience against all failures
            return []

    async def recover_interrupted(self) -> List[str]:
        """
        Find workflows that were 'running' when the app restarted.
        Mark them as 'interrupted' so they can be reviewed.
        Returns list of interrupted workflow IDs.
        """
        from chat_app.workflow_state import list_workflow_states, load_workflow_state, save_workflow_state
        from chat_app.workflow_orchestrator import _get_db_engine
        try:
            engine = _get_db_engine()
            if engine is None:
                return []
            running = await list_workflow_states(engine, status="running")
            interrupted_ids = []
            for wf in running:
                wf_id = wf.get("workflow_id", "")
                snapshot = await load_workflow_state(engine, wf_id)
                if snapshot:
                    snapshot.status = "interrupted"
                    snapshot.error = "Application restarted during execution"
                    await save_workflow_state(engine, snapshot)
                    interrupted_ids.append(wf_id)
                    logger.info("[ORCHESTRATOR] Marked workflow %s as interrupted", wf_id)

            return interrupted_ids
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[ORCHESTRATOR] Recovery check failed: %s", exc)
            return []

    async def pause_workflow(self, workflow_id: str, reason: str = "user_request") -> bool:
        """Pause an active workflow at the next task boundary."""
        from chat_app.workflow_models import TaskStatus
        plan = self._active_workflows.get(workflow_id)
        if not plan:
            logger.warning("[ORCHESTRATOR] Cannot pause %s: not active", workflow_id)
            return False

        for task in plan.tasks:
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.PAUSED

        await self._save_state(workflow_id, plan, "paused")
        logger.info("[ORCHESTRATOR] Paused workflow %s: %s", workflow_id, reason)
        return True

    async def resume_workflow(self, workflow_id: str, user_input: str = ""):
        """Resume a paused workflow from its saved state."""
        from chat_app.workflow_models import TaskStatus
        from chat_app.workflow_state import load_workflow_state, save_workflow_state
        from chat_app.workflow_orchestrator import _get_db_engine
        # Check if still in active workflows
        plan = self._active_workflows.get(workflow_id)
        if plan:
            # Resume paused tasks
            for task in plan.tasks:
                if task.status in (TaskStatus.PAUSED, TaskStatus.WAITING_INPUT, TaskStatus.WAITING_APPROVAL):
                    task.status = TaskStatus.PENDING
            await self._save_state(workflow_id, plan, "running")
            logger.info("[ORCHESTRATOR] Resumed active workflow %s", workflow_id)
            return await self.execute_workflow(plan, user_input or "resume")

        # Try loading from DB
        try:
            engine = _get_db_engine()
            if engine is None:
                return None
            snapshot = await load_workflow_state(engine, workflow_id)

            if snapshot and snapshot.status in ("paused", "waiting_input", "waiting_approval"):
                # Reconstruct plan from snapshot context
                logger.info("[ORCHESTRATOR] Resuming persisted workflow %s", workflow_id)
                # Mark as running again
                snapshot.status = "running"
                snapshot.paused_at = 0.0
                snapshot.pause_reason = ""
                engine = _get_db_engine()
                if engine:
                    await save_workflow_state(engine, snapshot)

                return None  # Can't fully reconstruct — return None to indicate partial resume
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCHESTRATOR] Resume failed for %s: %s", workflow_id, exc)
        return None
