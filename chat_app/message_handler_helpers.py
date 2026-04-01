"""Message handler helper functions — extracted from message_handler.py.

Contains: query preprocessing utilities, direct intent handler, task list
helpers, the AIAttributes class used for OTel tracing, and pipeline setup
helpers (_prepare_request, _route_and_track) that encapsulate the
pre-retrieval setup phase of on_message.
"""
import re
import dataclasses
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

import chainlit as cl

from chat_app.registry import Intent
from chat_app.pipeline_lineage import init_trace, record_stage, finalize_trace
from chat_app.schemas import PipelineStage
from prometheus_metrics import record_query
from shared.spl_query_optimizer import SPLQueryOptimizer

if TYPE_CHECKING:
    from query_router import QueryPlan
    from chat_app.message_context import MessageHandlerContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OTel AIAttributes (inline fallback when otel_tracing is unavailable)
# ---------------------------------------------------------------------------

class AIAttributes:
    LLM_MODEL = "gen_ai.request.model"
    LLM_RESPONSE_CHARS = "gen_ai.response.chars"
    RAG_CHUNKS_RETRIEVED = "rag.chunks.retrieved"
    RAG_SOURCE = "rag.source"
    RAG_CACHE_HIT = "rag.cache_hit"
    RAG_MODE = "rag.mode"
    AGENT_NAME = "agent.name"
    AGENT_STRATEGY = "agent.strategy"
    AGENT_ITERATIONS = "agent.iterations"
    AGENT_QUALITY = "agent.quality_score"
    PIPELINE_INTENT = "pipeline.intent"
    PIPELINE_PROFILE = "pipeline.profile"
    PIPELINE_REQUEST_ID = "pipeline.request_id"
    PIPELINE_DURATION_MS = "pipeline.duration_ms"
    PIPELINE_SUCCESS = "pipeline.success"
    PIPELINE_USER_QUERY = "pipeline.user_query"
    QUALITY_SCORE = "quality.score"
    QUALITY_CONFIDENCE = "quality.confidence"
    USER_ID = "user.id"
    SESSION_ID = "session.id"


# ---------------------------------------------------------------------------
# Intent-to-task-title mapping (used by TaskList in on_message)
# ---------------------------------------------------------------------------

INTENT_TASK_TITLES: Dict[Any, str] = {
    Intent.SPL_GENERATION: "Understanding your SPL request...",
    Intent.SPL_OPTIMIZATION: "Preparing to optimize your query...",
    Intent.TROUBLESHOOTING: "Diagnosing the issue...",
    Intent.CONFIG_LOOKUP: "Looking up configuration details...",
    Intent.GENERAL_QA: "Researching your question...",
    Intent.CONFIG_HEALTH_CHECK: "Running configuration health check...",
    Intent.INGESTION: "Preparing to ingest data...",
    Intent.CRIBL_PIPELINE: "Looking into Cribl details...",
    Intent.CRIBL_CONFIG: "Looking into Cribl configuration...",
    Intent.OBSERVABILITY_METRICS: "Gathering observability context...",
    Intent.OBSERVABILITY_INFRA: "Analyzing infrastructure...",
    Intent.DATA_TRANSFORM: "Transforming your data...",
    Intent.ANSIBLE: "Generating Ansible playbook...",
    Intent.SHELL_SCRIPT: "Writing shell script...",
    Intent.PYTHON_SCRIPT: "Writing Python script...",
    Intent.SAVED_SEARCH_ANALYSIS: "Analyzing saved searches...",
    Intent.RUN_SEARCH: "Executing search...",
    Intent.CREATE_ALERT: "Setting up alert...",
}

# Intent-to-acknowledgment-verb mapping (used for long queries)
INTENT_ACK_LABELS: Dict[Any, str] = {
    Intent.SPL_GENERATION: "writing SPL",
    Intent.SPL_OPTIMIZATION: "optimizing your query",
    Intent.TROUBLESHOOTING: "troubleshooting",
    Intent.CONFIG_LOOKUP: "looking up configuration",
    Intent.GENERAL_QA: "answering your question",
    Intent.CRIBL_PIPELINE: "looking into Cribl details",
    Intent.CRIBL_CONFIG: "looking into Cribl configuration",
    Intent.CONFIG_HEALTH_CHECK: "checking configuration health",
    Intent.OBSERVABILITY_METRICS: "gathering observability metrics",
    Intent.DATA_TRANSFORM: "transforming your data",
}


