"""
Workflow Templates — Pre-defined multi-agent workflow patterns and LLM-based planning.

Extracted from workflow_orchestrator.py for size management.
WorkflowOrchestrator imports from this module.

Provides:
- _template_* functions (analyze_and_optimize, troubleshoot, build_and_deploy, investigate, security_audit)
- WORKFLOW_TEMPLATES dict
- detect_workflow() — regex/intent-based template selection
- _is_multi_step_query() — heuristic for LLM planning gate
- llm_plan_workflow() — async LLM-based plan generation with Pydantic validation
- _parse_llm_plan_response(), _build_validated_plan() — plan parsing helpers
"""
from __future__ import annotations

import json as _json
import logging
from typing import Callable, Dict, List, Optional

from chat_app.agent_catalog import Department
from chat_app.registry import Intent
from chat_app.workflow_models import (
    ValidatedWorkflowPlan,
    ValidatedWorkflowStep,
    WorkflowPlan,
    WorkflowTask,
    _validated_plan_to_workflow,
)

# validate_plan_capabilities is imported lazily inside _build_validated_plan to
# allow test patching of get_agent_catalog at chat_app.workflow_orchestrator scope.

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workflow templates — common multi-agent patterns
# ---------------------------------------------------------------------------

def _template_analyze_and_optimize(user_input: str) -> WorkflowPlan:
    """Analyze then optimize workflow."""
    return WorkflowPlan(
        description="Analyze and optimize",
        tasks=[
            WorkflowTask(
                id=0, description="Analyze the query/configuration",
                intent=Intent.SPL_GENERATION,
                preferred_department=Department.ENGINEERING,
                params={"user_input": user_input},
            ),
            WorkflowTask(
                id=1, description="Generate optimization recommendations",
                intent=Intent.SPL_OPTIMIZATION,
                preferred_department=Department.ENGINEERING,
                depends_on=[0],
                params={"user_input": user_input},
            ),
            WorkflowTask(
                id=2, description="Validate the optimized result",
                intent=Intent.SPL_GENERATION,
                preferred_department=Department.ENGINEERING,
                depends_on=[1],
                params={"user_input": user_input},
            ),
        ],
    )


def _template_troubleshoot(user_input: str) -> WorkflowPlan:
    """Troubleshooting workflow."""
    return WorkflowPlan(
        description="Troubleshoot and diagnose",
        tasks=[
            WorkflowTask(
                id=0, description="Identify the problem area",
                intent=Intent.TROUBLESHOOTING,
                preferred_department=Department.SUPPORT,
                params={"user_input": user_input},
            ),
            WorkflowTask(
                id=1, description="Search knowledge base for solutions",
                intent=Intent.GENERAL_QA,
                preferred_department=Department.KNOWLEDGE,
                depends_on=[0],
                params={"user_input": user_input},
            ),
            WorkflowTask(
                id=2, description="Suggest resolution steps",
                intent=Intent.TROUBLESHOOTING,
                preferred_department=Department.SUPPORT,
                depends_on=[0, 1],
                params={"user_input": user_input},
            ),
        ],
    )


def _template_build_and_deploy(user_input: str) -> WorkflowPlan:
    """Build, validate, and deploy workflow."""
    return WorkflowPlan(
        description="Build, validate, and deploy",
        tasks=[
            WorkflowTask(
                id=0, description="Understand requirements and design",
                intent=Intent.CONFIG_LOOKUP,
                preferred_department=Department.ENGINEERING,
                params={"user_input": user_input},
            ),
            WorkflowTask(
                id=1, description="Build the configuration/query",
                intent=Intent.SPL_GENERATION,
                preferred_department=Department.ENGINEERING,
                depends_on=[0],
                params={"user_input": user_input},
            ),
            WorkflowTask(
                id=2, description="Validate and check for issues",
                intent=Intent.CONFIG_HEALTH_CHECK,
                preferred_department=Department.ENGINEERING,
                depends_on=[1],
                params={"user_input": user_input},
            ),
        ],
    )


def _template_investigate(user_input: str) -> WorkflowPlan:
    """Investigation workflow: gather → analyze → report."""
    return WorkflowPlan(
        description="Investigate and report",
        tasks=[
            WorkflowTask(
                id=0, description="Gather relevant information",
                intent=Intent.GENERAL_QA,
                preferred_department=Department.KNOWLEDGE,
                params={"user_input": user_input},
            ),
            WorkflowTask(
                id=1, description="Analyze findings",
                intent=Intent.SPL_GENERATION,
                preferred_department=Department.DATA,
                depends_on=[0],
                params={"user_input": user_input},
            ),
            WorkflowTask(
                id=2, description="Summarize and report",
                intent=Intent.GENERAL_QA,
                preferred_department=Department.KNOWLEDGE,
                depends_on=[0, 1],
                params={"user_input": user_input},
            ),
        ],
    )


