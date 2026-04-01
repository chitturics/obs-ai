"""Admin Security — Governance, Approval, Secrets, MFA, Tenants, Docs, Infra Routes.

Extracted from admin_security_routes.py to keep file sizes manageable.
Contains:
- Runbook endpoints
- Data governance (PII, retention policies)
- Policy engine (policy-as-code)
- Approval workflows
- Secrets management
- Credential scoping
- Self-evaluation stats
- MFA management
- Tenant quotas
- Persona orchestration
- Tenant isolation
- Documentation generator
- Project dictionary (manifest)
- Sidebar configuration
- Execution tracker
- Workflow engine
- Code intelligence

All endpoints are added to the shared ``security_router`` imported from
``admin_security_routes``.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

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
# Extended router (same prefix/tags/deps as main security_router)
# ---------------------------------------------------------------------------

security_ext_router = APIRouter(
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
# Runbook Endpoints
# ---------------------------------------------------------------------------

@security_ext_router.get("/runbooks")
async def get_all_runbooks() -> Dict[str, Any]:
    """Get all registered runbooks."""
    from chat_app.runbooks import get_runbook_registry

    registry = get_runbook_registry()
    return {
        "runbooks": registry.to_list(),
        "count": len(registry.get_all()),
        "categories": registry.get_categories(),
    }


@security_ext_router.get("/runbooks/search")
async def search_runbooks(
    query: str = Query(..., description="Search keyword"),
) -> Dict[str, Any]:
    """Search runbooks by keyword."""
    from chat_app.runbooks import get_runbook_registry

    results = get_runbook_registry().search(query)
    return {
        "results": [r.to_dict() for r in results],
        "count": len(results),
        "query": query,
    }


@security_ext_router.get("/runbooks/{alert_key}")
async def get_runbook(alert_key: str) -> Dict[str, Any]:
    """Get the runbook for a specific alert."""
    from chat_app.runbooks import get_runbook_registry

    rb = get_runbook_registry().get_for_alert(alert_key)
    if rb is None:
        raise HTTPException(status_code=404, detail=f"Runbook not found: {alert_key}")
    return rb.to_dict()


# ---------------------------------------------------------------------------
# Data Governance Endpoints
# ---------------------------------------------------------------------------

@security_ext_router.get("/governance/report")
async def get_governance_report() -> Dict[str, Any]:
    """Get data governance compliance report."""
    from chat_app.data_governance import get_governance_manager

    return get_governance_manager().get_compliance_report()


@security_ext_router.get("/governance/policies")
async def get_retention_policies() -> Dict[str, Any]:
    """Get all data retention policies."""
    from chat_app.data_governance import get_governance_manager

    mgr = get_governance_manager()
    return {
        "policies": [p.to_dict() for p in mgr.get_all_policies()],
        "pii_sources": [p.source for p in mgr.get_pii_sources()],
    }


@security_ext_router.post("/governance/scan-pii")
async def scan_for_pii(
    text: str = Query(..., description="Text to scan for PII"),
) -> Dict[str, Any]:
    """Scan text for PII occurrences."""
    from chat_app.data_governance import get_governance_manager

    findings = get_governance_manager().scan_for_pii(text)
    return {
        "has_pii": len(findings) > 0,
        "findings": [f.to_dict() for f in findings],
        "count": len(findings),
    }


@security_ext_router.post("/governance/redact")
async def redact_pii(
    text: str = Query(..., description="Text to redact PII from"),
) -> Dict[str, Any]:
    """Redact PII from text."""
    from chat_app.data_governance import get_governance_manager

    mgr = get_governance_manager()
    redacted = mgr.redact_pii(text)
    return {
        "original_has_pii": mgr.has_pii(text),
        "redacted": redacted,
    }


# ---------------------------------------------------------------------------
# Policy Engine Endpoints
# ---------------------------------------------------------------------------

@security_ext_router.get("/policies")
async def get_all_policies() -> Dict[str, Any]:
    """Get all policy-as-code rules."""
    from chat_app.policy_engine import get_policy_engine

    engine = get_policy_engine()
    return {
        "rules": engine.get_all_rules(),
        "stats": engine.get_stats(),
    }


@security_ext_router.post("/policies/evaluate")
async def evaluate_policy(
    tool: str = Query(..., description="Tool to evaluate"),
    environment: str = Query("development", description="Target environment"),
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Evaluate all policies for a tool execution."""
    from chat_app.policy_engine import get_policy_engine, PolicyContext

    role = user.get("metadata", {}).get("role", "USER")
    ctx = PolicyContext(
        tool=tool,
        actor=user.get("identifier", "unknown"),
        role=role,
        environment=environment,
    )
    result = get_policy_engine().evaluate(ctx)
    return result.to_dict()