# ---------------------------------------------------------------------------
# Query preprocessing utilities
# ---------------------------------------------------------------------------

def _run_local_optimizer(query: str) -> Any:
    """Run the local SPL optimizer and return the OptimizedQuery object directly.
    The _format_optimizer_bypass_response() handles both dict and OptimizedQuery."""
    result = SPLQueryOptimizer.optimize(query)
    return result


def _is_pronoun_heavy(user_input: str) -> bool:
    """Detect if the input relies on pronouns/references without enough context."""
    lower = user_input.lower().strip()
    pronoun_patterns = [
        r'^(optimize|improve|fix|review|explain|analyze)\s+(that|it|this|the query|the search)\s*$',
        r'^what about\s+',
        r'^(and|also|plus)\s+',
        r'^(same|similar)\s+(but|for|with)\s+',
        r'^(do|try|run)\s+(that|it|this)\s+(again|too|as well)\s*$',
    ]
    return any(re.match(p, lower) for p in pronoun_patterns)


def _simplify_query_for_retrieval(user_input: str) -> str:
    """Simplify a user query by stripping SPL syntax and filler words
    to get core semantic terms for better vector search.

    Example: "optimize index=main sourcetype=access_combined | stats count by status"
          -> "optimize access combined stats count status"
    """
    text = user_input.strip()
    text = re.sub(r'\|\s*\w+', ' ', text)
    text = re.sub(r'\b(index|sourcetype|source|host)\s*=\s*\S+', ' ', text)
    text = re.sub(r'\b(earliest|latest)\s*=\s*\S+', ' ', text)
    text = re.sub(r'[|=\[\]{}()"\'`]', ' ', text)
    text = re.sub(r'\b(by|as|where|OR|AND|NOT)\b', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text.split()) >= 2:
        return text
    return user_input


# ---------------------------------------------------------------------------
# Direct intent handler (bypasses full RAG pipeline)
# ---------------------------------------------------------------------------

async def _handle_direct_intent(
    plan: "QueryPlan",
    user_input: str,
    context: "MessageHandlerContext",
    current_profile: str,
) -> bool:
    """Handle intents that bypass the main RAG pipeline.

    Returns True if the intent was handled (caller should return), False otherwise.
    """
    if plan.intent == Intent.SEARCH_SUGGESTION:
        from shared.spl_robust_analyzer import suggest_search
        suggested_query = suggest_search(user_input)
        await cl.Message(content=f"Here is a suggested search for you:\n\n```spl\n{suggested_query}\n```").send()
        return True

    # Handle intents that bypass the full retrieval/LLM pipeline
    from chat_app.intent_handler import handle_intent
    if await handle_intent(plan, user_input, context):
        return True

    # For meta_question intent, use LLM directly without retrieval context
    if plan.intent == Intent.META_QUESTION and plan.skip_retrieval:
        import time as _time_mod
        _meta_start = _time_mod.monotonic()

        _trace = init_trace(user_input=user_input, intent="meta_question", profile=current_profile)
        record_stage(PipelineStage.ROUTING, duration_ms=0, success=True,
                     metadata={"intent": "meta_question", "path": "direct"})

        concise_prompt = (
            "Answer the following question concisely and directly. "
            "Do NOT include any SPL queries, code blocks, or optimization notes "
            "unless the user specifically asks for them. Keep it to 2-4 sentences.\n\n"
            f"Question: {user_input}"
        )
        result_text = ""
        _llm_start = _time_mod.monotonic()
        try:
            response = await context.llm.ainvoke(concise_prompt)
            result_text = response.content if hasattr(response, "content") else str(response)
            _llm_ms = int((_time_mod.monotonic() - _llm_start) * 1000)
            record_stage(PipelineStage.LLM_INFERENCE, duration_ms=_llm_ms, success=True,
                         metadata={"chars": len(result_text), "method": "direct_invoke"})
            await cl.Message(content=result_text.strip()).send()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            _llm_ms = int((_time_mod.monotonic() - _llm_start) * 1000)
            logger.error("[META] llm_failed ms=%d error=%s", _llm_ms, exc)
            record_stage(PipelineStage.LLM_INFERENCE, duration_ms=_llm_ms, success=False,
                         metadata={"error": str(exc)[:200]})
            await cl.Message(
                content="I'm sorry, the LLM service is currently unavailable. "
                "Please check that Ollama is running and the model is loaded."
            ).send()

        _total_ms = int((_time_mod.monotonic() - _meta_start) * 1000)
        logger.info("[DIRECT] intent=meta_question ms=%d chars=%d rid=direct", _total_ms, len(result_text))
        finalize_trace(strategy_used="direct", quality_score=0.0)

        if result_text:
            cl.user_session.set("last_question", user_input)
            cl.user_session.set("last_answer", result_text)
            cl.user_session.set("last_context", "")
        record_query(intent=Intent.META_QUESTION, profile=current_profile, latency=_total_ms / 1000.0)
        return True

    if plan.intent == Intent.CLARIFICATION and plan.clarification_question:
        await cl.Message(content=plan.clarification_question).send()
        record_query(intent=Intent.CLARIFICATION, profile=current_profile, latency=0)
        return True

    return False