def _template_security_audit(user_input: str) -> WorkflowPlan:
    """Security audit workflow."""
    return WorkflowPlan(
        description="Security audit",
        tasks=[
            WorkflowTask(
                id=0, description="Scan for security issues",
                intent=Intent.CONFIG_HEALTH_CHECK,
                preferred_department=Department.SECURITY,
                params={"user_input": user_input},
            ),
            WorkflowTask(
                id=1, description="Check configurations for vulnerabilities",
                intent=Intent.CONFIG_HEALTH_CHECK,
                preferred_department=Department.SECURITY,
                depends_on=[0],
                params={"user_input": user_input},
            ),
            WorkflowTask(
                id=2, description="Generate security report",
                intent=Intent.GENERAL_QA,
                preferred_department=Department.SECURITY,
                depends_on=[0, 1],
                params={"user_input": user_input},
            ),
        ],
    )


# Register templates
WORKFLOW_TEMPLATES: Dict[str, Callable] = {
    "analyze_and_optimize": _template_analyze_and_optimize,
    "troubleshoot": _template_troubleshoot,
    "build_and_deploy": _template_build_and_deploy,
    "investigate": _template_investigate,
    "security_audit": _template_security_audit,
}


# ---------------------------------------------------------------------------
# Workflow detection
# ---------------------------------------------------------------------------

def detect_workflow(user_input: str, intent: str) -> Optional[str]:
    """
    Detect if a user query maps to a multi-agent workflow template.

    Returns template name or None.
    """
    import re
    lower = user_input.lower()

    patterns = [
        (r'analyze.*(?:and|then).*(?:optimize|improve|fix)', "analyze_and_optimize"),
        (r'(?:optimize|improve).*(?:and|then).*(?:validate|check|test)', "analyze_and_optimize"),
        (r'(?:troubleshoot|debug|diagnose|fix).*(?:why|not working|failing|issue|problem)', "troubleshoot"),
        (r'(?:create|build|set up|configure).*(?:and|then).*(?:deploy|validate|test)', "build_and_deploy"),
        (r'(?:investigate|research|find out|look into)', "investigate"),
        (r'(?:security|audit|vulnerability|compliance|scan)', "security_audit"),
        (r'(?:compare|diff).*(?:and|then).*(?:fix|update|optimize)', "analyze_and_optimize"),
    ]

    for pattern, template_name in patterns:
        if re.search(pattern, lower):
            return template_name

    # Intent-based fallback
    intent_templates = {
        Intent.TROUBLESHOOTING: "troubleshoot",
        Intent.CONFIG_HEALTH_CHECK: "security_audit",
    }
    if intent in intent_templates:
        # Only use for complex queries (50+ chars)
        if len(user_input) > 50:
            return intent_templates[intent]

    return None


def _is_multi_step_query(user_input: str) -> bool:
    """Heuristic: does this query benefit from multi-step planning?"""
    import re
    lower = user_input.lower()
    word_count = len(lower.split())
    if word_count < 12:
        return False
    multi_step_signals = [
        r'\b(?:and then|after that|next|finally|first|second|third)\b',
        r'\b(?:step\s*\d|multi.?step|workflow|pipeline|sequence)\b',
        r'\b(?:for each|across all|every)\b',
    ]
    signal_count = sum(1 for p in multi_step_signals if re.search(p, lower))
    # Need at least 20 words and 1 signal, or 30+ words
    return (word_count >= 20 and signal_count >= 1) or word_count >= 35


_LLM_PLAN_PROMPT_TEMPLATE = (
    "You are a workflow planner for a Splunk/Observability assistant. "
    "Given a user request, break it into 2-5 sequential tasks.\n\n"
    "Each task must have:\n"
    "- description: what to do\n"
    "- intent: one of [spl_generation, spl_optimization, troubleshooting, config_lookup, "
    "config_health_check, general_qa, saved_search_analysis, "
    "cribl_pipeline, cribl_config, observability_metrics, observability_infra, "
    "ansible, shell_script, python_script, "
    "create_alert, data_transform, ingestion, compare_commands, repo_query, run_search, "
    "search_suggestion, meta_question]\n"
    "- department: one of [engineering, operations, data, infrastructure, knowledge, security, support]\n"
    "- depends_on: list of task indices (0-based) this task depends on\n\n"
    'Respond ONLY with valid JSON like: '
    '{{"description": "Plan summary", "tasks": [{{"description": "...", "intent": "...", "department": "...", "depends_on": []}}]}}\n\n'
    "User request: {user_input}"
)


