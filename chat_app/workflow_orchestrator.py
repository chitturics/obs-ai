"""
Workflow Orchestrator — Multi-agent coordination for complex tasks.

Handles tasks that require multiple agents working together:
- Breaks complex goals into sub-tasks
- Assigns sub-tasks to the best agent for each
- Manages dependencies between sub-tasks
- Aggregates results into a coherent output
- Tracks workflow progress and provides status updates

Example workflow:
    "Analyze my saved searches and optimize the slow ones"
    → Sub-task 1: reader agent → list and parse saved searches
    → Sub-task 2: tester agent → analyze each for performance issues
    → Sub-task 3: coder agent → generate optimized versions
    → Aggregate → Final report with before/after comparisons

Data models, Pydantic validation, and constants are in workflow_models.py.
Workflow templates and LLM planning are in workflow_templates.py.
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from chat_app.agent_catalog import get_agent_catalog  # noqa: F401 — re-exported for test patching
from chat_app.agent_dispatcher import (
    AgentDispatchResult,
    AgentDispatcher,
    get_agent_dispatcher,
)
from chat_app.workflow_persistence import WorkflowPersistenceMixin

# Models (re-exported for backward compatibility)
from chat_app.workflow_models import (  # noqa: F401
    APPROVAL_REQUIRED_INTENTS,
    TASK_MAX_RETRIES,
    TASK_RETRY_DELAY_SECONDS,
    WORKFLOW_TIMEOUT_SECONDS,
    TaskStatus,
    ValidatedWorkflowPlan,
    ValidatedWorkflowStep,
    WorkflowPlan,
    WorkflowResult,
    WorkflowTask,
    _validated_plan_to_workflow,
    validate_plan_capabilities as _wm_validate_plan_capabilities,
)

# Templates (re-exported for backward compatibility)
from chat_app.workflow_templates import (  # noqa: F401
    WORKFLOW_TEMPLATES,
    _build_validated_plan,
    _is_multi_step_query,
    _LLM_PLAN_PROMPT_TEMPLATE,
    _parse_llm_plan_response,
    _template_analyze_and_optimize,
    _template_build_and_deploy,
    _template_investigate,
    _template_security_audit,
    _template_troubleshoot,
    detect_workflow,
    llm_plan_workflow,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# validate_plan_capabilities — wrapper so tests can patch get_agent_catalog
# at chat_app.workflow_orchestrator.get_agent_catalog (the local binding).
# Implementation lives in workflow_models.validate_plan_capabilities.
# ---------------------------------------------------------------------------

def validate_plan_capabilities(
    plan: ValidatedWorkflowPlan,
) -> Tuple[bool, List[str]]:
    """Validate plan capabilities using the locally-patchable get_agent_catalog."""
    return _wm_validate_plan_capabilities(plan, _catalog_factory=get_agent_catalog)


# ---------------------------------------------------------------------------
# Database engine helper
# ---------------------------------------------------------------------------

_db_engine_singleton = None


def _get_db_engine():
    """Get shared async SQLAlchemy engine, or None if unavailable."""
    global _db_engine_singleton
    if _db_engine_singleton is not None:
        return _db_engine_singleton
    try:
        from chat_app.settings import get_settings
        app_settings = get_settings()
        db_settings = getattr(app_settings, 'database', None)
        if db_settings and hasattr(db_settings, 'url') and db_settings.url:
            url = db_settings.url.replace("postgresql://", "postgresql+asyncpg://")
            from sqlalchemy.ext.asyncio import create_async_engine
            _db_engine_singleton = create_async_engine(url, pool_pre_ping=True, pool_size=2)
            return _db_engine_singleton
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)
    return None


# ---------------------------------------------------------------------------
# Workflow Orchestrator
# ---------------------------------------------------------------------------

class WorkflowOrchestrator(WorkflowPersistenceMixin):
    """
    Orchestrates multi-agent workflows for complex tasks.

    Persistence methods (_save_state, get_persisted_workflows, recover_interrupted,
    pause_workflow, resume_workflow) are provided by WorkflowPersistenceMixin
    (workflow_persistence.py).

    Flow:
    1. Detect if the query needs a multi-agent workflow
    2. Select or build a workflow plan
    3. Execute tasks in dependency order
    4. Aggregate results
    """

    def __init__(self, dispatcher: Optional[AgentDispatcher] = None):
        self._dispatcher = dispatcher or get_agent_dispatcher()
        self._active_workflows: Dict[str, WorkflowPlan] = {}
        self._completed_workflows: List[WorkflowResult] = []

    @staticmethod
    def _flag_approval_on_plan(plan: WorkflowPlan) -> WorkflowPlan:
        """Set requires_approval on a plan if any task uses a dangerous intent."""
        for task in plan.tasks:
            if task.intent in APPROVAL_REQUIRED_INTENTS:
                plan.requires_approval = True
                return plan
        return plan

    def create_plan(
        self,
        user_input: str,
        intent: str,
        template_name: Optional[str] = None,
    ) -> Optional[WorkflowPlan]:
        """
        Create a workflow plan from a template or auto-detect.

        Returns None if no workflow is needed (single-agent query).
        Template-generated plans are also checked for approval requirements.
        """
        plan: Optional[WorkflowPlan] = None
        if template_name and template_name in WORKFLOW_TEMPLATES:
            plan = WORKFLOW_TEMPLATES[template_name](user_input)

        if plan is None:
            # Auto-detect via regex patterns
            detected = detect_workflow(user_input, intent)
            if detected and detected in WORKFLOW_TEMPLATES:
                plan = WORKFLOW_TEMPLATES[detected](user_input)

        if plan is not None:
            return self._flag_approval_on_plan(plan)

        # Flag for LLM planning if query looks multi-step
        if _is_multi_step_query(user_input):
            self._pending_llm_plan = user_input
        else:
            self._pending_llm_plan = None

        return None

    async def create_plan_async(
        self,
        user_input: str,
        intent: str,
        template_name: Optional[str] = None,
    ) -> Optional[WorkflowPlan]:
        """
        Like create_plan but with async LLM fallback for complex queries.

        Tries regex-based detection first, then falls back to LLM-generated plans.
        """
        # Try sync detection first
        plan = self.create_plan(user_input, intent, template_name)
        if plan:
            return plan

        # LLM fallback for multi-step queries
        if _is_multi_step_query(user_input):
            return await llm_plan_workflow(user_input)

        return None

    async def execute_workflow(
        self,
        plan: WorkflowPlan,
        user_input: str,
        user_approved: bool = False,
    ) -> WorkflowResult:
        """
        Execute a workflow plan by running tasks in dependency order.

        Tasks with no dependencies run in parallel.
        Tasks with dependencies wait for their prerequisites.

        If the plan contains steps that require user approval (dangerous
        intents like run_search, ansible, shell_script) and *user_approved*
        is ``False``, the workflow is returned immediately in a
        ``waiting_approval`` state rather than executed.
        """
        # --- Approval gate ---------------------------------------------------
        if plan.requires_approval and not user_approved:
            approval_intents = [
                t.intent for t in plan.tasks if t.intent in APPROVAL_REQUIRED_INTENTS
            ]
            logger.info(
                "[ORCHESTRATOR] Plan requires approval for intents %s — "
                "returning waiting_approval result",
                approval_intents,
            )
            return WorkflowResult(
                plan_description=plan.description,
                tasks_completed=0,
                tasks_failed=0,
                tasks_total=plan.total_tasks,
                combined_output=(
                    "This workflow contains steps that require your approval before "
                    "execution (intents: " + ", ".join(sorted(set(approval_intents)))
                    + "). Please confirm to proceed."
                ),
                agent_trace=[],
                duration_ms=0.0,
                success=False,
            )

        start = time.monotonic()
        workflow_id = f"wf_{int(time.time())}"
        self._active_workflows[workflow_id] = plan
        agent_trace = []

        # Persist initial state
        await self._save_state(workflow_id, plan, "running")

        try:
            deadline = time.monotonic() + WORKFLOW_TIMEOUT_SECONDS
            while True:
                # Enforce workflow-level timeout
                if time.monotonic() > deadline:
                    logger.error(
                        f"[ORCHESTRATOR] Workflow {workflow_id} timed out after "
                        f"{WORKFLOW_TIMEOUT_SECONDS}s"
                    )
                    for t in plan.tasks:
                        if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                            t.status = TaskStatus.FAILED
                            t.error = "Workflow timeout exceeded"
                    break

                ready = plan.get_ready_tasks()
                if not ready:
                    break

                # Execute ready tasks (potentially in parallel)
                if len(ready) == 1:
                    await self._execute_task(ready[0], user_input, agent_trace, user_approved)
                else:
                    # Parallel execution for independent tasks
                    await asyncio.gather(
                        *(self._execute_task(t, user_input, agent_trace, user_approved) for t in ready)
                    )

                # Persist progress after each batch
                await self._save_state(workflow_id, plan, "running")

                # Check if we're stuck (no progress)
                if not any(t.status == TaskStatus.PENDING for t in plan.tasks):
                    break

        finally:
            self._active_workflows.pop(workflow_id, None)

        # Combine results
        output_parts = []
        for task in plan.tasks:
            if task.status == TaskStatus.COMPLETED and task.output:
                output_parts.append(
                    f"### Step {task.id + 1}: {task.description}\n{task.output}"
                )
            elif task.status == TaskStatus.FAILED:
                output_parts.append(
                    f"### Step {task.id + 1}: {task.description}\n"
                    f"*Failed: {task.error or 'Unknown error'}*"
                )

        duration_ms = (time.monotonic() - start) * 1000
        result = WorkflowResult(
            plan_description=plan.description,
            tasks_completed=plan.completed_tasks,
            tasks_failed=plan.failed_tasks,
            tasks_total=plan.total_tasks,
            combined_output="\n\n".join(output_parts),
            agent_trace=agent_trace,
            duration_ms=duration_ms,
            success=plan.failed_tasks == 0,
        )

        self._completed_workflows.append(result)
        if len(self._completed_workflows) > 50:
            self._completed_workflows = self._completed_workflows[-50:]

        # Persist final state
        final_status = "completed" if result.success else "failed"
        await self._save_state(workflow_id, plan, final_status, error=result.combined_output[:500] if not result.success else "")

        logger.info(
            f"[ORCHESTRATOR] Workflow complete: {plan.completed_tasks}/{plan.total_tasks} tasks, "
            f"{duration_ms:.0f}ms"
        )
        return result

    async def _execute_task(
        self,
        task: WorkflowTask,
        user_input: str,
        agent_trace: List[Dict[str, Any]],
        user_approved: bool = False,
    ):
        """Execute a single workflow task with retry and fallback."""

        task.status = TaskStatus.RUNNING
        start = time.monotonic()
        last_error = None

        for attempt in range(1 + TASK_MAX_RETRIES):
            try:
                dep_context = self._get_dependency_context(task)
                params = {**task.params}
                if dep_context:
                    params["prior_context"] = dep_context

                dispatch_result = await self._dispatcher.dispatch(
                    user_input=params.get("user_input", user_input),
                    intent=task.intent,
                    params=params,
                    preferred_department=task.preferred_department,
                    user_approved=user_approved,
                )

                task.result = dispatch_result
                task.agent_name = dispatch_result.agent_name
                task.duration_ms = (time.monotonic() - start) * 1000

                if dispatch_result.success:
                    task.status = TaskStatus.COMPLETED
                    break
                elif any(
                    getattr(r, "approval_required", False)
                    for r in dispatch_result.skill_results
                ):
                    task.status = TaskStatus.FAILED
                    task.error = "Skill requires user approval before execution"
                    logger.warning(
                        f"[ORCHESTRATOR] Task {task.id} blocked: approval required"
                    )
                    break  # Don't retry approval-blocked tasks
                else:
                    last_error = dispatch_result.error
                    if attempt < TASK_MAX_RETRIES:
                        task.retry_count = attempt + 1
                        logger.info(
                            f"[ORCHESTRATOR] Task {task.id} failed (attempt {attempt + 1}), "
                            f"retrying in {TASK_RETRY_DELAY_SECONDS}s: {last_error}"
                        )
                        await asyncio.sleep(TASK_RETRY_DELAY_SECONDS * (attempt + 1))
                    else:
                        # All retries exhausted — try fallback intent
                        fallback_result = await self._try_fallback(
                            task, user_input, params, user_approved
                        )
                        if fallback_result:
                            task.result = fallback_result
                            task.agent_name = fallback_result.agent_name
                            task.status = TaskStatus.COMPLETED
                            task.duration_ms = (time.monotonic() - start) * 1000
                            logger.info(
                                f"[ORCHESTRATOR] Task {task.id} recovered via fallback "
                                f"(intent={task.intent} -> general_qa)"
                            )
                        else:
                            task.status = TaskStatus.FAILED
                            task.error = last_error

            except Exception as exc:  # Broad catch intentional: task handlers may raise any type
                last_error = str(exc)
                if attempt < TASK_MAX_RETRIES:
                    task.retry_count = attempt + 1
                    logger.info(
                        f"[ORCHESTRATOR] Task {task.id} exception (attempt {attempt + 1}), retrying: {exc}"
                    )
                    await asyncio.sleep(TASK_RETRY_DELAY_SECONDS * (attempt + 1))
                else:
                    task.status = TaskStatus.FAILED
                    task.error = last_error
                    task.duration_ms = (time.monotonic() - start) * 1000
                    logger.error(f"[ORCHESTRATOR] Task {task.id} failed after {TASK_MAX_RETRIES} retries: {exc}")

        agent_trace.append({
            "task_id": task.id,
            "description": task.description,
            "agent": task.agent_name,
            "skills": task.result.skills_executed if task.result else [],
            "success": task.status == TaskStatus.COMPLETED,
            "retries": task.retry_count,
            "duration_ms": round(task.duration_ms, 2),
        })

        # --- Enterprise: Audit log + activity timeline for workflow tasks ---
        try:
            from chat_app.audit_log import get_audit_log
            get_audit_log().append(
                event_type="workflow_task",
                actor=task.agent_name or "workflow_orchestrator",
                action="execute_task",
                target=task.id,
                details={
                    "intent": task.intent if isinstance(task.intent, str) else task.intent.value,
                    "agent": task.agent_name,
                    "success": task.status == TaskStatus.COMPLETED,
                    "retries": task.retry_count,
                    "duration_ms": round(task.duration_ms, 1),
                    "error": task.error,
                },
                severity="medium" if task.status == TaskStatus.COMPLETED else "high",
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)

    async def _try_fallback(
        self,
        task: WorkflowTask,
        user_input: str,
        params: Dict[str, Any],
        user_approved: bool,
    ) -> Optional[AgentDispatchResult]:
        """Attempt a fallback dispatch with general_qa intent."""
        from chat_app.registry import Intent
        if task.intent == Intent.GENERAL_QA:
            return None  # Already the broadest intent
        try:
            result = await self._dispatcher.dispatch(
                user_input=params.get("user_input", user_input),
                intent=Intent.GENERAL_QA,
                params=params,
                user_approved=user_approved,
            )
            if result.success:
                return result
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, StopIteration, StopAsyncIteration) as exc:
            logger.debug(f"[ORCHESTRATOR] Fallback also failed for task {task.id}: {exc}")
        return None

    def _get_dependency_context(self, task: WorkflowTask) -> str:
        """Get combined output from dependency tasks."""
        parts = []
        plan = None
        # Find the plan containing this task
        for wf_plan in self._active_workflows.values():
            if task in wf_plan.tasks:
                plan = wf_plan
                break
        if not plan:
            return ""

        for dep_id in task.depends_on:
            for t in plan.tasks:
                if t.id == dep_id and t.status == TaskStatus.COMPLETED and t.output:
                    parts.append(t.output)
        return "\n\n".join(parts)

    async def run(
        self,
        user_input: str,
        intent: str,
        template_name: Optional[str] = None,
        user_approved: bool = False,
    ) -> Optional[WorkflowResult]:
        """
        Convenience method: detect workflow, create plan, and execute.

        Uses async planning with LLM fallback for complex queries.
        Returns None if no workflow is applicable.
        """
        plan = await self.create_plan_async(user_input, intent, template_name)
        if not plan:
            return None
        return await self.execute_workflow(plan, user_input, user_approved=user_approved)

    def get_active_workflows(self) -> List[Dict[str, Any]]:
        """Get currently active workflows."""
        return [
            {
                "id": wf_id,
                "description": plan.description,
                "progress": plan.progress_pct,
                "total_tasks": plan.total_tasks,
                "completed_tasks": plan.completed_tasks,
            }
            for wf_id, plan in self._active_workflows.items()
        ]

    def get_completed_workflows(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recently completed workflows."""
        return [r.to_dict() for r in self._completed_workflows[-limit:]]

    # Persistence methods (_save_state, get_persisted_workflows, recover_interrupted,
    # pause_workflow, resume_workflow) are provided by WorkflowPersistenceMixin.

    def get_summary(self) -> Dict[str, Any]:
        """Get orchestrator summary."""
        total = len(self._completed_workflows)
        successes = sum(1 for r in self._completed_workflows if r.success)
        paused = sum(
            1 for p in self._active_workflows.values()
            if any(t.status in (TaskStatus.PAUSED, TaskStatus.WAITING_INPUT, TaskStatus.WAITING_APPROVAL) for t in p.tasks)
        )
        return {
            "active_workflows": len(self._active_workflows),
            "paused_workflows": paused,
            "completed_workflows": total,
            "success_rate": round(successes / max(total, 1), 4),
            "templates_available": list(WORKFLOW_TEMPLATES.keys()),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_orchestrator: Optional[WorkflowOrchestrator] = None


def get_workflow_orchestrator() -> WorkflowOrchestrator:
    """Get or create the singleton WorkflowOrchestrator."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = WorkflowOrchestrator()
    return _orchestrator
