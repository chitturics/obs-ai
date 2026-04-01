"""Admin sub-router: Utility and tool endpoints.

Handles these endpoint groups:
- POST /api/admin/tools/network-test     — Network diagnostic (DNS, ping, port check)
- POST /api/admin/tools/syslog-test      — Compose/send syslog events
- POST /api/admin/tools/regex-ai         — AI-powered regex assessment
- POST /api/admin/tools/regex-generate   — AI regex from selected text
- POST /api/admin/tools/fs-monitor       — Filesystem monitoring
- POST /api/admin/tools/ai-chat          — AI assistant for tools pages
- POST /api/admin/tools/transform-ai     — AI data transformation suggestion
- POST /api/admin/tools/ansible-validate — Ansible playbook validation
- POST /api/admin/tools/ansible-analyze  — Ansible playbook analysis
- POST /api/admin/tools/ansible-generate — Ansible playbook generation
- POST /api/admin/tools/shell-analyze    — Shell script analysis
- POST /api/admin/tools/shell-generate   — Shell script generation
- POST /api/admin/tools/python-analyze   — Python script analysis
- POST /api/admin/tools/python-generate  — Python script generation
- POST /api/admin/tools/update-saved-search   — Splunk saved search update
- POST /api/admin/tools/create-knowledge-object — Splunk knowledge object creation
- POST /api/admin/utilities/{operation}  — Execute a utility operation
- GET  /api/admin/api-catalog            — Returns all available API operations

Mount with:
    from chat_app.admin_tools import tools_router
    app.include_router(tools_router)
"""

import logging

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.admin_shared import (
    _csrf_check,
    _rate_limit,
    _track_audit_user,
    _UTILITY_OPS,
)

logger = logging.getLogger(__name__)

tools_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-tools"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class NetworkTestRequest(BaseModel):
    tool: str = Field(..., pattern="^(dns|ping|port)$")
    target: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=0, ge=0, le=65535)


class SyslogTestRequest(BaseModel):
    format: str = Field(default="rfc3164", pattern="^(rfc3164|rfc5424|hec)$")
    facility: int = Field(default=16, ge=0, le=23)  # 16=local0
    severity: int = Field(default=6, ge=0, le=7)  # 6=info
    hostname: str = Field(default="testhost", max_length=255)
    app_name: str = Field(default="myapp", max_length=128)
    pid: int = Field(default=0, ge=0, le=99999)
    message: str = Field(..., min_length=1, max_length=10000)
    target: str = Field(default="", max_length=255)  # hostname to send to
    port: int = Field(default=514, ge=1, le=65535)
    protocol: str = Field(default="udp", pattern="^(udp|tcp)$")
    send: bool = Field(default=False)  # if True, actually send; if False, just preview


class RegexAIRequest(BaseModel):
    pattern: str = Field(..., min_length=1, max_length=2000)
    description: str = Field(default="", max_length=500)
    sample_text: str = Field(default="", max_length=10000)


class RegexGenerateRequest(BaseModel):
    selected_text: str = Field(..., min_length=1, max_length=5000)
    full_text: str = Field(default="", max_length=50000)
    description: str = Field(default="", max_length=500)


class FSMonitorRequest(BaseModel):
    path: str = Field(default="/var/log", max_length=500)
    pattern: str = Field(default="*", max_length=200)
    max_files: int = Field(default=100, ge=1, le=500)
    generate_inputs_conf: bool = Field(default=False)


class ToolsAIChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    context: str = Field(default="", max_length=5000)
    page: str = Field(default="general", max_length=50)


class TransformAIRequest(BaseModel):
    data: str = Field(..., min_length=1, max_length=10000)
    goal: str = Field(default="", max_length=500)


class AnsibleValidateRequest(BaseModel):
    yaml_content: str = Field(..., min_length=1, max_length=100000)
    check_best_practices: bool = Field(default=True)


class AnsibleAnalyzeRequest(BaseModel):
    yaml_content: str = Field(..., min_length=1, max_length=100000)
    focus: str = Field(default="all", pattern="^(all|performance|security|structure)$")


class AnsibleGenerateRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)
    complexity: str = Field(default="intermediate", pattern="^(basic|intermediate|advanced)$")


class ShellAnalyzeRequest(BaseModel):
    script_content: str = Field(..., min_length=1, max_length=100000)


class ShellGenerateRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)


class PythonAnalyzeRequest(BaseModel):
    script_content: str = Field(..., min_length=1, max_length=100000)


class PythonGenerateRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)


class UpdateSavedSearchRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    search: Optional[str] = Field(default=None, max_length=100000)
    description: Optional[str] = Field(default=None, max_length=5000)
    cron_schedule: Optional[str] = Field(default=None, max_length=100)
    app: str = Field(default="search", max_length=200)