def _parse_llm_plan_response(text: str) -> Optional[dict]:
    """Extract a plan dict from LLM response text.

    Tries JSON parsing first, then falls back to line-by-line extraction.
    """
    # --- Strategy 1: JSON block extraction ---
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return _json.loads(text[start:end])
        except _json.JSONDecodeError:
            pass

    # --- Strategy 2: line-by-line fallback for dash-prefixed task lists ---
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("- ")]
    if lines:
        tasks = []
        for ln in lines[:10]:
            desc = ln.lstrip("- ").strip()
            if desc:
                tasks.append({"description": desc, "intent": "general_qa", "department": "knowledge", "depends_on": []})
        if tasks:
            return {"description": "LLM-generated plan", "tasks": tasks}

    return None


def _build_validated_plan(
    plan_data: dict,
    user_input: str,
) -> Optional[WorkflowPlan]:
    """Build and validate a WorkflowPlan from parsed LLM JSON via Pydantic.

    Returns None if validation or capability checks fail.
    """
    # Lazy import so that test patches of chat_app.workflow_orchestrator.get_agent_catalog
    # are respected (validate_plan_capabilities is redefined in orchestrator using its
    # local get_agent_catalog binding).
    try:
        from chat_app.workflow_orchestrator import validate_plan_capabilities as _validate
    except ImportError:
        from chat_app.workflow_models import validate_plan_capabilities as _validate

    tasks_data = plan_data.get("tasks") or plan_data.get("steps") or []
    if not tasks_data:
        return None

    # Build ValidatedWorkflowStep list
    steps: List[ValidatedWorkflowStep] = []
    for i, td in enumerate(tasks_data[:10]):
        try:
            deps = [
                d for d in td.get("depends_on", [])
                if isinstance(d, int) and 0 <= d < i
            ]
            step = ValidatedWorkflowStep(
                description=td.get("description", f"Step {i + 1}"),
                intent=td.get("intent", "general_qa"),
                agent_name=td.get("agent_name", ""),
                preferred_department=td.get("department", td.get("preferred_department")),
                depends_on=deps,
                estimated_duration_seconds=td.get("estimated_duration_seconds", 30),
            )
            steps.append(step)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[ORCHESTRATOR] Skipping invalid step %d: %s", i, exc)
            continue

    if not steps:
        return None

    # Build ValidatedWorkflowPlan
    try:
        vplan = ValidatedWorkflowPlan(
            goal=plan_data.get("description", plan_data.get("goal", "LLM-generated plan")),
            description=plan_data.get("description", ""),
            steps=steps,
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ORCHESTRATOR] Plan schema validation failed: %s", exc)
        return None

    # Capability validation
    valid, errors = _validate(vplan)
    if not valid:
        logger.warning(
            "[ORCHESTRATOR] Plan failed capability validation: %s", "; ".join(errors)
        )
        return None

    # Flag plan-level approval if any step requires it
    if any(s.requires_approval for s in vplan.steps):
        vplan.requires_user_approval = True

    return _validated_plan_to_workflow(vplan, user_input)


async def llm_plan_workflow(user_input: str) -> Optional[WorkflowPlan]:
    """Use the LLM to generate a novel workflow plan for complex queries.

    The response is parsed (JSON-first, line-fallback) then validated via
    Pydantic schema checks *and* capability checks against the agent catalog.
    """
    try:
        import httpx
    except ImportError:
        logger.debug("[ORCHESTRATOR] httpx not available for LLM planning")
        return None

    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        base_url = settings.ollama.base_url
        model = settings.ollama.model

        prompt = _LLM_PLAN_PROMPT_TEMPLATE.format(user_input=user_input[:500])

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1}},
            )
            if resp.status_code != 200:
                logger.debug("[ORCHESTRATOR] LLM plan request failed: %d", resp.status_code)
                return None

            text = resp.json().get("response", "")

        plan_data = _parse_llm_plan_response(text)
        if plan_data is None:
            logger.debug("[ORCHESTRATOR] LLM plan response has no parseable plan")
            return None

        plan = _build_validated_plan(plan_data, user_input)
        if plan:
            logger.info(
                "[ORCHESTRATOR] LLM generated %d-step validated plan: %s",
                len(plan.tasks),
                plan.description,
            )
        return plan

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ORCHESTRATOR] LLM planning failed: %s", exc)
        return None