# ---------------------------------------------------------------------------
# TaskList helpers (used inside on_message to show pipeline progress)
# ---------------------------------------------------------------------------

async def task_done(task_list: Any, task: Any, new_title: Optional[str] = None) -> None:
    """Mark a task as done and update the list."""
    if task_list is None or task is None:
        return
    try:
        task.status = cl.TaskStatus.DONE
        if new_title:
            task.title = new_title
        await task_list.send()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[%s] %%s", "message_handler_helpers.py", _exc)


async def task_add(task_list: Any, title: str) -> Optional[Any]:
    """Add a new running task to the list and return it."""
    if task_list is None:
        return None
    try:
        task = cl.Task(title=title, status=cl.TaskStatus.RUNNING)
        await task_list.add_task(task)
        await task_list.send()
        return task
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        return None


async def task_list_done(task_list: Any, status: str = "Done") -> None:
    """Mark task list as complete and remove it."""
    if task_list is None:
        return
    try:
        task_list.status = status
        await task_list.send()
        await task_list.remove()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[task_list_done] %s", _exc)


# ---------------------------------------------------------------------------
# Pre-retrieval pipeline setup helpers
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class RequestSetup:
    """Values computed during the pre-routing setup phase of on_message."""
    user_input: str
    username: str
    thread_id: str
    request_id: Optional[str]
    otel_root_span: Any
    otel_ctx_token: Any
    resolution_notice: Optional[str]
    user_context_note: Optional[str]
    latency: Any  # LatencyTracker


