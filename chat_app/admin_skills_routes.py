"""Admin sub-router: Skills, agents, orchestration, and workflow endpoints.

Handles these endpoint groups:
- GET  /api/admin/skill-catalog*           — Skill catalog (7 endpoints)
- GET  /api/admin/agent-catalog*           — Agent catalog (6 endpoints)
- GET  /api/admin/agentic/*               — Agentic execution layer (11 endpoints)
- POST /api/admin/agentic/dispatch        — Dispatch query to agent
- POST /api/admin/agentic/execute-skill   — Execute a single skill
- GET  /api/admin/orchestration/*         — Orchestration strategies (6 endpoints)
- GET  /api/admin/action-engine/*         — Action engine (2 endpoints)
- GET  /api/admin/director-graph/*        — Director graph (2 endpoints)
- GET  /api/admin/workflows/*             — Workflow management (8 endpoints)
- POST /api/admin/workflows/execute       — Execute canvas workflow

Mount with:
    from chat_app.admin_skills_routes import skills_router
    app.include_router(skills_router)
"""

import logging

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.admin_shared import (
    _csrf_check,
    _now_iso,
    _rate_limit,
    _track_audit_user,
)

# Orchestration, action engine, director graph, and workflow management extracted
from chat_app.admin_skills_orchestration_routes import (  # noqa: F401
    skills_orch_router,
)

# Workflow template CRUD and canvas execution extracted to keep this file under 600 lines
from chat_app.admin_skills_workflow_routes import (  # noqa: F401
    workflow_templates_router,
)

logger = logging.getLogger(__name__)

skills_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-skills"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class AgentDispatchRequest(BaseModel):
    query: str = Field(..., description="User query to dispatch")
    intent: Optional[str] = Field(default=None, description="Override intent (auto-detected if omitted)")
    agent_name: Optional[str] = Field(default=None, description="Force specific agent by name")
    max_skills: int = Field(default=3, ge=1, le=10)


class SkillExecuteRequest(BaseModel):
    skill_name: str = Field(..., description="Skill name or handler_key to execute")
    params: Dict[str, Any] = Field(default_factory=dict, description="Parameters for the skill")


# ---------------------------------------------------------------------------
# Skill Catalog
# ---------------------------------------------------------------------------

