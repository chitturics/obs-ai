"""Admin Security Routes — Core security endpoints.

Contains: audit log, RBAC, error catalog, circuit breakers, safety policies,
idempotency, latency budgets, SLO dashboard, cost dashboard.

Extended security endpoints (governance, approval workflows, secrets, MFA,
tenants, docs, executions, workflow engine, code intelligence) live in
admin_security_audit_routes.py and are re-exported via security_ext_router.

Endpoints:
- /api/admin/audit/* — Immutable audit log (query, verify, stats, export)
- /api/admin/rbac/* — RBAC permissions, defaults, overrides, check
- /api/admin/errors/catalog — Error code catalog
- /api/admin/circuit-breakers/* — Circuit breaker status and reset
- /api/admin/safety/* — Safety classifications, policies, evaluate
- /api/admin/idempotency/* — Idempotency store stats and key lookup
- /api/admin/latency/* — Latency budget summary, reports, timeouts
- /api/admin/slos/* — SLO dashboard and evaluations
- /api/admin/costs/* — Cost/load dashboard and user breakdown
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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
# Router
# ---------------------------------------------------------------------------

security_router = APIRouter(
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

class PermissionCheckRequest(BaseModel):
    """Request to check a specific permission."""
    resource_type: str = Field(..., description="Resource category (tool, collection, config, etc.)")
    resource_id: str = Field(default="*", description="Specific resource identifier")
    action: str = Field(default="read", description="Action to check (read, execute, create, etc.)")
    username: Optional[str] = Field(default=None, description="User to check (default: current user)")


class PermissionOverrideRequest(BaseModel):
    """Request to set per-user permission overrides."""
    username: str = Field(..., description="Target user identifier")
    grants: Optional[List[str]] = Field(default=None, description="Additional permissions to grant")
    denials: Optional[List[str]] = Field(default=None, description="Permissions to explicitly deny")


# ---------------------------------------------------------------------------
# Audit Log Endpoints
# ---------------------------------------------------------------------------

@security_router.get("/audit/entries")
async def get_audit_entries(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    actor: Optional[str] = Query(None, description="Filter by actor"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    target: Optional[str] = Query(None, description="Filter by target"),
    since: Optional[str] = Query(None, description="ISO timestamp — only entries after this time"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Query the immutable audit log with filtering."""
    from chat_app.audit_log import get_audit_log

    log = get_audit_log()
    entries = log.query(
        event_type=event_type,
        actor=actor,
        severity=severity,
        target=target,
        since=since,
        limit=limit,
        offset=offset,
    )
    return {
        "entries": entries,
        "count": len(entries),
        "limit": limit,
        "offset": offset,
    }


@security_router.get("/audit/verify")
async def verify_audit_chain(
    full: bool = Query(False, description="Re-read from file for full verification"),
) -> Dict[str, Any]:
    """Verify the integrity of the audit log hash chain."""
    from chat_app.audit_log import get_audit_log

    log = get_audit_log()
    result = log.verify_chain(full=full)
    return result


@security_router.get("/audit/stats")
async def get_audit_stats() -> Dict[str, Any]:
    """Get audit log statistics."""
    from chat_app.audit_log import get_audit_log

    log = get_audit_log()
    return log.get_stats()


@security_router.get("/audit/export")
async def export_audit_log(
    format: str = Query("json", description="Export format: json, csv, splunk"),
    limit: int = Query(1000, ge=1, le=100000),
    since: Optional[str] = Query(None, description="ISO timestamp — only entries after this time"),
) -> Any:
    """Export audit entries in JSON, CSV, or Splunk HEC format."""
    from chat_app.audit_log import get_audit_log

    if format not in ("json", "csv", "splunk"):
        raise HTTPException(status_code=400, detail="Invalid format. Use: json, csv, splunk")

    log = get_audit_log()
    data = log.export(format=format, limit=limit, since=since)  # type: ignore[arg-type]

    if format == "csv":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=data, media_type="text/csv")

    return {"format": format, "count": len(data) if isinstance(data, list) else 0, "data": data}


# ---------------------------------------------------------------------------
# RBAC Endpoints
# ---------------------------------------------------------------------------