async def prepare_request(
    message: Any,
    context: Any,
    guardrail_check_input: Any,
    ai_attributes_cls: Any,
) -> Optional["RequestSetup"]:
    """Handle pre-routing setup: OTel span, input sanitization, guardrails, pronoun resolution.

    Returns RequestSetup on success, or None if the request was blocked/handled.
    The caller should return immediately if None is returned.
    """
    from helper import current_username, current_thread_id
    from chat_app.logging_utils import set_request_context, LatencyTracker

    _username = current_username()
    _thread = current_thread_id()
    _request_id = set_request_context(user_id=_username, session_id=_thread)
    _latency = LatencyTracker()

    try:
        from chat_app.cost_tracker import set_cost_context
        set_cost_context(user_id=_username or "", session_id=_thread or "", request_id=_request_id or "")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[prepare_request] cost_context: %s", _exc)

    # OTel root span
    _otel_root_span = None
    _otel_ctx_token = None
    try:
        _otel_tracer = None
        try:
            from chat_app.otel_tracing import get_tracer as _get_otel_tracer
            _otel_tracer = _get_otel_tracer()
        except ImportError:
            pass
        if _otel_tracer is not None:
            from opentelemetry import trace as _otel_trace
            _otel_root_span = _otel_tracer.start_span(
                "pipeline.on_message",
                kind=_otel_trace.SpanKind.SERVER,
                attributes={
                    ai_attributes_cls.USER_ID: _username or "anonymous",
                    ai_attributes_cls.SESSION_ID: _thread or "",
                    ai_attributes_cls.PIPELINE_REQUEST_ID: _request_id or "",
                },
            )
            _otel_ctx_token = _otel_trace.context_api.attach(
                _otel_trace.set_span_in_context(_otel_root_span)
            )
    except Exception:  # broad catch — resilience at boundary
        _otel_root_span = None

    # Input sanitization
    user_input = (message.content or "").strip()
    _MAX_INPUT_LEN = 4000
    if len(user_input) > _MAX_INPUT_LEN:
        user_input = user_input[:_MAX_INPUT_LEN]
    user_input = "".join(ch for ch in user_input if ch == "\n" or (ord(ch) >= 32))
    logger.info("[MESSAGE] query=%r len=%d rid=%s", user_input[:120], len(user_input), _request_id)

    if _otel_root_span is not None:
        try:
            _otel_root_span.set_attribute(ai_attributes_cls.PIPELINE_USER_QUERY, user_input[:500])
        except Exception:  # broad catch — resilience at boundary
            pass

    # Guardrail: input safety check
    try:
        _gr = guardrail_check_input(user_input)
        if _gr.blocked:
            logger.warning("[GUARD] input_blocked warnings=%s rid=%s", _gr.warnings, _request_id)
            await cl.Message(
                content="I'm unable to process this request. "
                "It was flagged by our safety system. "
                "Please rephrase your question."
            ).send()
            return None
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[prepare_request] guardrail: %s", _exc)

    # Pronoun resolution
    _latency.start("pronoun_resolve")
    _resolution_notice = None
    try:
        from chat_app.conversation_memory import resolve_references
        resolved = resolve_references(user_input)
        if resolved != user_input:
            _resolution_notice = f"*I understood \"{user_input}\" as: \"{resolved[:120]}\"*"
            user_input = resolved
        elif _is_pronoun_heavy(user_input):
            await cl.Message(
                content="I wasn't sure what you're referring to. "
                "Could you provide more details or restate your question?"
            ).send()
            return None
    except (ImportError, KeyError, ValueError, AttributeError, RuntimeError):
        pass
    _latency.stop("pronoun_resolve")

    # User model personalization
    _user_context_note = None
    try:
        from chat_app.user_model import build_user_model, get_user_context_note
        user_model = await build_user_model(context.engine, _username)
        _user_context_note = get_user_context_note(user_model)
    except (ImportError, AttributeError, OSError, ValueError):
        pass

    return RequestSetup(
        user_input=user_input,
        username=_username or "",
        thread_id=_thread or "",
        request_id=_request_id,
        otel_root_span=_otel_root_span,
        otel_ctx_token=_otel_ctx_token,
        resolution_notice=_resolution_notice,
        user_context_note=_user_context_note,
        latency=_latency,
    )


@dataclasses.dataclass
class RouteResult:
    """Values computed during the routing phase of on_message."""
    plan: Any
    routing_ms: int
    wf_run: Any
    wf_engine: Any
    workflow_arc: Any
    current_profile: str
    user_settings: Dict


