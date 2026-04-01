"""Admin Tools Extended Routes 2 — Scripting and Splunk Writer endpoints.

Extracted from admin_tools_routes.py to keep file sizes manageable.
Contains: ansible-validate/analyze/generate, shell-analyze/generate,
python-analyze/generate, update-saved-search, create-knowledge-object.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.settings import get_settings
from chat_app.admin_shared import (
    _csrf_check,
    _rate_limit,
    _track_audit_user,
)
from chat_app.admin_tools_routes_ext import TransformAIRequest  # noqa: F401 — re-export

logger = logging.getLogger(__name__)

tools_ext2_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-tools"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

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


@tools_ext2_router.post("/tools/transform-ai", summary="AI suggest data transformation chain")
async def transform_ai_suggest(body: TransformAIRequest):
    """Given raw data and optional goal, suggest a chain of transform operations."""
    try:
        _s = get_settings()
        import httpx
        import json as _json
        prompt = f"Analyze this data and suggest a chain of transformation operations.\nData (first 500 chars): {body.data[:500]}\n"
        if body.goal:
            prompt += f"Goal: {body.goal}\n"
        prompt += "\nAvailable operations: base64_encode, base64_decode, url_encode, url_decode, hex_encode, hex_decode, html_encode, html_decode, md5, sha1, sha256, json_parse, json_prettify, json_minify, csv_parse, kv_parse, xml_parse, upper, lower, reverse, trim, line_sort, unique_lines, remove_empty, rex_extract, spl_escape, quote_values\n\nReturn a JSON array of operation names in order, then a brief explanation.\nFormat:\n[\"op1\", \"op2\", ...]\nExplanation text here"
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)) as client:
            resp = await client.post(
                f"{_s.ollama.base_url}/api/generate",
                json={"model": _s.ollama.model, "prompt": prompt, "stream": False, "options": {"temperature": 0.2, "num_predict": 300}},
            )
            data = resp.json()
            answer = data.get("response", "")
        lines = answer.strip().split('\n')
        ops = []
        explanation = answer
        for line in lines:
            line = line.strip()
            if line.startswith('['):
                try:
                    ops = _json.loads(line)
                    explanation = '\n'.join(l for l in lines if l.strip() != line).strip()
                    break
                except _json.JSONDecodeError as _exc:
                    logger.debug("Could not parse operations JSON from transform AI line: %s", _exc)
        return {"status": "ok", "operations": ops, "explanation": explanation}
    except (OSError, ValueError, KeyError, TypeError, _json.JSONDecodeError) as exc:
        logger.warning(f"[TOOLS] Transform AI error: {type(exc).__name__}: {exc}")
        return {"status": "error", "operations": [], "explanation": f"AI unavailable: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Scripting Tools
# ---------------------------------------------------------------------------

@tools_ext2_router.post("/tools/ansible-validate", summary="Validate an Ansible playbook")
async def tools_ansible_validate(body: AnsibleValidateRequest):
    try:
        from skills.ansible_ops.skill import ansible_validate_playbook
        result = ansible_validate_playbook(body.yaml_content, check_best_practices=body.check_best_practices)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Validation failed: {type(exc).__name__}: {exc}"}


@tools_ext2_router.post("/tools/ansible-analyze", summary="Analyze an Ansible playbook")
async def tools_ansible_analyze(body: AnsibleAnalyzeRequest):
    try:
        from skills.ansible_ops.skill import ansible_improve_playbook
        result = ansible_improve_playbook(body.yaml_content, focus=body.focus)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Analysis failed: {type(exc).__name__}: {exc}"}


@tools_ext2_router.post("/tools/ansible-generate", summary="Generate Ansible playbook from description")
async def tools_ansible_generate(body: AnsibleGenerateRequest):
    try:
        from skills.ansible_ops.skill import ansible_generate_playbook
        result = ansible_generate_playbook(body.description, complexity=body.complexity)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Generation failed: {type(exc).__name__}: {exc}"}


@tools_ext2_router.post("/tools/shell-analyze", summary="Analyze a shell script")
async def tools_shell_analyze(body: ShellAnalyzeRequest):
    try:
        from skills.shell_scripting.skill import shell_analyze_script
        result = shell_analyze_script(body.script_content)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Analysis failed: {type(exc).__name__}: {exc}"}


@tools_ext2_router.post("/tools/shell-generate", summary="Generate shell script from description")
async def tools_shell_generate(body: ShellGenerateRequest):
    try:
        from skills.shell_scripting.skill import shell_generate_script
        result = shell_generate_script(body.description)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Generation failed: {type(exc).__name__}: {exc}"}


@tools_ext2_router.post("/tools/python-analyze", summary="Analyze a Python script")
async def tools_python_analyze(body: PythonAnalyzeRequest):
    try:
        from skills.python_scripting.skill import python_analyze_script
        result = python_analyze_script(body.script_content)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Analysis failed: {type(exc).__name__}: {exc}"}


@tools_ext2_router.post("/tools/python-generate", summary="Generate Python script from description")
async def tools_python_generate(body: PythonGenerateRequest):
    try:
        from skills.python_scripting.skill import python_generate_script
        result = python_generate_script(body.description)
        return {"status": "ok", **result}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Generation failed: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Splunk Writer Tools
# ---------------------------------------------------------------------------

@tools_ext2_router.post("/tools/update-saved-search", summary="Update an existing Splunk saved search")
async def tools_update_saved_search(body: UpdateSavedSearchRequest):
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
            return {"status": "error", "message": "No fields to update."}
        result = sc.update_saved_search(body.name, app=body.app, **kwargs)
        return {"status": "ok", **result}
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Update failed: {type(exc).__name__}: {exc}"}


@tools_ext2_router.post("/tools/create-knowledge-object", summary="Create a Splunk knowledge object")
async def tools_create_knowledge_object(body: CreateKnowledgeObjectRequest):
    try:
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient()
        result = sc.create_knowledge_object(body.object_type, body.name, body.definition, app=body.app)
        return {"status": "ok", **result}
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Creation failed: {type(exc).__name__}: {exc}"}
