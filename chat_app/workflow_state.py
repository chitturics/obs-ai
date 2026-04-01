"""
Workflow state persistence using PostgreSQL.

Saves and loads workflow execution snapshots so that multi-step workflows
can be resumed after interruption or reviewed later.
"""
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WorkflowSnapshot:
    """A point-in-time snapshot of a workflow execution."""
    workflow_id: str
    workflow_name: str
    status: str = "running"  # running, completed, failed, paused, waiting_input, waiting_approval
    current_step: int = 0
    total_steps: int = 0
    steps_completed: List[Dict[str, Any]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    user_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    error: str = ""
    paused_at: float = 0.0
    pause_reason: str = ""
    resume_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def save_workflow_state(engine, snapshot: WorkflowSnapshot) -> bool:
    """Save a workflow snapshot to PostgreSQL."""
    if engine is None:
        logger.debug("[WORKFLOW_STATE] No database engine, skipping save")
        return False

    snapshot.updated_at = time.time()
    if snapshot.created_at == 0:
        snapshot.created_at = snapshot.updated_at

    try:
        from sqlalchemy import text
        async with engine.begin() as conn:
            # Ensure table exists
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS workflow_states (
                    workflow_id VARCHAR(128) PRIMARY KEY,
                    workflow_name VARCHAR(256) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'running',
                    current_step INTEGER DEFAULT 0,
                    total_steps INTEGER DEFAULT 0,
                    steps_completed JSONB DEFAULT '[]',
                    context JSONB DEFAULT '{}',
                    user_id VARCHAR(128) DEFAULT '',
                    error TEXT DEFAULT '',
                    created_at DOUBLE PRECISION,
                    updated_at DOUBLE PRECISION
                )
            """))

            # Upsert
            await conn.execute(text("""
                INSERT INTO workflow_states
                    (workflow_id, workflow_name, status, current_step, total_steps,
                     steps_completed, context, user_id, error, created_at, updated_at)
                VALUES
                    (:wid, :name, :status, :step, :total,
                     :steps::jsonb, :ctx::jsonb, :uid, :err, :cat, :uat)
                ON CONFLICT (workflow_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    current_step = EXCLUDED.current_step,
                    steps_completed = EXCLUDED.steps_completed,
                    context = EXCLUDED.context,
                    error = EXCLUDED.error,
                    updated_at = EXCLUDED.updated_at
            """), {
                "wid": snapshot.workflow_id,
                "name": snapshot.workflow_name,
                "status": snapshot.status,
                "step": snapshot.current_step,
                "total": snapshot.total_steps,
                "steps": json.dumps(snapshot.steps_completed),
                "ctx": json.dumps(snapshot.context),
                "uid": snapshot.user_id,
                "err": snapshot.error,
                "cat": snapshot.created_at,
                "uat": snapshot.updated_at,
            })

        logger.debug("[WORKFLOW_STATE] Saved workflow %s (step %d/%d)",
                     snapshot.workflow_id, snapshot.current_step, snapshot.total_steps)
        return True
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("[WORKFLOW_STATE] Save failed: %s", exc)
        return False


async def load_workflow_state(engine, workflow_id: str) -> Optional[WorkflowSnapshot]:
    """Load a workflow snapshot from PostgreSQL."""
    if engine is None:
        return None

    try:
        from sqlalchemy import text
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT * FROM workflow_states WHERE workflow_id = :wid"),
                {"wid": workflow_id},
            )
            row = result.mappings().first()
            if not row:
                return None

            return WorkflowSnapshot(
                workflow_id=row["workflow_id"],
                workflow_name=row["workflow_name"],
                status=row["status"],
                current_step=row["current_step"],
                total_steps=row["total_steps"],
                steps_completed=row["steps_completed"] if isinstance(row["steps_completed"], list) else json.loads(row["steps_completed"] or "[]"),
                context=row["context"] if isinstance(row["context"], dict) else json.loads(row["context"] or "{}"),
                user_id=row["user_id"],
                error=row.get("error", ""),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("[WORKFLOW_STATE] Load failed: %s", exc)
        return None


async def list_workflow_states(
    engine,
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List workflow snapshots with optional filters."""
    if engine is None:
        return []

    try:
        from sqlalchemy import text
        query = "SELECT workflow_id, workflow_name, status, current_step, total_steps, user_id, created_at, updated_at FROM workflow_states WHERE 1=1"
        params: Dict[str, Any] = {}

        if user_id:
            query += " AND user_id = :uid"
            params["uid"] = user_id
        if status:
            query += " AND status = :status"
            params["status"] = status

        query += " ORDER BY updated_at DESC LIMIT :limit"
        params["limit"] = limit

        async with engine.begin() as conn:
            result = await conn.execute(text(query), params)
            return [dict(row) for row in result.mappings().all()]
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[WORKFLOW_STATE] List failed: %s", exc)
        return []


async def delete_workflow_state(engine, workflow_id: str) -> bool:
    """Delete a workflow snapshot."""
    if engine is None:
        return False

    try:
        from sqlalchemy import text
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM workflow_states WHERE workflow_id = :wid"),
                {"wid": workflow_id},
            )
        return True
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[WORKFLOW_STATE] Delete failed: %s", exc)
        return False
