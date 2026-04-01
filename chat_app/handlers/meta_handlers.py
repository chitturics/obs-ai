"""Meta/orchestration handlers — response generator, agent dispatch, workflow, writers.

Extracted from skill_executor.py (batches 5-6) for modularity.
Each handler follows: def handler(**kwargs) -> str

Exports HANDLERS dict for auto-registration.
"""
import logging

logger = logging.getLogger(__name__)


# --- Batch 5: Splunk Writer Handlers ---

def _handler_update_saved_search(user_input: str = "", **kwargs) -> str:
    """Update an existing Splunk saved search. Requires REVIEW approval."""
    try:
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient()
        name = kwargs.get("name") or user_input
        if not name:
            return "Error: saved search name is required"
        update_kwargs = {}
        if kwargs.get("search"):
            update_kwargs["search"] = kwargs["search"]
        if kwargs.get("description"):
            update_kwargs["description"] = kwargs["description"]
        if kwargs.get("cron_schedule"):
            update_kwargs["cron_schedule"] = kwargs["cron_schedule"]
        app = kwargs.get("app", "search")
        if not update_kwargs:
            return "Error: no fields to update. Provide search, description, or cron_schedule."
        result = sc.update_saved_search(name, app=app, **update_kwargs)
        changed = ", ".join(result["fields_changed"])
        return f"Updated saved search '{name}' (app={app}). Fields changed: {changed}"
    except Exception as exc:
        return f"Error updating saved search: {exc}"


def _handler_create_knowledge_object(user_input: str = "", **kwargs) -> str:
    """Create a Splunk knowledge object. Requires REVIEW approval."""
    try:
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient()
        obj_type = kwargs.get("object_type", "")
        name = kwargs.get("name", "")
        definition = kwargs.get("definition") or user_input
        if not obj_type or not name or not definition:
            return "Error: object_type, name, and definition are all required"
        app = kwargs.get("app", "search")
        result = sc.create_knowledge_object(obj_type, name, definition, app=app)
        return f"Created {result['type']} '{name}' in app={app}"
    except Exception as exc:
        return f"Error creating knowledge object: {exc}"


# --- Batch 6: Meta/orchestration handlers ---

def _handler_response_generator(**kwargs):
    """Generate a response using the LLM pipeline."""
    query = kwargs.get("input") or kwargs.get("user_input", "")
    if not query:
        return "No input provided for response generation."
    return f"[Response Generator] Processing query: {query[:200]}"


def _handler_clarification(**kwargs):
    """Handle clarification requests."""
    query = kwargs.get("input") or kwargs.get("user_input", "")
    return (
        "I'd like to help clarify. Could you provide more details about:\n"
        f"- What specific aspect of '{query[:100]}' you'd like to know?\n"
        "- Any relevant context (index, sourcetype, environment)?"
    )


def _handler_query_router(**kwargs):
    """Route a query to the appropriate handler."""
    query = kwargs.get("input") or kwargs.get("user_input", "")
    intent = kwargs.get("intent", "general_qa")
    return f"[Query Router] Routed intent={intent} for: {query[:200]}"


def _handler_run_splunk_search(**kwargs):
    """Execute a Splunk search (delegates to MCP if available)."""
    query = kwargs.get("query") or kwargs.get("input", "")
    if not query:
        return "No search query provided."
    try:
        from chat_app.mcp_handler import execute_mcp_tool
        result = execute_mcp_tool("splunk-mcp", "search", {"query": query})
        return result if result else f"Search submitted: {query[:200]}"
    except Exception as _exc:  # broad catch — resilience against all failures
        return f"[Splunk Search] Query prepared: {query[:200]}\n(MCP gateway not available — run via Splunk CLI)"


def _handler_analyze_cribl_pipeline(**kwargs):
    """Analyze a Cribl pipeline configuration."""
    query = kwargs.get("input") or kwargs.get("user_input", "")
    # Import the search handler from skill_handlers to avoid circular dependency
    from chat_app.handlers.skill_handlers import _handler_search_knowledge
    return _handler_search_knowledge(input=query, intent="cribl")


