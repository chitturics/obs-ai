"""Main message handler for the Splunk Assistant.

Heavy lifting is delegated to:
  pipeline_retrieval.py      — retrieve_context()
  pipeline_response.py       — build_llm_context(), generate_llm_response(), build_final_response()
  pipeline_telemetry.py      — post-response telemetry
  message_handler_helpers.py — query utils, direct-intent handler, task helpers,
                               prepare_request(), route_and_track()
"""
import logging

import chainlit as cl

from helper import current_username, current_thread_id  # noqa: F401 — re-exported
from ingestion_handler import process_ingestion_directives, handle_attachments
from metrics import get_metrics
from prometheus_metrics import record_query, record_vector_search

from chat_app.guardrails import check_input as _guardrail_check_input, check_output as _guardrail_check_output, redact_pii as _guardrail_redact_pii
from chat_app.pipeline_lineage import record_stage
from chat_app.schemas import PipelineStage
from chat_app.message_context import MessageHandlerContext
from chat_app.meta_handler import handle_meta_commands
from chat_app.proactive_handler import proactive_optimization_check
from chat_app.utils import import_optional_module
from chat_app.tool_executor import should_use_tools, run_tool_augmented_query
from chat_app.pipeline_telemetry import (
    run_gci_review, run_slo_evaluation, build_reasoning_trace,
    record_session_state as _record_session,
    record_interaction_logs as _record_logs,
    record_user_profile_metrics as _record_profile,
    record_prometheus_and_lineage as _record_prom,
    record_execution_journal as _record_journal,
    record_tool_effectiveness as _record_tools,
    record_admin_activity as _record_admin,
    finalize_otel_span as _finalize_otel,
)
from chat_app.message_helpers import PipelineTelemetryContext, record_post_response_telemetry

# Pipeline stage functions (extracted per ADR-002)
from chat_app.pipeline_retrieval import retrieve_context
from chat_app.pipeline_response import (
    build_llm_context,
    generate_llm_response,
    build_final_response,
    enrich_context as _enrich_ctx,
    apply_anti_hallucination_guard,
    post_process_response,
)

# Message handler helpers
from chat_app.message_handler_helpers import (
    AIAttributes,
    INTENT_TASK_TITLES,
    INTENT_ACK_LABELS,
    _is_pronoun_heavy,              # noqa: F401 — re-exported for backward compat
    _handle_direct_intent,
    _simplify_query_for_retrieval,  # noqa: F401 — re-exported for backward compat
    _run_local_optimizer,            # noqa: F401 — re-exported for backward compat
    task_done as _task_done_fn,
    task_add as _task_add_fn,
    task_list_done as _task_list_done_fn,
    prepare_request,
    route_and_track,
)

# Pipeline data models
from chat_app.pipeline_models import RetrievalResult, LLMContextResult, BuildLLMContextRequest  # noqa: F401

# Context builder functions (moved from this file in v3.5 refactor)
from chat_app.context_builder import (  # noqa: F401
    detect_config_context,
    find_local_spec_file,
    extract_spec_stanzas,
    format_section,
)

# Prometheus metrics re-exports
try:
    from chat_app.prometheus_metrics import record_cache_miss  # noqa: F401
except ImportError:
    record_cache_miss = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Backward-compat re-exports — tests and legacy importers may reference these
# names on chat_app.message_handler even though the implementations now live
# in their respective modules.
# ---------------------------------------------------------------------------
try:
    from message_metadata import extract_message_metadata  # noqa: F401
    from chat_app.intent_handler import handle_intent  # noqa: F401
    from chat_app.query_router_handler import route_query  # noqa: F401
except ImportError:
    extract_message_metadata = handle_intent = route_query = None  # type: ignore[assignment]

try:
    from chat_app.response_generator import generate_response, _format_optimizer_bypass_response  # noqa: F401
except ImportError:
    generate_response = _format_optimizer_bypass_response = None  # type: ignore[assignment]

try:
    from chat_app.context_builder import (  # noqa: F401
        generate_followups, classify_references, build_sources_section, compute_confidence,
        format_chunk_with_metadata, score_and_filter_chunks, scrub_lines, filter_references,
    )
