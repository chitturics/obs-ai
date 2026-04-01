"""Admin Security — Infrastructure Routes (Tenants, Docs, Sidebar, Executions, Workflows, Code).

Extracted from admin_security_audit_routes.py to keep file sizes manageable.
Contains:
- Tenant isolation endpoints
- Documentation generator endpoints
- Project dictionary / manifest endpoints
- Sidebar configuration endpoints
- Execution tracker endpoints
- Workflow engine endpoints
- Code intelligence endpoints

All endpoints use the shared ``security_infra_router`` with the same
prefix, tags, and dependencies as the main security router.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from chat_app.admin_shared import (
    _csrf_check,
    _rate_limit,
    _track_audit_user,
)
from chat_app.auth_dependencies import (
    get_authenticated_user,
    require_admin,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Infrastructure router (same prefix/tags/deps as security_router)
# ---------------------------------------------------------------------------

security_infra_router = APIRouter(
    prefix="/api/admin",
    tags=["security"],
    dependencies=[
        Depends(_rate_limit),
        Depends(require_admin),
        Depends(_track_audit_user),
        Depends(_csrf_check),
    ],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DocGenSnippetRequest(BaseModel):
    """Request to generate documentation from snippets."""
    snippets: List[str] = Field(..., description="Text content to document")
    title: str = Field(default="Documentation", description="Document title")
    format: str = Field(default="markdown", description="Output format: markdown or sharepoint")
    style: str = Field(default="technical", description="Style: technical, user-friendly, api-reference")
    comments: Optional[List[str]] = Field(default=None, description="Reviewer/author comments")
    image_descriptions: Optional[List[str]] = Field(default=None, description="Image descriptions to reference")


# ---------------------------------------------------------------------------
# Tenant Isolation Endpoints
# ---------------------------------------------------------------------------

@security_infra_router.get("/tenants")
async def list_tenants() -> Dict[str, Any]:
    """List all tenants."""
    from chat_app.tenant_isolation import get_tenant_manager

    mgr = get_tenant_manager()
    return mgr.get_stats()


@security_infra_router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str) -> Dict[str, Any]:
    """Get a specific tenant."""
    from chat_app.tenant_isolation import get_tenant_manager

    tenant = get_tenant_manager().get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return tenant.to_dict()


@security_infra_router.get("/tenants/{tenant_id}/export")
async def export_tenant(tenant_id: str) -> Dict[str, Any]:
    """Export a tenant's data manifest."""
    from chat_app.tenant_isolation import get_tenant_manager

    export = get_tenant_manager().export_tenant(tenant_id)
    if not export:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return export.to_dict()


# ---------------------------------------------------------------------------
# Documentation Generator Endpoints
# ---------------------------------------------------------------------------

@security_infra_router.post("/docs/generate")
async def generate_docs_from_snippets(request: DocGenSnippetRequest) -> Dict[str, Any]:
    """Generate professional documentation from text snippets."""
    from chat_app.doc_generator import get_doc_generator

    result = get_doc_generator().from_snippets(
        snippets=request.snippets,
        title=request.title,
        format=request.format,
        comments=request.comments,
        image_descriptions=request.image_descriptions,
        style=request.style,
    )
    return {
        "documentation": result.content,
        "metadata": result.to_dict(),
    }


@security_infra_router.post("/docs/scan")
async def generate_docs_from_scan(
    path: str = Query(..., description="Directory or zip file path to scan"),
    title: str = Query("Project Documentation", description="Document title"),
    format: str = Query("markdown", description="Output format: markdown or sharepoint"),
) -> Dict[str, Any]:
    """Scan a directory or zip file and generate comprehensive documentation."""
    from chat_app.doc_generator import get_doc_generator
    from pathlib import Path as PathLib
    import zipfile

    gen = get_doc_generator()
    target = PathLib(path)

    if target.is_dir():
        result = gen.from_directory(str(target), title=title, format=format)
    elif target.exists() and zipfile.is_zipfile(str(target)):
        result = gen.from_zip(str(target), title=title, format=format)
    else:
        raise HTTPException(status_code=400, detail=f"Path is not a valid directory or zip file: {path}")

    return {
        "documentation": result.content,
        "metadata": result.to_dict(),
    }


# ---------------------------------------------------------------------------
# Project Dictionary Endpoints
# ---------------------------------------------------------------------------

@security_infra_router.get("/project/manifest")
async def get_project_manifest() -> Dict[str, Any]:
    """Get the complete project manifest — all resources, modules, endpoints, variables."""
    from chat_app.project_dictionary import get_project_dictionary

    return get_project_dictionary().build_manifest()


@security_infra_router.get("/project/manifest/{category}")
async def get_project_manifest_category(category: str) -> Dict[str, Any]:
    """Get a specific category from the project manifest."""
    from chat_app.project_dictionary import get_project_dictionary

    data = get_project_dictionary().get(category)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Category not found: {category}")
    return {"category": category, "data": data}


# ---------------------------------------------------------------------------
# Sidebar Configuration Endpoints
# ---------------------------------------------------------------------------

@security_infra_router.get("/sidebar/config")
async def get_sidebar_config_endpoint() -> Dict[str, Any]:
    """Get current sidebar layout configuration."""
    from chat_app.sidebar_config import get_sidebar_config
    return get_sidebar_config()