@skills_router.get("/skill-catalog")
async def get_skill_catalog_endpoint():
    """Get the full skill catalog -- all human actions mapped to system capabilities."""
    try:
        from chat_app.skill_catalog import get_skill_catalog
        catalog = get_skill_catalog()
        return {
            "status": "ok",
            "summary": catalog.summary(),
            "skills": catalog.list_all(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/skill-catalog/actions")
async def list_skill_actions():
    """List all available human action verbs (eat, think, run, etc.)."""
    try:
        from chat_app.skill_catalog import get_skill_catalog
        catalog = get_skill_catalog()
        return {"actions": catalog.list_actions(), "count": catalog.count}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/skill-catalog/action/{action}")
async def get_skill_by_action(action: str):
    """Get a skill by its human action verb (e.g., 'think', 'eat', 'run')."""
    try:
        from chat_app.skill_catalog import get_skill_catalog
        catalog = get_skill_catalog()
        skill = catalog.get_by_action(action)
        if not skill:
            raise HTTPException(404, f"No skill mapped to action '{action}'")
        return skill.to_dict()
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/skill-catalog/family/{family}")
async def get_skills_by_family(family: str):
    """Get all skills in a family (cognitive, io, communication, etc.)."""
    try:
        from chat_app.skill_catalog import get_skill_catalog, SkillFamily
        catalog = get_skill_catalog()
        try:
            fam = SkillFamily(family)
        except ValueError:
            families = [f.value for f in SkillFamily]
            raise HTTPException(400, f"Invalid family '{family}'. Valid: {families}")
        skills = catalog.get_family(fam)
        return {"family": family, "count": len(skills), "skills": [s.to_dict() for s in skills]}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/skill-catalog/search")
async def search_skills(q: str = Query(..., min_length=1)):
    """Search skills by name, action, description, or tags."""
    try:
        from chat_app.skill_catalog import get_skill_catalog
        catalog = get_skill_catalog()
        results = catalog.search(q)
        return {"query": q, "count": len(results), "skills": [s.to_dict() for s in results]}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/skill-catalog/intent/{intent}")
async def get_skills_for_intent_catalog(intent: str):
    """Get all skills that handle a given intent."""
    try:
        from chat_app.skill_catalog import get_skill_catalog
        catalog = get_skill_catalog()
        skills = catalog.get_for_intent(intent)
        return {"intent": intent, "count": len(skills), "skills": [s.to_dict() for s in skills]}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/skill-catalog/approval-required")
async def get_skills_requiring_approval():
    """Get skills that require human-in-the-loop approval."""
    try:
        from chat_app.skill_catalog import get_skill_catalog
        catalog = get_skill_catalog()
        skills = catalog.get_requiring_approval()
        return {"count": len(skills), "skills": [s.to_dict() for s in skills]}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


# ---------------------------------------------------------------------------
# Agent Catalog
# ---------------------------------------------------------------------------

@skills_router.get("/agent-catalog")
async def get_agent_catalog_endpoint():
    """Get the full agent catalog -- all human roles mapped to system agents."""
    try:
        from chat_app.agent_catalog import get_agent_catalog
        catalog = get_agent_catalog()
        return {
            "status": "ok",
            "summary": catalog.summary(),
            "agents": catalog.list_all(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agent-catalog/roles")
async def list_agent_roles():
    """List all available human role names (coder, ops guy, tester, etc.)."""
    try:
        from chat_app.agent_catalog import get_agent_catalog
        catalog = get_agent_catalog()
        return {"roles": catalog.list_roles(), "count": catalog.count}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agent-catalog/role/{role}")
async def get_agent_by_role(role: str):
    """Get an agent by its human role (e.g., 'coder', 'ops guy', 'tester')."""
    try:
        from chat_app.agent_catalog import get_agent_catalog
        catalog = get_agent_catalog()
        agent = catalog.get_by_role(role)
        if not agent:
            raise HTTPException(404, f"No agent mapped to role '{role}'")
        return agent.to_dict()
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agent-catalog/department/{department}")
async def get_agents_by_department(department: str):
    """Get all agents in a department (engineering, operations, data, etc.)."""
    try:
        from chat_app.agent_catalog import get_agent_catalog, Department
        catalog = get_agent_catalog()
        try:
            dept = Department(department)
        except ValueError:
            depts = [d.value for d in Department]
            raise HTTPException(400, f"Invalid department '{department}'. Valid: {depts}")
        agents = catalog.get_department(dept)
        return {"department": department, "count": len(agents), "agents": [a.to_dict() for a in agents]}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agent-catalog/search")
async def search_agents(q: str = Query(..., min_length=1)):
    """Search agents by name, role, description, or tags."""
    try:
        from chat_app.agent_catalog import get_agent_catalog
        catalog = get_agent_catalog()
        results = catalog.search(q)
        return {"query": q, "count": len(results), "agents": [a.to_dict() for a in results]}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agent-catalog/intent/{intent}")
async def get_agents_for_intent(intent: str):
    """Get all agents that handle a given intent, sorted by expertise."""
    try:
        from chat_app.agent_catalog import get_agent_catalog
        catalog = get_agent_catalog()
        agents = catalog.get_for_intent(intent)
        return {"intent": intent, "count": len(agents), "agents": [a.to_dict() for a in agents]}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agent-catalog/best/{intent}")
async def get_best_agent_for_intent(intent: str):
    """Get the best (highest expertise) agent for a given intent."""
    try:
        from chat_app.agent_catalog import get_agent_catalog
        catalog = get_agent_catalog()
        agent = catalog.get_best_agent(intent)
        if not agent:
            raise HTTPException(404, f"No agent handles intent '{intent}'")
        return agent.to_dict()
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


# ---------------------------------------------------------------------------
# Agentic Execution Layer
# ---------------------------------------------------------------------------

@skills_router.get("/agentic/status")
async def get_agentic_status():
    """Get the status of all agentic components."""
    try:
        from chat_app.skill_executor import get_skill_executor
        from chat_app.agent_dispatcher import get_agent_dispatcher
        from chat_app.workflow_orchestrator import get_workflow_orchestrator

        executor = get_skill_executor()
        dispatcher = get_agent_dispatcher()
        orchestrator = get_workflow_orchestrator()

        return {
            "status": "ok",
            "skill_executor": executor.get_metrics(),
            "agent_dispatcher": dispatcher.get_summary(),
            "workflow_orchestrator": orchestrator.get_summary(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agentic/available-skills")
async def get_available_skills():
    """Get all skills that can actually be executed (handler resolves)."""
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        available = executor.get_available_skills()
        return {"status": "ok", "count": len(available), "skills": available}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agentic/skills-for-intent/{intent}")
async def get_skills_for_intent(intent: str):
    """Get executable skills for a specific intent."""
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        skills = executor.get_skills_for_intent(intent)
        return {"status": "ok", "intent": intent, "count": len(skills), "skills": skills}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agentic/execution-log")
async def get_execution_log(limit: int = Query(50, ge=1, le=200)):
    """Get recent skill execution log."""
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        log = executor.get_execution_log(limit)
        return {"status": "ok", "count": len(log), "log": log}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agentic/dispatch-log")
async def get_dispatch_log(limit: int = Query(50, ge=1, le=200)):
    """Get recent agent dispatch log."""
    try:
        from chat_app.agent_dispatcher import get_agent_dispatcher
        dispatcher = get_agent_dispatcher()
        log = dispatcher.get_dispatch_log(limit)
        return {"status": "ok", "count": len(log), "log": log}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agentic/agent-metrics")
async def get_agent_perf_metrics():
    """Get per-agent performance metrics."""
    try:
        from chat_app.agent_dispatcher import get_agent_dispatcher
        dispatcher = get_agent_dispatcher()
        metrics = dispatcher.get_agent_metrics()
        return {"status": "ok", "agents": metrics}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agentic/workflows")
async def get_workflow_status():
    """Get active and recent workflows."""
    try:
        from chat_app.workflow_orchestrator import get_workflow_orchestrator
        orchestrator = get_workflow_orchestrator()
        return {
            "status": "ok",
            "active": orchestrator.get_active_workflows(),
            "completed": orchestrator.get_completed_workflows(),
            "summary": orchestrator.get_summary(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agentic/resolve-handler/{handler_key}")
async def resolve_handler(handler_key: str):
    """Resolve a handler_key to its execution backend."""
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        source, resolved = executor.resolve_handler(handler_key)
        if source is None:
            raise HTTPException(404, f"Handler not found: {handler_key}")
        return {"status": "ok", "handler_key": handler_key, "source": source, "resolved": resolved}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.get("/agentic/select-agent/{intent}")
async def select_agent_for_intent(intent: str, query: str = Query("", description="User query for better agent selection")):
    """Select the best agent for a given intent."""
    try:
        from chat_app.agent_dispatcher import get_agent_dispatcher
        dispatcher = get_agent_dispatcher()
        agent = dispatcher.select_agent(intent, query)
        if not agent:
            raise HTTPException(404, f"No agent found for intent '{intent}'")
        return {"status": "ok", "agent": agent.to_dict()}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, str(exc))


@skills_router.post("/agentic/dispatch", summary="Dispatch a query to the best agent")
async def dispatch_agent(body: AgentDispatchRequest):
    """Execute agent dispatch -- selects best agent, runs skills, returns enriched context."""
    try:
        from chat_app.agent_dispatcher import get_agent_dispatcher
        dispatcher = get_agent_dispatcher()

        intent = body.intent
        if not intent:
            try:
                from chat_app.intent_classifier import classify_intent
                plan = classify_intent(body.query)
                intent = plan.intent
            except Exception as _exc:  # broad catch — resilience against all failures
                intent = "general_qa"

        result = await dispatcher.dispatch(
            user_input=body.query,
            intent=intent,
            max_skills=body.max_skills,
        )
        return {
            "status": "ok",
            "agent_name": result.agent_name,
            "agent_role": result.agent_role,
            "department": result.department,
            "skills_executed": result.skills_executed,
            "enriched_context": result.enriched_context[:2000] if result.enriched_context else "",
            "system_prompt_fragment": result.system_prompt_fragment[:500] if result.system_prompt_fragment else "",
            "duration_ms": result.duration_ms,
            "success": result.success,
            "error": result.error,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[AGENTIC] Dispatch failed: {exc}")
        raise HTTPException(500, str(exc))


@skills_router.post("/agentic/execute-skill", summary="Execute a single skill")
async def execute_skill_endpoint(body: SkillExecuteRequest):
    """Execute a skill by name and return its output."""
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        result = await executor.execute(
            skill_name=body.skill_name,
            params=body.params,
        )
        return {
            "status": "ok",
            "skill_name": body.skill_name,
            "output": result.output[:5000] if result.output else "",
            "success": result.success,
            "error": result.error or "",
            "approval_required": result.approval_required if hasattr(result, 'approval_required') else False,
            "duration_ms": result.duration_ms if hasattr(result, 'duration_ms') else 0,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[AGENTIC] Skill execution failed: {exc}")
        return {
            "status": "error",
            "skill_name": body.skill_name,
            "output": "",
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "duration_ms": 0,
            "timestamp": _now_iso(),
        }

# Orchestration strategies, action engine, director graph, and workflow management
# endpoints are in admin_skills_orchestration_routes.py (skills_orch_router imported above).
# Workflow template CRUD is in admin_skills_workflow_routes.py (workflow_templates_router imported above).


# ---------------------------------------------------------------------------
# GET /api/admin/skills/catalog — full skill catalog with execution metadata
# ---------------------------------------------------------------------------

@skills_router.get("/skills/catalog", summary="Full skill catalog with execution metadata")
async def get_skills_catalog():
    """Return the full skill catalog including handler keys, min_role, and families.

    This endpoint surfaces /skills/catalog (plural) for frontend consumers that
    expect the canonical REST path.  The data is identical to /skill-catalog but
    includes additional execution-layer metadata: whether each skill has a
    registered handler and its current execution source.
    """
    try:
        from chat_app.skill_catalog import get_skill_catalog
        catalog = get_skill_catalog()
        skills_raw = catalog.list_all()

        # Augment with execution metadata when the executor is available.
        handler_map: dict = {}
        try:
            from chat_app.skill_executor import get_skill_executor
            executor = get_skill_executor()
            available = executor.get_available_skills()
            handler_map = {s.get("handler_key", ""): s.get("source", "unknown") for s in available}
        except Exception:  # broad catch — resilience at boundary
            pass

        enriched = []
        for skill in skills_raw:
            handler_key = skill.get("handler_key", "")
            skill["execution_source"] = handler_map.get(handler_key, "unregistered")
            skill["has_handler"] = handler_key in handler_map
            enriched.append(skill)

        summary = catalog.summary()
        return {
            "status": "ok",
            "total": len(enriched),
            "summary": summary,
            "skills": enriched,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))