class CreateKnowledgeObjectRequest(BaseModel):
    object_type: str = Field(..., pattern="^(macro|eventtypes|tags|saved_search)$")
    name: str = Field(..., min_length=1, max_length=500)
    definition: str = Field(..., min_length=1, max_length=100000)
    app: str = Field(default="search", max_length=200)


# ---------------------------------------------------------------------------
# NOTE: The 7 large endpoint implementations are in admin_tools_impl.py.
# That module is imported at the bottom of this file so the routes register
# onto tools_router.  Do NOT add them back here.
# Covered: network-test, syslog-test, regex-ai, regex-generate,
#          fs-monitor, ai-chat, transform-ai
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Ansible / Shell / Python scripting tool endpoints
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Ansible / Shell / Python scripting tool endpoints
# ---------------------------------------------------------------------------

@tools_router.post("/tools/ansible-validate", summary="Validate an Ansible playbook")
async def tools_ansible_validate(body: AnsibleValidateRequest):
    """Validate YAML syntax, structure, and optionally best practices."""
    try:
        from skills.ansible_ops.skill import ansible_validate_playbook
        result = ansible_validate_playbook(
            body.yaml_content,
            check_best_practices=body.check_best_practices,
        )
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Ansible validate error: {type(exc).__name__}: {exc}")
        return {"status": "error", "message": f"Validation failed: {type(exc).__name__}: {exc}"}


@tools_router.post("/tools/ansible-analyze", summary="Analyze an Ansible playbook")
async def tools_ansible_analyze(body: AnsibleAnalyzeRequest):
    """Deep analysis of playbook: structure, security, performance, improvements."""
    try:
        from skills.ansible_ops.skill import ansible_improve_playbook
        result = ansible_improve_playbook(body.yaml_content, focus=body.focus)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Ansible analyze error: {type(exc).__name__}: {exc}")
        return {"status": "error", "message": f"Analysis failed: {type(exc).__name__}: {exc}"}


@tools_router.post("/tools/ansible-generate", summary="Generate Ansible playbook from description")
async def tools_ansible_generate(body: AnsibleGenerateRequest):
    """Generate a playbook from natural language description."""
    try:
        from skills.ansible_ops.skill import ansible_generate_playbook
        result = ansible_generate_playbook(body.description, complexity=body.complexity)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Ansible generate error: {type(exc).__name__}: {exc}")
        return {"status": "error", "message": f"Generation failed: {type(exc).__name__}: {exc}"}


@tools_router.post("/tools/shell-analyze", summary="Analyze a shell script")
async def tools_shell_analyze(body: ShellAnalyzeRequest):
    """Analyze shell script for issues, best practices, and improvements."""
    try:
        from skills.shell_scripting.skill import shell_analyze_script
        result = shell_analyze_script(body.script_content)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Shell analyze error: {type(exc).__name__}: {exc}")
        return {"status": "error", "message": f"Analysis failed: {type(exc).__name__}: {exc}"}


@tools_router.post("/tools/shell-generate", summary="Generate shell script from description")
async def tools_shell_generate(body: ShellGenerateRequest):
    """Generate a shell script from natural language description."""
    try:
        from skills.shell_scripting.skill import shell_generate_script
        result = shell_generate_script(body.description)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Shell generate error: {type(exc).__name__}: {exc}")
        return {"status": "error", "message": f"Generation failed: {type(exc).__name__}: {exc}"}


@tools_router.post("/tools/python-analyze", summary="Analyze a Python script")
async def tools_python_analyze(body: PythonAnalyzeRequest):
    """Analyze Python script for anti-patterns, security issues, and improvements."""
    try:
        from skills.python_scripting.skill import python_analyze_script
        result = python_analyze_script(body.script_content)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Python analyze error: {type(exc).__name__}: {exc}")
        return {"status": "error", "message": f"Analysis failed: {type(exc).__name__}: {exc}"}