except ImportError:
    generate_followups = classify_references = build_sources_section = compute_confidence = None  # type: ignore[assignment]
    format_chunk_with_metadata = score_and_filter_chunks = scrub_lines = filter_references = None  # type: ignore[assignment]

try:
    from chat_app.feedback_logger import (  # noqa: F401
        get_recent_interactions, get_recent_query_preferences, get_recent_global_notes_raw,
    )
except ImportError:
    get_recent_interactions = get_recent_query_preferences = get_recent_global_notes_raw = None  # type: ignore[assignment]

try:
    from chat_app.cache import cache_vector_results, get_cached_vector_results  # noqa: F401
    from chat_app.prometheus_metrics import record_cache_hit  # noqa: F401
except ImportError:
    cache_vector_results = get_cached_vector_results = record_cache_hit = None  # type: ignore[assignment]

try:
    from shared.spl_query_optimizer import SPLQueryOptimizer  # noqa: F401
except ImportError:
    try:
        from chat_app.spl_optimizer import SPLQueryOptimizer  # noqa: F401
    except ImportError:
        SPLQueryOptimizer = None  # type: ignore[assignment, misc]

# Optional modules
PROFILES_AVAILABLE, profiles_imports = import_optional_module('profiles', ['detect_profile_from_query', 'get_profile_prompt', 'get_retrieval_strategy'])
FEEDBACK_GUARDRAILS_AVAILABLE, feedback_guardrails_imports = import_optional_module('feedback_guardrails', ['extract_feedback_guardrails', 'extract_negative_feedback_warnings'])
FEEDBACK_RETRIEVER_AVAILABLE, feedback_retriever_imports = import_optional_module('feedback_retriever', ['find_feedback_match'])

logger = logging.getLogger(__name__)

# Initialize OpenTelemetry tracing (graceful degradation if not installed)
try:
    from chat_app.otel_tracing import (
        init_otel, trace_span, trace_llm_call, trace_retrieval,
        trace_agent, trace_pipeline_stage,
    )
    try:
        from chat_app.otel_tracing import AIAttributes  # noqa: F811
    except ImportError:
        pass
    init_otel()
except ImportError:
    from contextlib import contextmanager as _cm
    @_cm
    def trace_span(name, attributes=None, kind=None): yield None  # type: ignore[assignment]
    trace_llm_call = lambda model, provider="ollama": trace_span(f"llm.{model}")  # type: ignore[assignment]
    trace_retrieval = lambda strategy, collections="": trace_span(f"rag.{strategy}")  # type: ignore[assignment]
    trace_agent = lambda name, strategy="": trace_span(f"agent.{name}")  # type: ignore[assignment]
    trace_pipeline_stage = lambda stage, intent="", profile="": trace_span(f"pipeline.{stage}")  # type: ignore[assignment]