async def _handler_orchestrator(**kwargs):
    """Meta-handler: delegates to the real orchestration strategy engine."""
    user_input = kwargs.get("user_input") or kwargs.get("input", "")
    intent = kwargs.get("intent", "general_qa")
    if not user_input:
        return "[Orchestrator] No input provided."
    try:
        from chat_app.orchestration_strategies import execute_orchestration
        result = await execute_orchestration(
            user_input=user_input,
            intent=intent,
            plan=kwargs.get("plan"),
            context=kwargs.get("context"),
            user_approved=kwargs.get("user_approved", False),
        )
        return result.combined_output if hasattr(result, "combined_output") else str(result)
    except Exception as exc:
        logger.error("[SKILL_EXEC] Orchestrator delegation failed: %s", exc)
        return f"[Orchestrator] Execution failed: {exc}"


async def _handler_agent_dispatch(**kwargs):
    """Meta-handler: delegates to the real agent dispatcher."""
    user_input = kwargs.get("user_input") or kwargs.get("input", "")
    intent = kwargs.get("intent", "general_qa")
    if not user_input:
        return "[Agent Dispatch] No input provided."
    try:
        from chat_app.agent_dispatcher import get_agent_dispatcher
        dispatcher = get_agent_dispatcher()
        result = await dispatcher.dispatch(
            user_input=user_input,
            intent=intent,
            params=kwargs,
            user_approved=kwargs.get("user_approved", False),
        )
        if result.success and result.enriched_context:
            return result.enriched_context
        return result.error or "[Agent Dispatch] No output produced."
    except Exception as exc:
        logger.error("[SKILL_EXEC] Agent dispatch delegation failed: %s", exc)
        return f"[Agent Dispatch] Execution failed: {exc}"


async def _handler_workflow_orchestrator(**kwargs):
    """Meta-handler: delegates to the real workflow orchestrator."""
    user_input = kwargs.get("user_input") or kwargs.get("input", "")
    intent = kwargs.get("intent", "general_qa")
    if not user_input:
        return "[Workflow] No input provided."
    try:
        from chat_app.workflow_orchestrator import get_workflow_orchestrator
        orchestrator = get_workflow_orchestrator()
        result = await orchestrator.run(
            user_input=user_input,
            intent=intent,
            template_name=kwargs.get("template_name"),
            user_approved=kwargs.get("user_approved", False),
        )
        if result is None:
            return "[Workflow] No multi-step workflow applicable for this query."
        return result.combined_output if result.combined_output else "[Workflow] Completed with no output."
    except Exception as exc:
        logger.error("[SKILL_EXEC] Workflow orchestration failed: %s", exc)
        return f"[Workflow] Execution failed: {exc}"


def _handler_direct_execution(**kwargs):
    """Direct execution of a tool or command."""
    query = kwargs.get("input") or kwargs.get("user_input", "")
    return f"[Direct Execution] Prepared for: {query[:200]}"


def _handler_idle_worker(**kwargs):
    """Get idle worker status."""
    try:
        from chat_app.idle_worker import get_idle_worker
        worker = get_idle_worker()
        return f"Idle worker active: {worker.is_running if hasattr(worker, 'is_running') else 'unknown'}"
    except Exception as _exc:  # broad catch — resilience against all failures
        return "[Idle Worker] Background worker status check."


HANDLERS = {
    # Batch 5: Splunk Writer Handlers
    "update_saved_search": _handler_update_saved_search,
    "create_knowledge_object": _handler_create_knowledge_object,
    # Batch 6: Meta/orchestration handlers
    "response_generator": _handler_response_generator,
    "clarification": _handler_clarification,
    "query_router": _handler_query_router,
    "run_splunk_search": _handler_run_splunk_search,
    "analyze_cribl_pipeline": _handler_analyze_cribl_pipeline,
    "orchestrator": _handler_orchestrator,
    "agent_dispatch": _handler_agent_dispatch,
    "workflow_orchestrator": _handler_workflow_orchestrator,
    "direct_execution": _handler_direct_execution,
    "idle_worker": _handler_idle_worker,
}