@security_infra_router.put("/sidebar/config")
async def save_sidebar_config_endpoint(
    request: Request,
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Save sidebar layout configuration (reorder, show/hide items)."""
    from chat_app.sidebar_config import save_sidebar_config
    body = await request.json()
    actor = user.get("identifier", "admin")
    return save_sidebar_config(body, actor=actor)


@security_infra_router.post("/sidebar/reset")
async def reset_sidebar_config_endpoint() -> Dict[str, Any]:
    """Reset sidebar to default layout."""
    from chat_app.sidebar_config import reset_sidebar_config
    return reset_sidebar_config()


# ---------------------------------------------------------------------------
# Execution Tracker Endpoints
# ---------------------------------------------------------------------------

@security_infra_router.get("/executions/dashboard")
async def get_execution_dashboard() -> Dict[str, Any]:
    """Get execution observability dashboard — traces for all commands, skills, agents, MCP tools."""
    from chat_app.execution_tracker import get_execution_store
    return get_execution_store().get_dashboard()


@security_infra_router.get("/executions/traces")
async def get_execution_traces(
    category: Optional[str] = Query(None, description="Filter: command, skill, agent, mcp_tool, workflow"),
    name: Optional[str] = Query(None, description="Filter by name"),
    success: Optional[bool] = Query(None, description="Filter by success"),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """Query execution traces with filtering."""
    from chat_app.execution_tracker import get_execution_store
    traces = get_execution_store().query(category=category, name=name, success=success, limit=limit)
    return {"traces": traces, "count": len(traces)}


@security_infra_router.get("/executions/stats")
async def get_execution_stats() -> Dict[str, Any]:
    """Get execution statistics — counts by category, top executors, top errors."""
    from chat_app.execution_tracker import get_execution_store
    return get_execution_store().get_stats()


# ---------------------------------------------------------------------------
# Workflow Engine Endpoints
# ---------------------------------------------------------------------------

@security_infra_router.get("/workflows/definitions")
async def get_workflow_definitions() -> Dict[str, Any]:
    """Get all workflow definitions — templates showing what steps each workflow executes."""
    from chat_app.workflow_engine import get_workflow_engine
    engine = get_workflow_engine()
    return {
        "definitions": [d.to_dict() for d in engine.get_all_definitions()],
        "count": len(engine.get_all_definitions()),
    }


@security_infra_router.get("/workflows/definitions/{name}")
async def get_workflow_definition(name: str) -> Dict[str, Any]:
    """Get a single workflow definition with all step details."""
    from chat_app.workflow_engine import get_workflow_engine
    defn = get_workflow_engine().get_definition(name)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {name}")
    return defn.to_dict()


@security_infra_router.get("/workflows/runs")
async def get_workflow_runs(
    workflow: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """Get recent workflow executions with step-by-step details."""
    from chat_app.workflow_engine import get_workflow_engine
    runs = get_workflow_engine().get_recent_runs(workflow_name=workflow, limit=limit)
    return {"runs": runs, "count": len(runs)}


@security_infra_router.get("/workflows/runs/{run_id}")
async def get_workflow_run(run_id: str) -> Dict[str, Any]:
    """Get a single workflow run with full step details."""
    from chat_app.workflow_engine import get_workflow_engine
    run = get_workflow_engine().get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run


@security_infra_router.post("/workflows/simulate")
async def simulate_workflow(
    workflow: str = Query(..., description="Workflow name to simulate"),
) -> Dict[str, Any]:
    """Simulate a workflow — predict step-by-step execution with estimated latencies."""
    from chat_app.workflow_engine import get_workflow_engine
    result = get_workflow_engine().simulate(workflow)
    return result.to_dict()


@security_infra_router.get("/workflows/stats")
async def get_workflow_stats() -> Dict[str, Any]:
    """Get workflow execution statistics."""
    from chat_app.workflow_engine import get_workflow_engine
    return get_workflow_engine().get_stats()


# ---------------------------------------------------------------------------
# Code Intelligence Endpoints
# ---------------------------------------------------------------------------

@security_infra_router.get("/code/graph")
async def get_code_dependency_graph() -> Dict[str, Any]:
    """Get the full module dependency graph — nodes, edges, layers."""
    from chat_app.code_intelligence import get_code_intel
    return get_code_intel().get_dependency_graph()


@security_infra_router.get("/code/modules")
async def get_code_modules() -> Dict[str, Any]:
    """Get info for all modules — lines, functions, classes, dependencies."""
    from chat_app.code_intelligence import get_code_intel
    modules = get_code_intel().get_all_modules()
    return {"modules": modules, "count": len(modules)}


@security_infra_router.get("/code/modules/{name}")
async def get_code_module(name: str) -> Dict[str, Any]:
    """Get detailed info about a single module."""
    from chat_app.code_intelligence import get_code_intel
    mod = get_code_intel().get_module(name)
    if not mod:
        raise HTTPException(status_code=404, detail=f"Module not found: {name}")
    return mod


@security_infra_router.get("/code/duplicates")
async def get_code_duplicates() -> Dict[str, Any]:
    """Find function names that exist in multiple modules."""
    from chat_app.code_intelligence import get_code_intel
    dupes = get_code_intel().find_duplicates()
    return {"duplicates": dupes, "count": len(dupes)}


@security_infra_router.get("/code/layers")
async def get_code_layers() -> Dict[str, Any]:
    """Get modules organized by architectural layer."""
    from chat_app.code_intelligence import get_code_intel
    return {"layers": get_code_intel().get_layer_map()}


@security_infra_router.get("/code/health")
async def get_code_health() -> Dict[str, Any]:
    """Get codebase health metrics — coupling, size, god files, orphans."""
    from chat_app.code_intelligence import get_code_intel
    return get_code_intel().get_health_metrics()


@security_infra_router.get("/code/cross-layer")
async def get_cross_layer_deps() -> Dict[str, Any]:
    """Find dependencies that cross architectural layers."""
    from chat_app.code_intelligence import get_code_intel
    violations = get_code_intel().get_cross_layer_dependencies()
    return {"violations": violations, "count": len(violations)}
