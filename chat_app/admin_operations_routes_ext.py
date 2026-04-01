"""Admin sub-router extension: LLM costs, OTel, prompt templates, analytics, personas, etc.

Extracted from admin_operations_routes.py to keep file sizes manageable.
Routes are registered on the same operations_router via import.

Endpoint groups in this file:
- GET  /api/admin/costs/*              -- Cost tracking (3)
- GET  /api/admin/llm/*                -- LLM providers (2)
- GET  /api/admin/otel/*               -- OTel tracing (4)
- GET  /api/admin/prompt-templates/*   -- Prompt template management (5)
- GET  /api/admin/analytics/*          -- Analytics (4)
- GET  /api/admin/user-profiles/*      -- User learning profiles (2)
- POST /api/admin/ingestion/*          -- Ingestion management (1)
- GET  /api/admin/mcp/server/*         -- MCP server (2)
- GET  /api/admin/a2a/*                -- A2A protocol (2)
- GET  /api/admin/tools/unified-registry/* -- Unified tool registry (4)
- GET  /api/admin/personas/*           -- User personas (4)
"""

import logging
from typing import Optional

from fastapi import HTTPException, Query

from chat_app.admin_operations_routes import (
    operations_router,
    MCPToolCallRequest,
    A2ATaskRequest,
    PersonaCreateRequest,
    PersonaUpdateRequest,
    PromptTemplateCreate,
    PromptTemplateUpdate,
)
from chat_app.admin_shared import (
    _append_audit,
    _current_audit_user,
    _now_iso,
    _safe_error,
)
from chat_app.settings import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM Cost Tracking
# ---------------------------------------------------------------------------

@operations_router.get("/costs", summary="LLM cost summary")
async def get_costs(hours: int = Query(24, ge=1, le=720)):
    """Return cost summary for the specified period."""
    try:
        from chat_app.cost_tracker import get_cost_summary
        return get_cost_summary(hours=hours)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[ADMIN] Cost summary failed: %s", exc)
        return {"total_usd": 0, "total_calls": 0}


@operations_router.get("/costs/daily", summary="Daily cost trend")
async def get_costs_daily(days: int = Query(30, ge=1, le=365)):
    """Return daily cost totals for the last N days."""
    try:
        from chat_app.cost_tracker import get_cost_tracker
        return get_cost_tracker().get_daily_trend(days=days)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[ADMIN] Daily cost trend failed: %s", exc)
        return {"daily_totals": {}}


@operations_router.get("/costs/by-user", summary="Per-user cost breakdown")
async def get_costs_by_user(top_n: int = Query(20, ge=1, le=100)):
    """Return per-user cost breakdown."""
    try:
        from chat_app.cost_tracker import get_cost_tracker
        return get_cost_tracker().get_by_user(top_n=top_n)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[ADMIN] Per-user costs failed: %s", exc)
        return {"users": []}


# ---------------------------------------------------------------------------
# Multi-LLM Gateway
# ---------------------------------------------------------------------------