async def on_message(message: cl.Message, context: "MessageHandlerContext") -> None:
    """Process user messages with intelligent context retrieval."""
    import time as _time
    _query_start = _time.monotonic()

    # --- Pre-routing setup: OTel, sanitization, guardrail, pronoun resolve, user model ---
    _setup = await prepare_request(message, context, _guardrail_check_input, AIAttributes)
    if _setup is None:
        return  # blocked by guardrail or pronoun ambiguity

    from chat_app.logging_utils import clear_request_context
    user_input, username, thread_id = _setup.user_input, _setup.username, _setup.thread_id
    _request_id, _otel_root_span, _otel_ctx_token = _setup.request_id, _setup.otel_root_span, _setup.otel_ctx_token
    _resolution_notice, user_context_note, _latency = _setup.resolution_notice, _setup.user_context_note, _setup.latency

    await context.ensure_services_ready()
    metrics = get_metrics()
    metrics.increment("queries_total")

    if await handle_meta_commands(message, context.vector_store, context.engine, context.starter_options):
        return

    # --- Routing, workflow tracking, episodic memory ---
    _route = await route_and_track(
        user_input, username, _request_id, context, _latency, trace_pipeline_stage, AIAttributes
    )
    plan, _wf_run, _wf_engine = _route.plan, _route.wf_run, _route.wf_engine
    _workflow_arc, current_profile, user_settings = _route.workflow_arc, _route.current_profile, _route.user_settings

    if await _handle_direct_intent(plan, user_input, context, current_profile):
        return

    # --- MCP tool-augmented path ---
    if context.mcp_tools and should_use_tools(plan.intent):
        try:
            tool_result = await run_tool_augmented_query(
                user_input=user_input, llm=context.llm, tools=context.mcp_tools,
                system_prompt=context.system_prompt, max_tool_rounds=3,
            )
            if tool_result:
                logger.info("[MCP] intent=%s result_len=%d rid=%s", plan.intent, len(tool_result), _request_id)
                await cl.Message(content=tool_result).send()
                cl.user_session.set("last_answer", tool_result); cl.user_session.set("last_context", "")
                record_query(intent=plan.intent, profile=current_profile, latency=0); return
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[MCP] tool_failed intent=%s error=%s rid=%s", plan.intent, exc, _request_id)

    # --- Acknowledge complex / long queries ---
    _sub_queries = getattr(plan, 'sub_queries', []) or []
    is_compound = getattr(plan, 'is_compound', False) or len(_sub_queries) > 1
    if is_compound and len(_sub_queries) > 1 and len(user_input) > 60:
        ack_parts = [f"Got it -- I'll break this into {len(_sub_queries)} parts:"]
        for i, sq in enumerate(_sub_queries[:5], 1):
            ack_parts.append(f"  {i}. {sq[:100]}")
        try:
            await cl.Message(content="\n".join(ack_parts), author="System").send()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[%s] %s", "message_handler.py", exc)
    elif len(user_input) > 200:
        try:
            _ack_verb = INTENT_ACK_LABELS.get(plan.intent, "working on this")
            await cl.Message(content=f"Understood -- {_ack_verb}. Let me gather the relevant context.", author="System").send()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[%s] %s", "message_handler.py", exc)

    # --- TaskList progress indicator ---
    task_list = task_analyze = None
    try:
        task_list = cl.TaskList()
        task_list.status = "Processing your request..."
        _analyze_title = INTENT_TASK_TITLES.get(plan.intent, "Analyzing your query...")
        task_analyze = cl.Task(title=_analyze_title, status=cl.TaskStatus.RUNNING)
        await task_list.add_task(task_analyze)
        await task_list.send()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        task_list = None

    async def _task_done(task, new_title=None):
        await _task_done_fn(task_list, task, new_title)

    async def _task_add(title):
        return await _task_add_fn(task_list, title)

    async def _task_list_done(status="Done"):
        await _task_list_done_fn(task_list, status)

    # --- Process ingestion directives & attachments ---
    user_input, directive_msgs = await process_ingestion_directives(
        user_input, context.vector_store, context.engine, username, thread_id,
        search_roots=context.search_roots,
    )
    await _task_done(task_analyze)

    if directive_msgs:
        await cl.Message(content="\n".join(directive_msgs)).send()
        if not user_input:
            await _task_list_done("Ingestion complete")
            return

    await handle_attachments(message, context.vector_store, context.engine, username, thread_id)

    # --- Core pipeline with error recovery ---
    quality = confidence = task_retrieval = task_llm = None
    try:
        _rag_mode = "simple"
        try:
            from chat_app.adaptive_rag import select_rag_mode
            _has_conv_history = False
            try:
                from chat_app.conversation_memory import get_conversation_context
                _has_conv_history = bool(get_conversation_context(max_turns=1))
            except (ImportError, ValueError):
                pass
            _rag_mode, _ = select_rag_mode(
                query=user_input, intent=plan.intent or "",
                confidence=plan.confidence or 0.0, has_history=_has_conv_history,
            )
        except (ImportError, ValueError, AttributeError):
            pass

        # Step 7: Retrieve context
        task_retrieval = await _task_add("Fetching relevant documentation...")
        _latency.start("retrieval")
        with trace_retrieval("parallel", collections="multi_collection") as _retrieval_span:
            memory_chunks, local_spec_content, local_spec_refs, detected_profile, chroma_source, has_conf_context, conf_files = await retrieve_context(
                user_input, context, user_settings, context.profiles_available, current_profile,
                context.map_source_to_url, context.SPEC_STATIC_ROOT, context.LOCAL_DOCS_ROOT, context.SPEC_SRC_ROOT
            )
            if _retrieval_span:
                _retrieval_span.set_attribute(AIAttributes.RAG_CHUNKS_RETRIEVED, len(memory_chunks))
                _retrieval_span.set_attribute(AIAttributes.RAG_SOURCE, chroma_source)
                _retrieval_span.set_attribute(AIAttributes.RAG_CACHE_HIT, chroma_source == "cache")
                _retrieval_span.set_attribute("rag.mode", _rag_mode)
        _retrieval_ms = _latency.stop("retrieval")
        record_stage(PipelineStage.RETRIEVAL, duration_ms=_retrieval_ms, success=True,
                     metadata={"chunks": len(memory_chunks), "source": chroma_source, "rag_mode": _rag_mode})
        if _wf_run:
            _step = _wf_run.add_step("retrieval", "retrieve")
            _step.start()
            _step.complete(output=f"{len(memory_chunks)} chunks from {chroma_source}",
                          chunks=len(memory_chunks), source=chroma_source)
            _step.latency_ms = _retrieval_ms
        await _task_done(task_retrieval, f"Retrieved {len(memory_chunks)} chunks from {chroma_source.upper()} ({_retrieval_ms:.0f}ms)")
        if chroma_source != "cache":
            _vs_collection = memory_chunks[0].get("collection", "assistant_memory") if memory_chunks and isinstance(memory_chunks[0], dict) else "assistant_memory"
            record_vector_search(collection=_vs_collection, latency=_retrieval_ms / 1000.0, result_count=len(memory_chunks))

        # Step 6b: Orchestrated Agent Dispatch
        react_context = agent_context = agent_prompt_fragment = workflow_context = None
        _active_agent_name = orch_result = None
        _latency.start("orchestration")
        try:
            from chat_app.orchestration_strategies import execute_orchestration
            task_orch = await _task_add("Orchestrating agent analysis")
            with trace_agent("orchestrator", strategy=plan.intent or "") as _orch_span:
                orch_result = await execute_orchestration(user_input, plan.intent, plan, context)
                if _orch_span and orch_result:
                    _orch_span.set_attribute(AIAttributes.AGENT_STRATEGY, orch_result.strategy_used or "")
                    _orch_span.set_attribute(AIAttributes.AGENT_NAME, getattr(orch_result, 'agent_name', '') or "")
                    _orch_span.set_attribute(AIAttributes.AGENT_ITERATIONS, getattr(orch_result, 'iterations', 0))
                    _orch_span.set_attribute(AIAttributes.PIPELINE_SUCCESS, orch_result.success)

            if getattr(orch_result, "clarification_needed", False):
                clarification_questions = getattr(orch_result, "clarification_questions", [])
                if clarification_questions:
                    clarification_text = "\n".join(f"- {q}" for q in clarification_questions)
                    clarification_message = "Before I can give you an accurate answer, I need a bit more information:\n\n" + clarification_text
                else:
                    clarification_message = "Could you clarify your question so I can give you a more accurate answer?"
                await cl.Message(content=clarification_message).send()
                try:
                    await _task_done(task_orch, "Clarification requested")
                except Exception:  # broad catch — resilience at boundary
                    pass
                return

            if orch_result.success and orch_result.context:
                if orch_result.strategy_used == "workflow":
                    workflow_context = orch_result.context
                elif orch_result.strategy_used == "react":
                    react_context = orch_result.context
                else:
                    agent_context = orch_result.context
                    agent_prompt_fragment = orch_result.system_prompt_fragment
                _active_agent_name = getattr(orch_result, 'agent_name', None)
                _spf = orch_result.system_prompt_fragment or ""
                if "[NEEDS_CLARIFICATION]" in _spf:
                    _gaps = _spf.replace("[NEEDS_CLARIFICATION]", "").strip()
                    if _gaps:
                        agent_prompt_fragment = ""
                        agent_context += f"\n\n**Note:** The analysis may be incomplete. Consider asking about: {_gaps}"
                fb = f" (fallback from {orch_result.fallback_from})" if orch_result.fallback_used else ""
                await _task_done(task_orch, f"Strategy: {orch_result.strategy_used}{fb} ({orch_result.iterations} iter, {orch_result.duration_ms:.0f}ms)")
            else:
                await _task_done(task_orch, f"Orchestration: {orch_result.strategy_used} (no context)")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[ORCH] failed error=%s rid=%s", exc, _request_id)
            try:
                await _task_done(task_orch, f"Orchestration failed: {type(exc).__name__}")
            except Exception:  # broad catch — resilience at boundary
                pass
            try:
                from chat_app.agent_dispatcher import get_agent_dispatcher, format_agent_context_for_llm
                dispatcher = get_agent_dispatcher()
                dispatch_result = await dispatcher.dispatch(user_input, plan.intent)
                agent_llm_context = format_agent_context_for_llm(dispatch_result)
                if agent_llm_context:
                    agent_context = agent_llm_context
                    agent_prompt_fragment = dispatch_result.system_prompt_fragment
                    _active_agent_name = dispatch_result.agent_name
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as fallback_exc:
                logger.warning("[ORCH] emergency_fallback_failed error=%s rid=%s", fallback_exc, _request_id)
        _orch_ms = _latency.stop("orchestration")
        _orch_strategy = getattr(orch_result, 'strategy_used', '') if orch_result else ''
        record_stage(PipelineStage.ORCHESTRATION, duration_ms=_orch_ms, success=True,
                     metadata={"strategy": _orch_strategy or 'none', "agent": _active_agent_name or 'none'})
        if _wf_run:
            _step = _wf_run.add_step("orchestration", "agent_select")
            _step.start()
            _step.complete(output=f"strategy={_orch_strategy}, agent={_active_agent_name}",
                          strategy=_orch_strategy, agent=_active_agent_name)
            _step.latency_ms = _orch_ms

        # Step 9: Build context for LLM
        _latency.start("context_build")
        with trace_pipeline_stage("context_build", intent=plan.intent or "", profile=current_profile):
            formatted_context, base_system_prompt, feedback_match, all_refs, opt_result, plan, scored_chunks, doc_snippets = await build_llm_context(
                user_input, memory_chunks, local_spec_content, local_spec_refs, user_settings, context.engine,
                username, context.system_prompt, context.profiles_available, detected_profile,
                context.feedback_guardrails_available, context.map_source_to_url, context.load_static_context,
                plan=plan, conf_files=conf_files,
            )
        formatted_context, base_system_prompt, confidence = await _enrich_ctx(
            formatted_context=formatted_context, base_system_prompt=base_system_prompt,
            plan=plan, user_input=user_input, username=username,
            user_settings=user_settings, engine=context.engine,
            memory_chunks=memory_chunks, all_refs=all_refs,
            feedback_match=feedback_match, local_spec_content=local_spec_content,
            workflow_context=workflow_context, agent_context=agent_context,
            react_context=react_context, agent_prompt_fragment=agent_prompt_fragment,
            workflow_arc=_workflow_arc, user_context_note=user_context_note,
        )
        _ctx_build_ms = _latency.stop("context_build")
        record_stage(PipelineStage.CONTEXT_BUILD, duration_ms=_ctx_build_ms, success=True,
                     metadata={"context_chars": len(formatted_context), "agent_context": bool(agent_context)})

        # Decide: feedback match, no context, or full LLM
        validated_answer = ""
        if isinstance(feedback_match, dict):
            sim = feedback_match.get("similarity", 0)
            validated_answer = feedback_match.get("answer", "") if sim >= 0.90 else ""
        has_context = memory_chunks or local_spec_content or feedback_match
        _is_conceptual = plan and getattr(plan, 'intent', '') in ('general_qa', 'spl_help', 'greeting', 'tutorial', 'feedback', 'clarification')
        no_knowledge = (confidence and confidence.label == "VERY_LOW" and not has_context and not _is_conceptual)

        if validated_answer:
            logger.info("[PIPELINE] action=use_feedback sim=%.2f rid=%s", sim, _request_id)
            result_text = validated_answer; _latency.start("llm_inference"); _latency.stop("llm_inference")
        elif no_knowledge:
            logger.info("[PIPELINE] action=skip_llm reason=no_context rid=%s", _request_id)
            hint = f"\n\n**Hint:** {confidence.clarification_question}" if confidence.clarification_question else ""
            result_text = "I don't have enough information in my knowledge base to answer this accurately.\n\nTry: rephrasing, `/search <topic>`, or uploading relevant docs." + hint
            _latency.start("llm_inference"); _latency.stop("llm_inference")
        else:
            # Step 10: Generate LLM response
            task_llm = await _task_add(f"Composing a response ({len(scored_chunks)} relevant chunks)...")
            _latency.start("llm_inference")
            _llm_model = context.settings.ollama.model if hasattr(context, 'settings') else "unknown"
            with trace_llm_call(_llm_model) as _llm_span:
                result_text = await generate_llm_response(
                    user_input, formatted_context, context.chain, context.llm, user_settings,
                    context.system_prompt, base_system_prompt, feedback_match, detected_profile, opt_result, plan,
                )
                if _llm_span and result_text:
                    _llm_span.set_attribute(AIAttributes.LLM_RESPONSE_CHARS, len(result_text))
            _llm_ms = _latency.stop("llm_inference")
            record_stage(PipelineStage.LLM_INFERENCE, duration_ms=_llm_ms, success=True,
                         metadata={"context_chars": len(formatted_context), "response_chars": len(result_text)})
            if _wf_run:
                _step = _wf_run.add_step("llm_inference", "llm_call")
                _step.start()
                _step.complete(output=f"{len(result_text)} chars")
                _step.latency_ms = _llm_ms

        # Self-Evaluation
        _latency.start("scoring")
        try:
            from chat_app.self_evaluator import evaluate_response_quality
            quality = evaluate_response_quality(result_text, user_input, formatted_context, len(memory_chunks))
        except (ImportError, ValueError, AttributeError):
            pass
        _scoring_ms = _latency.stop("scoring")
        record_stage(PipelineStage.POST_PROCESS, duration_ms=_scoring_ms, success=True,
                     metadata={"quality": quality.overall if quality else None,
                               "confidence": confidence.label if confidence else None})

        result_text = apply_anti_hallucination_guard(result_text, confidence, memory_chunks, _request_id)
        result_text, _profile_tip = post_process_response(result_text, user_input, plan, memory_chunks, current_profile)

        # Step 11: Build final response
        _latency.start("final_assembly")
        final_response, actions = await build_final_response(
            result_text, local_spec_content, all_refs, scored_chunks, memory_chunks,
            chroma_source, user_settings, user_input, has_conf_context, context.engine,
        )
        _latency.stop("final_assembly")

        try:
            from chat_app.prometheus_metrics import record_pipeline_stages as _record_stages
            _record_stages(_latency.to_dict())
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[%s] %%s", "message_handler.py", _exc)

        if _resolution_notice: final_response = f"{_resolution_notice}\n\n{final_response}"
        if _profile_tip: final_response += _profile_tip

        final_response, _gci_record = run_gci_review(
            user_input, final_response, _active_agent_name, plan,
            formatted_context, memory_chunks, _request_id,
        )
        run_slo_evaluation(_latency, quality)

        if _wf_run:
            try:
                _wf_run.metadata.update({"intent": plan.intent or "", "profile": current_profile,
                                          "chunks": len(memory_chunks), "confidence": quality.overall if quality else 0})
                _wf_engine.finish_run(_wf_run, success=True)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("[%s] %%s", "message_handler.py", _exc)

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as pipeline_exc:
        if '_wf_run' in dir() and _wf_run:
            try:
                _wf_run.metadata["error"] = str(pipeline_exc)[:200]
                _wf_engine.finish_run(_wf_run, success=False)
            except Exception:  # broad catch — resilience at boundary
                pass
        logger.error("[PIPELINE] failed error=%s rid=%s", pipeline_exc, _request_id, exc_info=True)
        try:
            record_stage(PipelineStage.POST_PROCESS, duration_ms=0, success=False,
                         error=f"{type(pipeline_exc).__name__}: {str(pipeline_exc)[:200]}")
        except Exception:  # broad catch — resilience at boundary
            pass
        for _t in [task_retrieval, task_llm]:
            if _t:
                try:
                    _t.status = cl.TaskStatus.FAILED
                except Exception:  # broad catch — resilience at boundary
                    pass
        try:
            from chat_app.failure_analyzer import categorize_failure, execute_recovery
            failure = categorize_failure(pipeline_exc, context={"user_input": user_input, "intent": plan.intent if 'plan' in dir() else "unknown"})
            recovery_msg = await execute_recovery(failure, user_input=user_input, context=context, user_settings=user_settings)
            final_response = recovery_msg or f"I encountered an issue processing your request. Please try again.\n\n*Error: {type(pipeline_exc).__name__}*"
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as recovery_exc:
            logger.error("[RECOVERY] failed error=%s rid=%s", recovery_exc, _request_id)
            final_response = "I'm sorry, I encountered an error while processing your request. Please try again later."
        actions, memory_chunks, scored_chunks, chroma_source = [], [], [], "error"
        formatted_context, detected_profile = "", None

    await _task_done(task_llm, "Response complete")
    await _task_list_done("Done")

    # Reasoning Transparency Trace
    _reasoning_html = build_reasoning_trace(
        user_settings, plan, detected_profile, current_profile,
        memory_chunks, confidence, react_context, _time, _query_start,
    )
    if _reasoning_html:
        final_response += f"\n\n{_reasoning_html}"

    # Guardrail: Output safety check
    try:
        _gr_sources = [c.get("text", "") for c in (scored_chunks or []) if isinstance(c, dict)]
        _gr_output = _guardrail_check_output(final_response, sources=_gr_sources or None)
        if _gr_output.pii_detected:
            logger.warning("[GUARD] action=redact_pii rid=%s", _request_id)
            final_response = _guardrail_redact_pii(final_response)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[%s] %%s", "message_handler.py", _exc)

    # Send or update streaming message
    streaming_msg = cl.user_session.get("streaming_msg")
    if streaming_msg:
        streaming_msg.content = final_response
        streaming_msg.actions = actions
        await streaming_msg.update()
        sent_msg = streaming_msg
        cl.user_session.set("streaming_msg", None)
    else:
        sent_msg = await cl.Message(content=final_response, actions=actions).send()

    # Post-response telemetry
    _record_profile(username, user_input, _query_start, _time)
    await _record_logs(context.engine, username, thread_id, user_input, final_response, formatted_context)
    await _record_session(
        user_input, final_response, formatted_context, sent_msg,
        _active_agent_name, plan, detected_profile, current_profile, memory_chunks,
    )

    collections_used = list({c.get("collection", "") for c in memory_chunks if c.get("collection")})
    cl.user_session.set("last_collections_used", collections_used)

    _query_elapsed = _time.monotonic() - _query_start
    _quality_val = quality.overall if quality else None

    _record_prom(plan, detected_profile, current_profile, _query_elapsed,
                 memory_chunks, chroma_source, quality, _latency, _request_id, orch_result, _active_agent_name)
    _record_journal(_request_id, user_input, plan, detected_profile, current_profile,
                    orch_result, _active_agent_name, memory_chunks, _quality_val,
                    _gci_record, _query_elapsed, chroma_source)
    _record_tools(plan, quality, _query_elapsed, react_context)
    _record_admin(user_input, plan, username, thread_id, collections_used,
                  memory_chunks, quality, _query_elapsed, detected_profile, current_profile)

    _telemetry_ctx = PipelineTelemetryContext(
        user_input=user_input, plan=plan, quality=quality,
        quality_value=_quality_val, username=username, thread_id=thread_id,
        query_elapsed=_query_elapsed, memory_chunks=memory_chunks,
        chroma_source=chroma_source, latency_tracker=_latency,
        time_module=_time, query_start=_query_start, context=context,
        confidence=confidence, detected_profile=detected_profile,
        current_profile=current_profile, collections_used=collections_used,
        final_response=final_response, active_agent_name=_active_agent_name,
        orch_result=orch_result, request_id=_request_id,
        react_context=react_context, workflow_arc=_workflow_arc,
    )
    await record_post_response_telemetry(_telemetry_ctx)

    await proactive_optimization_check(plan, final_response)

    _finalize_otel(
        _otel_root_span, _otel_ctx_token if _otel_root_span else None,
        _time, _query_start, plan, current_profile, chroma_source, quality, confidence,
    )

    clear_request_context()