@security_ext_router.post("/policies/{name}/toggle")
async def toggle_policy(
    name: str,
    enabled: bool = Query(..., description="Enable or disable the policy"),
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Enable or disable a policy rule."""
    from chat_app.policy_engine import get_policy_engine

    engine = get_policy_engine()
    if enabled:
        success = engine.enable_rule(name)
    else:
        success = engine.disable_rule(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Policy not found: {name}")
    return {"name": name, "enabled": enabled}


# ---------------------------------------------------------------------------
# Approval Workflow Endpoints
# ---------------------------------------------------------------------------

@security_ext_router.get("/approval-workflows")
async def get_approval_workflows(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """Get approval workflow history."""
    from chat_app.approval_workflows import get_approval_manager

    mgr = get_approval_manager()
    history = mgr.get_history(limit=limit)
    if status:
        history = [w for w in history if w.status.value == status]
    return {
        "workflows": [w.to_dict() for w in history],
        "count": len(history),
        "stats": mgr.get_stats(),
    }


@security_ext_router.get("/approval-workflows/pending")
async def get_pending_approvals(
    role: Optional[str] = Query(None, description="Filter by required approver role"),
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Get pending approval workflows for the current user's role."""
    from chat_app.approval_workflows import get_approval_manager

    user_role = role or user.get("metadata", {}).get("role", "USER")
    pending = get_approval_manager().get_pending(role=user_role)
    return {
        "pending": [w.to_dict() for w in pending],
        "count": len(pending),
    }


@security_ext_router.get("/approval-workflows/change-windows")
async def get_change_windows() -> Dict[str, Any]:
    """Get all change windows with current status."""
    from chat_app.approval_workflows import get_approval_manager

    return {"windows": get_approval_manager().get_change_windows()}


@security_ext_router.get("/approval-workflows/{workflow_id}")
async def get_approval_workflow(workflow_id: str) -> Dict[str, Any]:
    """Get a specific approval workflow."""
    from chat_app.approval_workflows import get_approval_manager

    wf = get_approval_manager().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")
    return wf.to_dict()


@security_ext_router.post("/approval-workflows/{workflow_id}/approve")
async def approve_workflow_step(
    workflow_id: str,
    reason: str = Query("", description="Approval reason"),
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Approve the current step of an approval workflow."""
    from chat_app.approval_workflows import get_approval_manager

    role = user.get("metadata", {}).get("role", "USER")
    actor = user.get("identifier", "unknown")
    result = get_approval_manager().approve_step(workflow_id, actor, role, reason)
    if not result:
        raise HTTPException(status_code=400, detail="Cannot approve: workflow not found or role mismatch")
    return result.to_dict()


@security_ext_router.post("/approval-workflows/{workflow_id}/deny")
async def deny_workflow_step(
    workflow_id: str,
    reason: str = Query("", description="Denial reason"),
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Deny the current step (denies entire workflow)."""
    from chat_app.approval_workflows import get_approval_manager

    actor = user.get("identifier", "unknown")
    result = get_approval_manager().deny_step(workflow_id, actor, reason)
    if not result:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")
    return result.to_dict()


# ---------------------------------------------------------------------------
# Secrets Management Endpoints
# ---------------------------------------------------------------------------

@security_ext_router.get("/secrets/report")
async def get_secrets_report() -> Dict[str, Any]:
    """Get secret rotation report — overdue, unset, never rotated."""
    from chat_app.secrets_manager import get_secrets_manager

    return get_secrets_manager().get_rotation_report()


@security_ext_router.post("/secrets/{name}/rotate")
async def mark_secret_rotated(
    name: str,
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Mark a secret as just rotated."""
    from chat_app.secrets_manager import get_secrets_manager
    from chat_app.audit_log import get_audit_log

    entry = get_secrets_manager().mark_rotated(name)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Secret not found: {name}")

    actor = user.get("identifier", "system")
    get_audit_log().append(
        event_type="secret_rotation",
        actor=actor,
        action="rotate",
        target=name,
        severity="high",
    )
    return entry.to_dict()


@security_ext_router.post("/secrets/scan")
async def scan_for_plaintext_secrets(
    path: str = Query("/app/config.yaml", description="File or directory to scan"),
) -> Dict[str, Any]:
    """Scan a file or directory for plaintext secrets."""
    from chat_app.secrets_manager import get_secrets_manager
    from pathlib import Path

    mgr = get_secrets_manager()
    target = Path(path)
    if target.is_dir():
        findings = mgr.scan_directory(str(target))
    else:
        findings = mgr.scan_for_plaintext(str(target))
    return {
        "path": path,
        "findings": [f.to_dict() for f in findings],
        "count": len(findings),
        "clean": len(findings) == 0,
    }


# ---------------------------------------------------------------------------
# Credential Scoping Endpoints
# ---------------------------------------------------------------------------

@security_ext_router.get("/connectors/health")
async def get_connector_health() -> Dict[str, Any]:
    """Get health status of all external service connectors."""
    from chat_app.credential_scoping import get_credential_manager

    return get_credential_manager().get_connector_health()


@security_ext_router.get("/connectors/scopes")
async def get_connector_scopes() -> Dict[str, Any]:
    """Get all tool-to-scope mappings for external connectors."""
    from chat_app.credential_scoping import get_credential_manager

    return {"scopes": get_credential_manager().get_all_scopes()}


@security_ext_router.get("/connectors/{service}/credentials")
async def get_service_credentials(service: str) -> Dict[str, Any]:
    """Get credentials for a specific service (masked)."""
    from chat_app.credential_scoping import get_credential_manager

    creds = get_credential_manager().get_for_service(service)
    if not creds:
        raise HTTPException(status_code=404, detail=f"No credentials for service: {service}")
    return {
        "service": service,
        "credentials": [c.to_dict() for c in creds],
    }


# ---------------------------------------------------------------------------
# Self-Evaluation Endpoints
# ---------------------------------------------------------------------------

@security_ext_router.get("/evaluation/stats")
async def get_evaluation_stats() -> Dict[str, Any]:
    """Get self-evaluation statistics — confidence trends, grounding distribution."""
    from chat_app.self_evaluation import get_evaluator

    return get_evaluator().get_stats()


# ---------------------------------------------------------------------------
# MFA Endpoints
# ---------------------------------------------------------------------------

@security_ext_router.get("/mfa/stats")
async def get_mfa_stats() -> Dict[str, Any]:
    """Get MFA enrollment and verification statistics."""
    from chat_app.mfa import get_mfa_manager

    return get_mfa_manager().get_stats()


@security_ext_router.post("/mfa/enroll")
async def enroll_mfa(
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Enroll the current user in MFA. Returns secret and QR URI."""
    from chat_app.mfa import get_mfa_manager

    username = user.get("identifier", "unknown")
    return get_mfa_manager().enroll(username)


@security_ext_router.post("/mfa/verify")
async def verify_mfa(
    code: str = Query(..., description="6-digit TOTP code or backup code"),
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Verify a TOTP code for the current user."""
    from chat_app.mfa import get_mfa_manager

    username = user.get("identifier", "unknown")
    valid = get_mfa_manager().verify(username, code)
    return {"username": username, "valid": valid}


@security_ext_router.get("/mfa/enrollments")
async def get_mfa_enrollments() -> Dict[str, Any]:
    """Get all MFA enrollments (admin view)."""
    from chat_app.mfa import get_mfa_manager

    enrollments = get_mfa_manager().get_all_enrollments()
    return {"enrollments": enrollments, "count": len(enrollments)}


# ---------------------------------------------------------------------------
# Tenant Quota Endpoints
# ---------------------------------------------------------------------------

@security_ext_router.get("/quotas")
async def get_quota_definitions() -> Dict[str, Any]:
    """Get all quota definitions."""
    from chat_app.tenant_quotas import get_quota_manager

    return {"quotas": get_quota_manager().get_quota_definitions()}


@security_ext_router.get("/quotas/stats")
async def get_quota_stats() -> Dict[str, Any]:
    """Get global quota statistics."""
    from chat_app.tenant_quotas import get_quota_manager

    return get_quota_manager().get_stats()


@security_ext_router.get("/quotas/{tenant}")
async def get_tenant_quotas(tenant: str) -> Dict[str, Any]:
    """Get quota usage for a specific tenant."""
    from chat_app.tenant_quotas import get_quota_manager

    return get_quota_manager().get_tenant_usage(tenant)


# ---------------------------------------------------------------------------
# Persona Orchestration Endpoints
# ---------------------------------------------------------------------------

@security_ext_router.get("/personas/affinity-matrix")
async def get_persona_affinity_matrix() -> Dict[str, Any]:
    """Get the persona-agent affinity matrix."""
    from chat_app.persona_orchestration import get_persona_orchestrator

    po = get_persona_orchestrator()
    return {"matrix": po.get_affinity_matrix(), "stats": po.get_stats()}


@security_ext_router.get("/personas/history")
async def get_persona_history(
    username: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """Get persona change history."""
    from chat_app.persona_orchestration import get_persona_orchestrator

    history = get_persona_orchestrator().get_persona_history(username=username, limit=limit)
    return {"history": history, "count": len(history)}


# ---------------------------------------------------------------------------
# Re-export infra routes for backward compatibility
# ---------------------------------------------------------------------------
from chat_app.admin_security_infra_routes import security_infra_router  # noqa: E402,F401