@operations_router.get("/llm/providers", summary="List LLM providers")
async def get_llm_providers():
    """Return all configured LLM providers with availability status."""
    try:
        from chat_app.llm_gateway import get_llm_gateway
        gw = get_llm_gateway()
        return {"providers": gw.get_providers(), "fallback_chain": gw.get_fallback_chain(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[ADMIN] LLM providers list failed: %s", exc)
        return {"providers": [], "fallback_chain": []}


@operations_router.get("/llm/recommend", summary="Get model recommendation for a task")
async def get_llm_recommendation(task: str = Query("general", description="Task type")):
    """Recommend the best model/provider for a given task type."""
    try:
        from chat_app.llm_gateway import get_llm_gateway
        gw = get_llm_gateway()
        rec = gw.recommend_model(task_type=task)
        return {
            "task_type": task, "recommendation": rec,
            "available_tasks": ["general", "code", "complex", "creative", "spl", "summarization"],
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[ADMIN] LLM recommendation failed: %s", exc)
        return {"task_type": task, "recommendation": None, "timestamp": _now_iso()}


# ---------------------------------------------------------------------------
# OTel Tracing
# ---------------------------------------------------------------------------

@operations_router.get("/otel/traces", summary="List recent OTel traces")
async def get_otel_traces(limit: int = Query(50, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    """Return recent distributed traces from the in-memory span exporter."""
    try:
        from chat_app.otel_tracing import get_memory_exporter, is_otel_available
        if not is_otel_available():
            return {"traces": [], "total": 0, "otel_available": False, "message": "OpenTelemetry SDK not installed or tracing disabled"}
        exporter = get_memory_exporter()
        if exporter is None:
            return {"traces": [], "total": 0, "otel_available": True, "message": "No in-memory exporter configured"}
        all_traces = exporter.get_traces(limit=500)
        total = len(all_traces)
        page = all_traces[offset:offset + limit]
        return {"traces": page, "total": total, "otel_available": True}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[OTEL] Trace list failed: %s", exc)
        return {"traces": [], "total": 0}


@operations_router.get("/otel/traces/{trace_id}", summary="Get all spans for a specific trace")
async def get_otel_trace_detail(trace_id: str):
    """Return the full span tree for a single distributed trace."""
    try:
        from chat_app.otel_tracing import get_memory_exporter, is_otel_available
        if not is_otel_available():
            raise HTTPException(503, "OpenTelemetry not available")
        exporter = get_memory_exporter()
        if exporter is None:
            raise HTTPException(503, "No in-memory exporter configured")
        trace_data = exporter.get_trace_by_id(trace_id)
        if not trace_data:
            raise HTTPException(404, f"Trace {trace_id} not found")
        return trace_data
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[OTEL] Trace detail failed: %s", exc)
        raise HTTPException(500, str(exc))


@operations_router.get("/otel/spans", summary="List raw spans (most recent first)")
async def get_otel_spans(limit: int = Query(100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    """Return raw spans from the in-memory exporter."""
    try:
        from chat_app.otel_tracing import get_memory_exporter, is_otel_available
        if not is_otel_available():
            return {"spans": [], "total": 0, "otel_available": False}
        exporter = get_memory_exporter()
        if exporter is None:
            return {"spans": [], "total": 0, "otel_available": True}
        all_spans = exporter.get_spans(limit=500)
        total = len(all_spans)
        page = all_spans[offset:offset + limit]
        return {"spans": page, "total": total, "otel_available": True}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[OTEL] Span list failed: %s", exc)
        return {"spans": [], "total": 0}


@operations_router.get("/otel/status", summary="OpenTelemetry tracing status")
async def get_otel_status():
    """Return the current OTel configuration and status."""
    try:
        from chat_app.otel_tracing import is_otel_available, HAS_OTEL, get_memory_exporter
        exporter = get_memory_exporter()
        span_count = len(exporter._spans) if exporter and hasattr(exporter, '_spans') else 0
        settings = get_settings()
        return {
            "sdk_installed": HAS_OTEL,
            "tracing_active": is_otel_available(),
            "enabled_in_settings": settings.otel.enabled,
            "endpoint": settings.otel.endpoint or "(none -- in-memory only)",
            "service_name": settings.otel.service_name,
            "console_export": settings.otel.console_export,
            "max_spans": settings.otel.max_spans,
            "buffered_spans": span_count,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[OTEL] Status check failed: %s", exc)
        return {"tracing_active": False, "sdk_installed": False}


# ---------------------------------------------------------------------------
# Prompt Template Management
# ---------------------------------------------------------------------------

@operations_router.get("/prompt-templates", summary="List all prompt templates")
async def list_prompt_templates(limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    """Return all prompt templates with metadata and metrics."""
    try:
        from chat_app.prompt_manager import get_prompt_manager
        mgr = get_prompt_manager()
        templates = mgr.list_all()
        total = len(templates)
        page = templates[offset:offset + limit]
        return {"templates": page, "total": total, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "list prompt templates"))


@operations_router.get("/prompt-templates/{template_id}", summary="Get prompt template by ID")
async def get_prompt_template(template_id: str):
    """Return a single prompt template with full details and metrics."""
    try:
        from chat_app.prompt_manager import get_prompt_manager
        mgr = get_prompt_manager()
        t = mgr.get(template_id)
        if not t:
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
        return {
            "id": t.id, "name": t.name, "category": t.category,
            "template": t.template, "version": t.version,
            "variables": t.variables, "status": t.status,
            "ab_group": t.ab_group, "created_by": t.created_by,
            "created_at": t.created_at, "metrics": vars(t.metrics),
        }
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "get prompt template"))


@operations_router.post("/prompt-templates", summary="Create a new prompt template")
async def create_prompt_template(body: PromptTemplateCreate):
    """Create a new versioned prompt template."""
    try:
        from chat_app.prompt_manager import get_prompt_manager
        mgr = get_prompt_manager()
        author = _current_audit_user.get() or "admin"
        pt = mgr.create(name=body.name, category=body.category,
                        template=body.template, variables=body.variables, author=author)
        _append_audit("prompt_template_create", {"template_id": pt.id, "name": pt.name})
        return {"id": pt.id, "name": pt.name, "version": pt.version, "status": "created"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "create prompt template"))


@operations_router.put("/prompt-templates/{template_id}", summary="Update prompt template")
async def update_prompt_template(template_id: str, body: PromptTemplateUpdate):
    """Update a prompt template (bumps version, archives old)."""
    try:
        from chat_app.prompt_manager import get_prompt_manager
        mgr = get_prompt_manager()
        author = _current_audit_user.get() or "admin"
        updated = mgr.update(template_id, body.template, author=author)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
        _append_audit("prompt_template_update", {"template_id": template_id, "new_version": updated.version})
        return {"id": updated.id, "name": updated.name, "version": updated.version, "status": "updated"}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "update prompt template"))


@operations_router.get("/prompt-templates/{template_id}/versions", summary="Version history for a prompt template")
async def get_prompt_template_versions(template_id: str, limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    """Return version history for a prompt template."""
    try:
        from chat_app.prompt_manager import get_prompt_manager
        mgr = get_prompt_manager()
        if not mgr.get(template_id):
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
        versions = mgr.get_versions(template_id)
        total = len(versions)
        page = versions[offset:offset + limit]
        return {"template_id": template_id, "versions": page, "total": total}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "get prompt template versions"))


# ---------------------------------------------------------------------------
# Analytics & Business Intelligence
# ---------------------------------------------------------------------------

@operations_router.get("/analytics/taxonomy", summary="Question taxonomy breakdown")
async def get_analytics_taxonomy():
    try:
        from chat_app.analytics import get_analytics_engine
        engine = get_analytics_engine()
        return {**engine.get_question_taxonomy(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "analytics taxonomy"))


@operations_router.get("/analytics/gaps", summary="Knowledge gap detection")
async def get_analytics_gaps(top_n: int = Query(20, ge=1, le=100)):
    try:
        from chat_app.analytics import get_analytics_engine
        engine = get_analytics_engine()
        gaps = engine.get_knowledge_gaps(top_n=top_n)
        return {"gaps": gaps, "total": len(gaps), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "analytics gaps"))


@operations_router.get("/analytics/adoption", summary="Adoption metrics")
async def get_analytics_adoption():
    try:
        from chat_app.analytics import get_analytics_engine
        engine = get_analytics_engine()
        return {**engine.get_adoption_metrics(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "analytics adoption"))


@operations_router.get("/analytics/roi", summary="ROI estimate")
async def get_analytics_roi():
    try:
        from chat_app.analytics import get_analytics_engine
        engine = get_analytics_engine()
        return {**engine.get_roi_estimate(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "analytics roi"))


# ---------------------------------------------------------------------------
# User Learning Profiles
# ---------------------------------------------------------------------------

@operations_router.get("/user-profiles", summary="List all user learning profiles")
async def list_user_profiles(limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    try:
        from chat_app.user_profiles import get_profile_manager
        mgr = get_profile_manager()
        profiles = mgr.list_profiles()
        total = len(profiles)
        page = profiles[offset:offset + limit]
        return {"profiles": page, "total": total, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[USER-PROFILES] List failed: %s", exc)
        return {"profiles": [], "total": 0, "timestamp": _now_iso()}


@operations_router.get("/user-profiles/{user_id}", summary="Get a specific user learning profile")
async def get_user_profile(user_id: str):
    try:
        from chat_app.user_profiles import get_profile_manager
        mgr = get_profile_manager()
        profile = mgr.get_profile(user_id)
        return {"profile": profile.to_dict(), "personalization_prompt": profile.get_personalization_prompt(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[USER-PROFILES] Get %s failed: %s", user_id, exc)
        raise HTTPException(status_code=500, detail=_safe_error(exc, f"get user profile {user_id}"))


# ---------------------------------------------------------------------------
# Ingestion Management
# ---------------------------------------------------------------------------

@operations_router.get("/ingestion/stats", summary="Incremental ingestion statistics")
async def ingestion_incremental_stats():
    try:
        from chat_app.document_ingestor import get_incremental_stats
        stats = get_incremental_stats()
        return {"stats": stats, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[INGESTION] Stats failed: %s", exc)
        return {"stats": {}, "error": str(type(exc).__name__), "timestamp": _now_iso()}


# ---------------------------------------------------------------------------
# MCP Server Mode
# ---------------------------------------------------------------------------

@operations_router.get("/mcp/server/capabilities", summary="MCP server capability manifest")
async def mcp_server_capabilities():
    try:
        from chat_app.mcp_server_mode import get_mcp_server_capabilities
        return get_mcp_server_capabilities()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[MCP-SERVER] Capabilities failed: %s", exc)
        raise HTTPException(status_code=500, detail=_safe_error(exc, "mcp server capabilities"))


@operations_router.post("/mcp/server/tool-call", summary="Test MCP tool call")
async def mcp_server_tool_call(body: MCPToolCallRequest):
    try:
        from chat_app.mcp_server_mode import handle_mcp_tool_call
        result = await handle_mcp_tool_call(body.tool_name, body.arguments)
        return {"tool": body.tool_name, "result": result, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[MCP-SERVER] Tool call %s failed: %s", body.tool_name, exc)
        raise HTTPException(status_code=500, detail=_safe_error(exc, f"mcp tool call {body.tool_name}"))


# ---------------------------------------------------------------------------
# A2A Protocol
# ---------------------------------------------------------------------------

@operations_router.get("/a2a/agents", summary="List A2A agent cards")
async def a2a_list_agents(limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    try:
        from chat_app.a2a_protocol import get_agent_cards
        cards = get_agent_cards()
        total = len(cards)
        page = cards[offset:offset + limit]
        return {"agents": page, "total": total, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[A2A] Agent list failed: %s", exc)
        raise HTTPException(status_code=500, detail=_safe_error(exc, "a2a agent list"))


@operations_router.post("/a2a/task", summary="Execute A2A task")
async def a2a_execute_task(body: A2ATaskRequest):
    try:
        from chat_app.a2a_protocol import handle_a2a_task
        result = await handle_a2a_task({"type": body.type, "agent": body.agent, "input": body.input})
        return {"task_type": body.type, "result": result, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[A2A] Task execution failed: %s", exc)
        raise HTTPException(status_code=500, detail=_safe_error(exc, "a2a task execution"))


# ---------------------------------------------------------------------------
# Unified Tool Registry
# ---------------------------------------------------------------------------

@operations_router.get("/tools/unified-registry", summary="Full unified tool registry dump")
async def get_unified_registry_endpoint(
    category: Optional[str] = Query(None), source: Optional[str] = Query(None),
    intent: Optional[str] = Query(None), search: Optional[str] = Query(None),
    exposure: Optional[str] = Query(None), role: Optional[str] = Query(None),
):
    try:
        from chat_app.unified_registry import get_unified_registry
        reg = get_unified_registry()
        if search:
            tools = reg.search(search)
        elif intent:
            tools = reg.get_for_intent(intent)
        elif category:
            tools = reg.get_by_category(category)
        elif role:
            tools = reg.get_for_role(role)
        elif exposure == "mcp":
            tools = reg.get_mcp_tools()
        elif exposure == "api":
            tools = reg.get_api_services()
        elif exposure == "skill":
            tools = reg.get_skills()
        else:
            tools = reg.get_all()
        if source:
            tools = [t for t in tools if source in t.source_registry]
        return {"total": len(tools), "tools": [t.to_dict() for t in tools], "loaded_at": reg._loaded_at}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.exception("[ADMIN] Unified registry error: %s", exc)
        raise HTTPException(500, _safe_error(exc, "unified registry"))


@operations_router.get("/tools/capabilities", summary="Unified capability report")
async def get_capabilities_report():
    try:
        from chat_app.unified_registry import get_unified_registry
        reg = get_unified_registry()
        report = reg.get_capability_report()
        report["intent_coverage"] = reg.get_intent_coverage()
        return report
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.exception("[ADMIN] Capabilities report error: %s", exc)
        raise HTTPException(500, _safe_error(exc, "capabilities report"))


@operations_router.get("/tools/capabilities/{tool_id:path}", summary="Capability status for a single tool")
async def get_tool_capability_status(tool_id: str):
    try:
        from chat_app.unified_registry import get_unified_registry
        reg = get_unified_registry()
        return reg.get_capability_status(tool_id)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.exception("[ADMIN] Capability status error: %s", exc)
        raise HTTPException(500, _safe_error(exc, "capability status"))


@operations_router.post("/tools/unified-registry/reload", summary="Reload the unified registry")
async def reload_unified_registry_endpoint():
    try:
        from chat_app.unified_registry import reload_unified_registry
        reg = reload_unified_registry()
        report = reg.get_capability_report()
        return {"success": True, "message": f"Reloaded {report['total_tools']} tools", **report}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.exception("[ADMIN] Unified registry reload error: %s", exc)
        raise HTTPException(500, _safe_error(exc, "unified registry reload"))


# ---------------------------------------------------------------------------
# User Personas
# ---------------------------------------------------------------------------

@operations_router.get("/personas", summary="List all AI personas")
async def list_personas_endpoint():
    try:
        from chat_app.user_persona import list_personas
        personas = list_personas()
        return {"personas": [p.to_dict() for p in personas], "total": len(personas), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, _safe_error(exc, "list personas"))


@operations_router.get("/personas/{persona_id}", summary="Get persona details")
async def get_persona_endpoint(persona_id: str):
    try:
        from chat_app.user_persona import get_persona
        persona = get_persona(persona_id)
        if persona is None:
            raise HTTPException(404, detail=f"Persona '{persona_id}' not found")
        return {"persona": persona.to_dict(), "timestamp": _now_iso()}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, _safe_error(exc, "get persona"))


@operations_router.post("/personas", summary="Create a custom persona")
async def create_persona_endpoint(body: PersonaCreateRequest):
    try:
        from chat_app.user_persona import get_persona, save_custom_persona, UserPersona
        if get_persona(body.id) is not None:
            existing = get_persona(body.id)
            if existing and existing.builtin:
                raise HTTPException(409, detail=f"Cannot overwrite built-in persona '{body.id}'")
        persona = UserPersona(
            id=body.id, name=body.name, description=body.description,
            system_prompt_modifier=body.system_prompt_modifier,
            response_style=body.response_style, verbosity=body.verbosity,
            expertise_level=body.expertise_level, follow_up_style=body.follow_up_style,
            icon=body.icon, builtin=False,
        )
        saved = save_custom_persona(persona)
        return {"persona": saved.to_dict(), "created": True, "timestamp": _now_iso()}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, _safe_error(exc, "create persona"))


@operations_router.put("/personas/{persona_id}", summary="Update a persona")
async def update_persona_endpoint(persona_id: str, body: PersonaUpdateRequest):
    try:
        from chat_app.user_persona import get_persona, save_custom_persona
        persona = get_persona(persona_id)
        if persona is None:
            raise HTTPException(404, detail=f"Persona '{persona_id}' not found")
        if persona.builtin:
            raise HTTPException(403, detail="Built-in personas cannot be modified")
        if body.name is not None: persona.name = body.name
        if body.description is not None: persona.description = body.description
        if body.system_prompt_modifier is not None: persona.system_prompt_modifier = body.system_prompt_modifier
        if body.response_style is not None: persona.response_style = body.response_style
        if body.verbosity is not None: persona.verbosity = body.verbosity
        if body.expertise_level is not None: persona.expertise_level = body.expertise_level
        if body.follow_up_style is not None: persona.follow_up_style = body.follow_up_style
        if body.icon is not None: persona.icon = body.icon
        saved = save_custom_persona(persona)
        return {"persona": saved.to_dict(), "updated": True, "timestamp": _now_iso()}
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, _safe_error(exc, "update persona"))