@tools_router.post("/tools/python-generate", summary="Generate Python script from description")
async def tools_python_generate(body: PythonGenerateRequest):
    """Generate a Python script from natural language description."""
    try:
        from skills.python_scripting.skill import python_generate_script
        result = python_generate_script(body.description)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Python generate error: {type(exc).__name__}: {exc}")
        return {"status": "error", "message": f"Generation failed: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Splunk Writer Tools
# ---------------------------------------------------------------------------

@tools_router.post("/tools/update-saved-search", summary="Update an existing Splunk saved search")
async def tools_update_saved_search(body: UpdateSavedSearchRequest):
    """Update a saved search on the connected Splunk instance. Requires Splunk connectivity."""
    try:
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient()
        kwargs = {}
        if body.search is not None:
            kwargs["search"] = body.search
        if body.description is not None:
            kwargs["description"] = body.description
        if body.cron_schedule is not None:
            kwargs["cron_schedule"] = body.cron_schedule
        if not kwargs:
            return {"status": "error", "message": "No fields to update. Provide search, description, or cron_schedule."}
        result = sc.update_saved_search(body.name, app=body.app, **kwargs)
        return {"status": "ok", **result}
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Update saved search error: {type(exc).__name__}: {exc}")
        return {"status": "error", "message": f"Update failed: {type(exc).__name__}: {exc}"}


@tools_router.post("/tools/create-knowledge-object", summary="Create a Splunk knowledge object")
async def tools_create_knowledge_object(body: CreateKnowledgeObjectRequest):
    """Create a macro, eventtype, tag, or saved search in Splunk."""
    try:
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient()
        result = sc.create_knowledge_object(body.object_type, body.name, body.definition, app=body.app)
        return {"status": "ok", **result}
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Create knowledge object error: {type(exc).__name__}: {exc}")
        return {"status": "error", "message": f"Creation failed: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# POST /api/admin/utilities/{operation}
# ---------------------------------------------------------------------------

@tools_router.post("/utilities/{operation}", summary="Execute a utility operation")
async def execute_utility(operation: str, request: Request):
    """Execute a utility operation (encoding, hashing, data transform). Accessible to all authenticated users."""
    body = await request.json()
    input_text = body.get("input", "")
    if not input_text:
        raise HTTPException(400, "Missing 'input' field")

    from chat_app.skill_executor import get_internal_handler
    handler = get_internal_handler(operation)
    if not handler:
        raise HTTPException(404, f"Unknown utility: {operation}")

    if operation not in _UTILITY_OPS:
        raise HTTPException(403, f"Operation '{operation}' is not a utility -- use /agentic/execute-skill instead")

    try:
        result = handler(user_input=input_text, **body)
        return {"operation": operation, "result": result, "success": True}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        return {"operation": operation, "error": str(e), "success": False}


# ---------------------------------------------------------------------------
# GET /api/admin/api-catalog
# ---------------------------------------------------------------------------

@tools_router.get("/api-catalog", summary="Returns all available API operations")
async def get_api_catalog():
    """Returns all available API operations with name, description, required_role, and parameters."""
    from chat_app.skill_catalog import SKILL_CATALOG, ApprovalGate as _AG

    catalog = []
    for skill in SKILL_CATALOG:
        catalog.append({
            "name": skill.name,
            "action": skill.action,
            "description": skill.description,
            "family": skill.family.value if hasattr(skill.family, 'value') else str(skill.family),
            "handler_key": skill.handler_key,
            "min_role": getattr(skill, 'min_role', 'USER'),
            "approval_required": skill.approval != _AG.AUTO if hasattr(skill, 'approval') else False,
            "intents": skill.intents if hasattr(skill, 'intents') else [],
            "tags": getattr(skill, 'tags', []),
            "api_endpoint": f"/api/admin/utilities/{skill.handler_key}" if "data_transform" in (skill.intents or []) else "/api/admin/agentic/execute-skill",
        })

    return {
        "total_skills": len(catalog),
        "catalog": catalog,
        "utility_endpoint": "/api/admin/utilities/{operation}",
        "skill_endpoint": "/api/admin/agentic/execute-skill",
        "dispatch_endpoint": "/api/admin/agentic/dispatch",
        "auth_methods": ["X-API-Key header", "Bearer token", "Cookie JWT"],
        "roles": ["VIEWER", "USER", "ANALYST", "ADMIN"],
    }


# ---------------------------------------------------------------------------
# GET /api/admin/tools/capabilities
# ---------------------------------------------------------------------------

@tools_router.get("/tools/capabilities", summary="Tool capability discovery and availability report")
async def get_tools_capabilities():
    """Return a full capability report covering all tools/skills/MCP definitions.

    Reports which tools are available, unavailable (with reasons), or degraded.
    Includes MCP capability metadata for discovery protocol consumers.
    """
    from chat_app.unified_registry import get_unified_registry

    reg = get_unified_registry()
    report = reg.get_capability_report()
    mcp_caps = reg.get_mcp_capabilities()
    intent_coverage = reg.get_intent_coverage()

    return {
        "capabilities": report,
        "mcp": mcp_caps,
        "intent_coverage": intent_coverage,
    }


# ---------------------------------------------------------------------------
# Register large endpoint implementations from the split module.
# This must come LAST (after tools_router is defined).
# ---------------------------------------------------------------------------
import chat_app.admin_tools_impl  # noqa: F401, E402