async def route_and_track(
    user_input: str,
    username: str,
    request_id: Optional[str],
    context: Any,
    latency: Any,
    trace_pipeline_stage_fn: Any,
    ai_attributes_cls: Any,
) -> "RouteResult":
    """Handle routing, workflow engine, episodic memory, workflow memory tracking.

    Returns a RouteResult with plan, workflow run, etc.
    """
    from query_router import route_query
    from chat_app.pipeline_lineage import init_trace, record_stage
    from chat_app.schemas import PipelineStage
    from chat_app.user_profiles import get_profile_manager
    from message_metadata import extract_message_metadata

    # Agent State
    try:
        from chat_app.agent_state import get_agent_state, save_agent_state
        agent_state = get_agent_state()
        agent_state.turn_count += 1
        save_agent_state(agent_state)
    except (ImportError, AttributeError, OSError, ValueError):
        pass

    current_profile = cl.user_session.get("chat_profile", "general")
    user_settings = cl.user_session.get("settings", {})

    tags, metadata = extract_message_metadata(user_input)
    tags.append(f"profile:{current_profile}")
    metadata["profile"] = current_profile
    if cl.context.current_step:
        cl.context.current_step.tags = tags
        cl.context.current_step.metadata = metadata

    latency.start("routing")
    with trace_pipeline_stage_fn("routing", profile=current_profile) as _routing_span:
        plan = route_query(user_input, user_settings)
        if _routing_span:
            _routing_span.set_attribute(ai_attributes_cls.PIPELINE_INTENT, plan.intent or "unknown")
    routing_ms = latency.stop("routing")

    init_trace(user_input=user_input, intent=plan.intent or "", profile=current_profile, request_id=request_id)

    _wf_run = None
    _wf_engine = None
    try:
        from chat_app.workflow_engine import get_workflow_engine
        _wf_engine = get_workflow_engine()
        _wf_name = f"intent_{plan.intent}" if plan.intent else "general_qa"
        _wf_defn = _wf_engine.get_definition(_wf_name) or _wf_engine.get_definition("general_qa")
        if _wf_defn:
            _wf_run = _wf_engine.start_run(_wf_defn.name, actor=username, input_preview=user_input[:200])
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[route_and_track] workflow_engine: %s", _exc)

    record_stage(PipelineStage.ROUTING, duration_ms=routing_ms, success=True,
                 metadata={"intent": plan.intent, "profile": plan.profile, "skip_retrieval": plan.skip_retrieval})
    if _wf_run:
        _step = _wf_run.add_step("routing", "classify")
        _step.start()
        _step.complete(output=f"intent={plan.intent}", intent=plan.intent, profile=plan.profile)
        _step.latency_ms = routing_ms
    logger.info(
        "[ROUTE] intent=%s profile=%s skip_retrieval=%s rid=%s",
        plan.intent, plan.profile, plan.skip_retrieval, request_id,
        extra={"stage": "route", "intent": plan.intent, "profile": plan.profile,
               "skip_retrieval": plan.skip_retrieval, "request_id": request_id},
    )

    try:
        from chat_app.cost_tracker import set_cost_context
        set_cost_context(intent=plan.intent or "")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[route_and_track] cost_context: %s", _exc)

    try:
        _profile_mgr = get_profile_manager()
        _profile_mgr.record_query(user_id=username or "anonymous", query=user_input, intent=plan.intent or "unknown")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[route_and_track] profile_mgr: %s", _exc)

    try:
        from chat_app.episodic_memory import find_similar_episodes
        similar_episodes = await find_similar_episodes(context.engine, user_input, username=username, limit=3)
        if similar_episodes:
            plan.episode_context = "\n".join([
                f"Similar past query: {ep.get('query','')} → {ep.get('intent','')} "
                f"(quality: {ep.get('confidence',0):.1f}, success: {ep.get('success',-1)})"
                for ep in similar_episodes[:3]
            ])
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[route_and_track] episodic_memory: %s", _exc)

    _workflow_arc = None
    try:
        from chat_app.workflow_memory import get_workflow_memory
        _wm = get_workflow_memory()
        _workflow_arc = _wm.detect_continuation(
            query=user_input, user_id=username or "anonymous", intent=plan.intent or "unknown",
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[route_and_track] workflow_memory: %s", _exc)

    return RouteResult(
        plan=plan,
        routing_ms=routing_ms,
        wf_run=_wf_run,
        wf_engine=_wf_engine,
        workflow_arc=_workflow_arc,
        current_profile=current_profile,
        user_settings=user_settings,
    )