@security_router.get("/rbac/permissions")
async def get_my_permissions(
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Get the full permission set for the current user."""
    from chat_app.rbac import get_user_permissions

    return get_user_permissions(user)


@security_router.get("/rbac/defaults")
async def get_default_permissions() -> Dict[str, Any]:
    """Get the default permission sets for all roles."""
    from chat_app.rbac import get_default_permissions as _get_defaults

    return {"roles": _get_defaults()}


@security_router.post("/rbac/check")
async def check_permission_endpoint(
    request: PermissionCheckRequest,
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Check whether a user has a specific permission."""
    from chat_app.rbac import check_permission

    # If checking for another user, require ADMIN role
    target_user = user
    if request.username and request.username != user.get("identifier"):
        role = user.get("metadata", {}).get("role", "USER")
        if role != "ADMIN":
            raise HTTPException(status_code=403, detail="Only ADMIN can check other users' permissions")
        # Build a synthetic user dict for the target
        target_user = {
            "identifier": request.username,
            "metadata": {"role": "USER"},  # Default; would need DB lookup for real role
        }

    allowed = check_permission(
        target_user,
        request.resource_type,
        request.resource_id,
        request.action,
    )
    return {
        "username": target_user.get("identifier"),
        "permission": f"{request.resource_type}:{request.resource_id}:{request.action}",
        "allowed": allowed,
    }


@security_router.get("/rbac/overrides")
async def list_permission_overrides() -> Dict[str, Any]:
    """List all per-user permission overrides."""
    from chat_app.rbac import list_all_overrides

    overrides = list_all_overrides()
    return {"overrides": overrides, "count": len(overrides)}


@security_router.post("/rbac/overrides")
async def set_permission_overrides(
    request: PermissionOverrideRequest,
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Set per-user permission overrides (grants and/or denials)."""
    from chat_app.rbac import set_user_overrides
    from chat_app.audit_log import get_audit_log

    result = set_user_overrides(
        username=request.username,
        grants=request.grants,
        denials=request.denials,
    )

    # Audit the change
    actor = user.get("identifier", "system")
    get_audit_log().append(
        event_type="rbac_change",
        actor=actor,
        action="set_overrides",
        target=request.username,
        details={
            "grants": request.grants,
            "denials": request.denials,
        },
        severity="high",
    )

    return {"username": request.username, "overrides": result, "status": "updated"}


@security_router.delete("/rbac/overrides/{username}")
async def delete_permission_overrides(
    username: str,
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Remove all permission overrides for a user."""
    from chat_app.rbac import delete_user_overrides
    from chat_app.audit_log import get_audit_log

    removed = delete_user_overrides(username)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No overrides found for user: {username}")

    actor = user.get("identifier", "system")
    get_audit_log().append(
        event_type="rbac_change",
        actor=actor,
        action="delete_overrides",
        target=username,
        severity="high",
    )

    return {"username": username, "status": "removed"}


# ---------------------------------------------------------------------------
# Error Catalog Endpoint
# ---------------------------------------------------------------------------

@security_router.get("/errors/catalog")
async def get_error_catalog() -> Dict[str, Any]:
    """Get the full error code catalog with HTTP status, message templates, and remediation hints."""
    from chat_app.error_taxonomy import get_error_catalog as _get_catalog

    catalog = _get_catalog()
    return {
        "catalog": catalog,
        "count": len(catalog),
        "categories": sorted(set(v["category"] for v in catalog.values())),
    }


# ---------------------------------------------------------------------------
# Circuit Breaker Endpoints
# ---------------------------------------------------------------------------

@security_router.get("/circuit-breakers")
async def get_circuit_breakers() -> Dict[str, Any]:
    """Get status of all circuit breakers."""
    from chat_app.circuit_breaker import get_circuit_breaker_registry

    registry = get_circuit_breaker_registry()
    return {
        "breakers": registry.get_all_status(),
        "stats": registry.get_stats(),
    }


@security_router.get("/circuit-breakers/open")
async def get_open_circuits() -> Dict[str, Any]:
    """Get currently open (disabled) circuit breakers — for status banner."""
    from chat_app.circuit_breaker import get_circuit_breaker_registry

    registry = get_circuit_breaker_registry()
    open_circuits = registry.get_open_circuits()
    return {
        "open_circuits": open_circuits,
        "count": len(open_circuits),
    }


@security_router.post("/circuit-breakers/{tool_name}/reset")
async def reset_circuit_breaker(
    tool_name: str,
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Manually reset a tool's circuit breaker to closed state."""
    from chat_app.circuit_breaker import get_circuit_breaker_registry
    from chat_app.audit_log import get_audit_log

    registry = get_circuit_breaker_registry()
    if not registry.reset(tool_name):
        raise HTTPException(status_code=404, detail=f"No circuit breaker found for tool: {tool_name}")

    actor = user.get("identifier", "system")
    get_audit_log().append(
        event_type="circuit_breaker",
        actor=actor,
        action="manual_reset",
        target=tool_name,
        severity="medium",
    )

    status = registry.get_status(tool_name)
    return {"tool": tool_name, "status": status, "reset_by": actor}


# ---------------------------------------------------------------------------
# Safety Policy Endpoints
# ---------------------------------------------------------------------------

@security_router.get("/safety/classifications")
async def get_safety_classifications() -> Dict[str, Any]:
    """Get all tool safety classifications."""
    from chat_app.safety_policies import get_all_classifications

    return {"classifications": get_all_classifications()}


@security_router.get("/safety/policies")
async def get_safety_policies() -> Dict[str, Any]:
    """Get environment-specific safety policies."""
    from chat_app.safety_policies import get_environment_policies

    return {"policies": get_environment_policies()}


@security_router.post("/safety/evaluate")
async def evaluate_safety_policy(
    tool_name: str = Query(..., description="Tool to evaluate"),
    environment: str = Query("development", description="Target environment"),
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Evaluate the safety policy for a tool in a given environment."""
    from chat_app.safety_policies import evaluate_policy

    role = user.get("metadata", {}).get("role", "USER")
    decision = evaluate_policy(
        tool_name=tool_name,
        user_role=role,
        environment=environment,
    )
    return {
        "tool": tool_name,
        "action": decision.action.value,
        "safety_level": decision.safety_level.value,
        "reason": decision.reason,
        "requires_dry_run": decision.requires_dry_run,
        "approval_role": decision.approval_role,
        "environment": decision.environment,
        "user_role": role,
    }


# ---------------------------------------------------------------------------
# Idempotency Endpoints
# ---------------------------------------------------------------------------

@security_router.get("/idempotency/stats")
async def get_idempotency_stats() -> Dict[str, Any]:
    """Get idempotency store statistics (hit rate, active keys, etc.)."""
    from chat_app.idempotency import get_idempotency_store

    return get_idempotency_store().get_stats()


@security_router.get("/idempotency/check/{key}")
async def check_idempotency_key(key: str) -> Dict[str, Any]:
    """Check if an idempotency key exists and get its cached result."""
    from chat_app.idempotency import get_idempotency_store

    cached = get_idempotency_store().get(key)
    if cached:
        return cached
    return {"idempotency_key": key, "cached": False}


# ---------------------------------------------------------------------------
# Latency Budget Endpoints
# ---------------------------------------------------------------------------

@security_router.get("/latency/summary")
async def get_latency_summary() -> Dict[str, Any]:
    """Get aggregate latency budget summary."""
    from chat_app.latency_budgets import get_latency_tracker

    return get_latency_tracker().get_summary()


@security_router.get("/latency/reports")
async def get_latency_reports() -> Dict[str, Any]:
    """Get per-tool latency reports."""
    from chat_app.latency_budgets import get_latency_tracker

    tracker = get_latency_tracker()
    return {
        "reports": tracker.get_all_reports(),
        "violations": tracker.get_violations(),
    }


@security_router.get("/latency/report/{tool_name}")
async def get_tool_latency_report(tool_name: str) -> Dict[str, Any]:
    """Get latency report for a specific tool."""
    from chat_app.latency_budgets import get_latency_tracker

    return get_latency_tracker().get_report(tool_name)


@security_router.get("/latency/timeouts")
async def get_all_timeouts() -> Dict[str, Any]:
    """Get all configured tool timeouts."""
    from chat_app.latency_budgets import get_latency_tracker

    tracker = get_latency_tracker()
    return {
        "timeouts": tracker.get_all_timeouts(),
        "fallbacks": tracker.get_all_fallbacks(),
    }


# ---------------------------------------------------------------------------
# SLO Dashboard Endpoints
# ---------------------------------------------------------------------------

@security_router.get("/slos/dashboard")
async def get_slo_dashboard() -> Dict[str, Any]:
    """Get unified SLO dashboard — single red/yellow/green health view."""
    from chat_app.slo_tracker import get_slo_tracker

    return get_slo_tracker().get_dashboard()


@security_router.get("/slos")
async def get_all_slos() -> Dict[str, Any]:
    """Get all SLO evaluations."""
    from chat_app.slo_tracker import get_slo_tracker

    tracker = get_slo_tracker()
    return {
        "slos": tracker.evaluate_all(),
        "names": tracker.get_slo_names(),
    }


@security_router.get("/slos/{slo_name}")
async def get_slo(slo_name: str) -> Dict[str, Any]:
    """Get a specific SLO evaluation."""
    from chat_app.slo_tracker import get_slo_tracker

    result = get_slo_tracker().evaluate(slo_name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"SLO not found: {slo_name}")
    return result


# ---------------------------------------------------------------------------
# Cost Dashboard Endpoints
# ---------------------------------------------------------------------------

@security_router.get("/costs/dashboard")
async def get_cost_dashboard(
    hours: int = Query(24, ge=1, le=720),
) -> Dict[str, Any]:
    """Get cost/load dashboard — LLM tokens, retrieval, tool runtimes per user."""
    from chat_app.cost_tracker import get_cost_tracker

    return get_cost_tracker().get_dashboard(hours=hours)


@security_router.get("/costs/users")
async def get_cost_by_user(
    top_n: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """Get cost breakdown by user."""
    from chat_app.cost_tracker import get_cost_tracker

    return get_cost_tracker().get_by_user(top_n=top_n)


# ---------------------------------------------------------------------------
# Re-export extended routes for backward compatibility
# ---------------------------------------------------------------------------
from chat_app.admin_security_audit_routes import security_ext_router  # noqa: E402,F401

