"""Admin sub-router: Workflow Template (Visual Designer) endpoints.

Extracted from admin_skills_routes.py to keep file sizes manageable.
All routes are included on skills_router via re-import in admin_skills_routes.py.

Endpoints:
- GET  /api/admin/workflows/templates          — List workflow templates
- POST /api/admin/workflows/templates          — Save new workflow template
- PUT  /api/admin/workflows/templates/{id}     — Update workflow template
- DELETE /api/admin/workflows/templates/{id}  — Delete workflow template
- POST /api/admin/workflows/execute            — Execute canvas workflow
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from chat_app.auth_dependencies import require_admin
from chat_app.admin_shared import (
    _append_audit,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router — same prefix/tags/dependencies as skills_router so routes merge
# ---------------------------------------------------------------------------

workflow_templates_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-skills"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)

# ---------------------------------------------------------------------------
# In-memory template store (backed by JSON file for persistence)
# ---------------------------------------------------------------------------

_workflow_templates: Dict[str, Dict] = {}
_TEMPLATE_FILE = Path("/app/data/workflow_templates.json")


def _load_workflow_templates():
    global _workflow_templates
    try:
        if _TEMPLATE_FILE.exists():
            _workflow_templates = json.loads(_TEMPLATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as _exc:
        logger.debug("[%s] %%s", "admin_skills_workflow_routes.py", _exc)


def _save_workflow_templates():
    try:
        _TEMPLATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TEMPLATE_FILE.write_text(json.dumps(_workflow_templates, indent=2, default=str), encoding="utf-8")
    except (OSError, ValueError) as _exc:
        logger.debug("[%s] %%s", "admin_skills_workflow_routes.py", _exc)


_load_workflow_templates()


# ---------------------------------------------------------------------------
# Workflow Template CRUD
# ---------------------------------------------------------------------------

@workflow_templates_router.get("/workflows/templates", summary="List workflow templates")
async def list_workflow_templates():
    """List all saved workflow templates."""
    templates = list(_workflow_templates.values())
    return {"status": "ok", "templates": templates, "count": len(templates)}


@workflow_templates_router.post("/workflows/templates", summary="Save new workflow template")
async def create_workflow_template(body: dict):
    """Create a new workflow template."""
    import uuid
    template_id = str(uuid.uuid4())[:8]
    template = {
        "id": template_id,
        "name": body.get("name", "Untitled"),
        "description": body.get("description", ""),
        "nodes": body.get("nodes", []),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _workflow_templates[template_id] = template
    _save_workflow_templates()
    _append_audit(section="workflows", action="create_template", changes={"id": template_id, "name": template["name"]})
    return {"status": "ok", "template": template}


@workflow_templates_router.put("/workflows/templates/{template_id}", summary="Update workflow template")
async def update_workflow_template(template_id: str, body: dict):
    """Update an existing workflow template."""
    if template_id not in _workflow_templates:
        raise HTTPException(404, f"Template {template_id} not found")
    template = _workflow_templates[template_id]
    template["name"] = body.get("name", template["name"])
    template["description"] = body.get("description", template["description"])
    template["nodes"] = body.get("nodes", template["nodes"])
    template["updated_at"] = _now_iso()
    _save_workflow_templates()
    _append_audit(section="workflows", action="update_template", changes={"id": template_id})
    return {"status": "ok", "template": template}


@workflow_templates_router.delete("/workflows/templates/{template_id}", summary="Delete workflow template")
async def delete_workflow_template(template_id: str):
    """Delete a workflow template."""
    if template_id not in _workflow_templates:
        raise HTTPException(404, f"Template {template_id} not found")
    del _workflow_templates[template_id]
    _save_workflow_templates()
    _append_audit(section="workflows", action="delete_template", changes={"id": template_id})
    return {"status": "ok", "deleted": template_id}


@workflow_templates_router.post("/workflows/execute", summary="Execute a workflow from canvas")
async def execute_canvas_workflow(body: dict):
    """Execute a workflow defined by canvas nodes."""
    nodes = body.get("nodes", [])
    if not nodes:
        raise HTTPException(400, "No nodes provided")

    try:
        from chat_app.workflow_orchestrator import (
            WorkflowTask, WorkflowPlan, get_workflow_orchestrator
        )
        orch = get_workflow_orchestrator()

        tasks = []
        for i, node in enumerate(nodes):
            task = WorkflowTask(
                id=i,
                description=node.get("label", f"Step {i+1}"),
                intent=node.get("config", {}).get("intent", "general"),
                agent_name=node.get("config", {}).get("name", ""),
                depends_on=[i-1] if i > 0 else [],
            )
            tasks.append(task)

        plan = WorkflowPlan(
            description=body.get("name", "Canvas Workflow"),
            tasks=tasks,
        )

        result = await orch.execute_workflow(plan, user_input=body.get("name", "workflow"))
        return {"status": "ok", "result": result.to_dict(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))
