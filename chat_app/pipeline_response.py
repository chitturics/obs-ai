"""Pipeline Response Stage — LLM context building, response generation, and formatting.

Extracted from message_handler.py per ADR-002.
Contains: build_llm_context(), generate_llm_response(), build_final_response(),
          anti-hallucination guard, and response helpers.
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

import chainlit as cl

from feedback_logger import (
    get_recent_global_notes_raw,
    get_recent_interactions,
    get_recent_query_preferences,
)
from context_builder import (
    detect_config_context,
    score_and_filter_chunks,
    format_chunk_with_metadata,
    scrub_lines,
    format_section,
    filter_references,
    classify_references,
    compute_confidence,
    generate_followups,
    build_sources_section,
    _friendly_collection_name,
)
from response_generator import generate_response, _format_optimizer_bypass_response
from search_opt_client import call_search_optimizer, format_optimizer_context
from shared.spl_query_optimizer import SPLQueryOptimizer

from chat_app.langfuse_integration import observe_llm
from chat_app.registry import Intent
from chat_app.settings import get_settings
from chat_app.utils import import_optional_module
from metrics import get_metrics
from query_router import QueryPlan

PROFILES_AVAILABLE, profiles_imports = import_optional_module(
    'profiles', ['detect_profile_from_query', 'get_profile_prompt', 'get_retrieval_strategy']
)
FEEDBACK_RETRIEVER_AVAILABLE, feedback_retriever_imports = import_optional_module(
    'feedback_retriever', ['find_feedback_match']
)

logger = logging.getLogger(__name__)


def _run_local_optimizer(query: str) -> Any:
    """Run the local SPL optimizer and return the OptimizedQuery object directly.
    The _format_optimizer_bypass_response() handles both dict and OptimizedQuery."""
    result = SPLQueryOptimizer.optimize(query)
    return result


@observe_llm(name="build_llm_context")
async def build_llm_context(
    user_input: str,
    memory_chunks: List[Any],
    local_spec_content: List[str],
    local_spec_refs: List[str],
    user_settings: Dict[str, Any],
    engine: Any,
    username: str,
    system_prompt: str,
    profiles_available: bool,
    detected_profile: Optional[str],
    feedback_guardrails_available: bool,
    map_source_to_url: Any,
    load_static_context: Any,
    plan: Optional["QueryPlan"] = None,
    conf_files: Optional[List[str]] = None,
) -> Tuple[str, str, Any, List[str], Any, "QueryPlan", List[Any], List[str]]:
    """Builds the context for the LLM.

    Args:
        plan: Pre-computed QueryPlan (avoids redundant route_query call).
        conf_files: Pre-detected config files (avoids redundant detect_config_context call).
    """
    feedback_match = None
    is_fast_mode = get_settings().fast_mode
    if user_settings.get("liked_queries_boost", True) and FEEDBACK_RETRIEVER_AVAILABLE:
        find_feedback_match = feedback_retriever_imports['find_feedback_match']
        # First check already-retrieved chunks for feedback matches (no embedding call — fast)
        feedback_match = find_feedback_match(memory_chunks, user_input, similarity_threshold=0.75)
        # If no match in retrieved chunks, directly query the feedback_qa collection.
        # Skip in fast_mode — query_feedback_collection does an embed_query (10-14s on CPU).
        if not feedback_match and not is_fast_mode:
            try:
                from feedback_retriever import query_feedback_collection
                feedback_match = query_feedback_collection(user_input, similarity_threshold=0.75)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.debug("[%s] %s", "pipeline_response.py", exc)

        # If main query doesn't match, try sub-queries against feedback
        # (e.g., "what is Splunk & NLS" → try "what is Splunk", "what is NLS")
        if not feedback_match and plan and hasattr(plan, 'sub_queries') and plan.sub_queries:
            for sub_q in plan.sub_queries:
                # Check retrieved chunks first (no embedding call — fast)
                sub_match = find_feedback_match(memory_chunks, sub_q, similarity_threshold=0.75)
                # Skip direct collection query in fast_mode (avoids extra embed call per sub-query)
                if not sub_match and not is_fast_mode:
                    try:
                        from feedback_retriever import query_feedback_collection
                        sub_match = query_feedback_collection(sub_q, similarity_threshold=0.75)
                    except (ImportError, ValueError, RuntimeError):
                        pass
                if sub_match:
                    logger.info("[FEEDBACK] Sub-query match for '%s' (sim=%.2f)", sub_q[:50], sub_match.get("similarity", 0))
                    feedback_match = sub_match
                    break

    if conf_files is None:
        conf_files, _ = detect_config_context(user_input)

    # Determine reranking flag from config.yaml features and user session.
    # Reranking is auto-enabled for complex queries and specific intents
    # even when the global feature flag is off.
    use_reranking = False
    try:
        from chat_app.settings import _load_yaml_config
        yaml_config = _load_yaml_config()
        use_reranking = bool(yaml_config.get("features", {}).get("reranking", False))
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_response.py", _exc)

    # --- Intent-aware auto-enable: complex queries benefit from reranking ---
    current_intent = plan.intent if plan else ""
    _RERANK_INTENTS = {"spl_explanation", "compare_commands", "troubleshooting"}
    _SIMPLE_INTENTS = {"greeting", "meta_question", "data_transform"}
    if not use_reranking and current_intent not in _SIMPLE_INTENTS:
        word_count = len(user_input.split())
        if word_count > 10 or current_intent in _RERANK_INTENTS:
            use_reranking = True
            logger.info(
                "[RERANK] Auto-enabled: intent=%s words=%d",
                current_intent, word_count,
            )

    # Allow per-session override (explicit user toggle always wins)
    if user_settings.get("reranking") is not None:
        use_reranking = bool(user_settings.get("reranking"))

    scored_chunks = score_and_filter_chunks(
        memory_chunks, user_input, conf_files, user_settings,
        map_source_to_url=map_source_to_url,
        use_reranking=use_reranking,
        intent=current_intent,
    )
    top_chunks = scored_chunks[:15]

    doc_snippets = []
    for score, ref, text, source, chunk_dict in top_chunks:
        doc_snippets.append(format_chunk_with_metadata(text, chunk_dict))
    doc_snippets = scrub_lines(doc_snippets)

    all_refs = list(local_spec_refs)
    for _, ref, _, source, _ in top_chunks:
        if ref and ref not in all_refs:
            all_refs.append(ref)
    all_refs = filter_references(all_refs, user_input)

    # Parallelize DB queries instead of running them sequentially
    import asyncio as _aio
    feedback_task = _aio.ensure_future(get_recent_global_notes_raw(engine, limit=5))
    liked_queries_task = _aio.ensure_future(get_recent_query_preferences(engine, liked=True, limit=5))
    interaction_history_task = _aio.ensure_future(get_recent_interactions(engine, username=username, limit=8))
    recent_feedback, liked_queries_raw, interaction_history_raw = await _aio.gather(
        feedback_task, liked_queries_task, interaction_history_task
    )
    liked_queries = scrub_lines(liked_queries_raw)
    scrub_lines(interaction_history_raw)
    static_context = load_static_context()

    optimizer_context = None
    opt_result = None
    if plan is None:
        from query_router import route_query
        plan = route_query(user_input, user_settings)
    if plan.optimizer_action:
        try:
            opt_action = plan.optimizer_action
            opt_type = plan.optimizer_type if plan.optimizer_type != "auto" else None
            query_for_optimizer = plan.extracted_query or user_input
            opt_result = await call_search_optimizer(
                query_for_optimizer,
                profile=plan.profile,
                action=opt_action,
                force_type=opt_type,
            )
            if opt_result:
                optimizer_context = format_optimizer_context(opt_result)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[OPTIMIZER] service_failed reason=%s", exc)

        if not opt_result and opt_action == "optimize" and query_for_optimizer:
            try:
                opt_result = _run_local_optimizer(query_for_optimizer)
                if opt_result:
                    # Local optimizer returns OptimizedQuery object, not dict.
                    # Skip format_optimizer_context (which expects dict) - the bypass
                    # function handles OptimizedQuery directly.
                    pass  # local optimizer used — captured in pipeline summary
            except (ValueError, KeyError, AttributeError) as opt_exc:
                logger.debug("[PIPELINE] Local optimizer fallback failed: %s", opt_exc)

    context_sections = []
    # Priority order: spec files > knowledge base > optimizer (most relevant first)
    if local_spec_content:
        context_sections.append(format_section("### Local Spec Files (authoritative):", local_spec_content[:2]))
    if doc_snippets:
        context_sections.append(format_section("### Knowledge Base:", doc_snippets[:6]))
    if optimizer_context:
        context_sections.append(format_section("### Search Optimizer:", [optimizer_context]))
    if recent_feedback:
        feedback_texts = [
            f"**{n.get('title', 'Feedback')}** (by {n.get('created_by', 'user')})\n{n.get('body', '')}"
            for n in recent_feedback[:3]
        ]
        context_sections.append(format_section("### Team Feedback:", feedback_texts))
    # Knowledge Graph context (structural relationships)
    try:
        from chat_app.knowledge_graph import get_knowledge_graph
        knowledge_graph = get_knowledge_graph()
        if knowledge_graph:
            try:
                from chat_app.settings import get_settings as _kg_settings
                max_context_facts = _kg_settings().knowledge_graph.max_context_facts
            except Exception as _exc:  # broad catch — resilience against all failures
                logger.debug("[%s] %%s", "pipeline_response.py", _exc)
                max_context_facts = 8
            kg_context = knowledge_graph.generate_context_for_query(
                user_input,
                plan.intent if plan else Intent.GENERAL_QA,
                max_facts=max_context_facts,
            )
            if kg_context and isinstance(kg_context, str):
                context_sections.append(kg_context)
    except (ImportError, AttributeError, ValueError):
        pass
    # Registry capabilities context — gives LLM awareness of available tools
    try:
        from chat_app.registry import build_capabilities_context
        capabilities_context = build_capabilities_context()
        if capabilities_context and isinstance(capabilities_context, str):
            context_sections.append(capabilities_context)
    except (ImportError, AttributeError):
        pass

    # These sections are lower priority — only include if we have room
    # (the context truncator will cut them if needed)
    if liked_queries:
        context_sections.append(format_section("### Successful Query Patterns:", liked_queries[:3]))
    if static_context:
        context_sections.append(format_section("### Environment Context:", static_context[:2]))

    if context_sections:
        formatted_context = "\n\n".join(context_sections)
    elif plan and plan.intent in (Intent.SPL_GENERATION, Intent.SPL_OPTIMIZATION, Intent.SPL_EXPLANATION, Intent.SPL_VALIDATION):
        formatted_context = (
            "No specific documents matched this query, but you have deep expertise in SPL (Splunk Processing Language). "
            "Use your built-in knowledge of SPL commands, functions, and best practices to answer. "
            "Provide optimized, production-ready SPL with explanations."
        )
    else:
        formatted_context = "No specific context available."

    base_system_prompt = system_prompt
    if profiles_available and detected_profile:
        get_profile_prompt = profiles_imports['get_profile_prompt']
        base_system_prompt = get_profile_prompt(detected_profile)

    # Feedback guardrails are skipped for speed — negative_feedback filtering
    # and feedback_match already handle this in the retrieval phase.
    # Only inject guardrails for queries with enough chunks (avoids extra embedding calls)
    FEEDBACK_GUARDRAILS_AVAILABLE, feedback_guardrails_imports = import_optional_module(
        'feedback_guardrails', ['extract_feedback_guardrails', 'extract_negative_feedback_warnings']
    )
    if feedback_guardrails_available and FEEDBACK_GUARDRAILS_AVAILABLE and len(memory_chunks) >= 5:
        try:
            extract_feedback_guardrails = feedback_guardrails_imports['extract_feedback_guardrails']
            positive = await cl.make_async(extract_feedback_guardrails)(user_input, max_examples=2)
            if positive:
                formatted_context = positive + "\n\n" + formatted_context
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[%s] %%s", "pipeline_response.py", _exc)

    return formatted_context, base_system_prompt, feedback_match, all_refs, opt_result, plan, scored_chunks, doc_snippets


async def generate_llm_response(
    user_input: str,
    formatted_context: str,
    chain: Any,
    llm: Any,
    user_settings: Dict[str, Any],
    system_prompt: str,
    base_system_prompt: str,
    feedback_match: Any,
    detected_profile: Optional[str],
    opt_result: Any,
    plan: "QueryPlan",
) -> str:
    """Generates the LLM response."""
    metrics = get_metrics()
    context_hash = hashlib.sha256(formatted_context.encode()).hexdigest()
    result_text = None
    if opt_result and plan.optimizer_action in ("optimize", "review", "auto"):
        result_text = _format_optimizer_bypass_response(opt_result, plan.extracted_query or user_input, plan.optimizer_action)
        if result_text:
            pass  # optimizer bypass — captured in pipeline summary

    if not result_text:
        active_chain = chain
        if base_system_prompt != system_prompt:
            from langchain_core.prompts import ChatPromptTemplate as _CPT
            from langchain_core.output_parsers import StrOutputParser as _SOP
            active_chain = _CPT.from_messages([("system", base_system_prompt), ("human", "{input}")]) | llm | _SOP()

        with metrics.timer("llm_latency"):
            result_text = await generate_response(
                user_input, formatted_context, active_chain, user_settings, context_hash,
                feedback_match=feedback_match,
                profile=detected_profile,
            )

    if not result_text:
        result_text = "I'm sorry, the LLM service is currently unavailable. Please try again in a moment."

    return result_text


async def build_final_response(
    result_text: str,
    local_spec_content: List[str],
    all_refs: List[str],
    scored_chunks: List[Any],
    memory_chunks: List[Any],
    chroma_source: str,
    user_settings: Dict[str, Any],
    user_input: str,
    has_conf_context: bool,
    engine: Any = None,
) -> Tuple[str, List[Any]]:
    """Builds the final response message."""
    confidence_label = compute_confidence(local_spec_content, all_refs, len(scored_chunks), memory_chunks)

    retrieval_parts = []
    if chroma_source == "cache":
        retrieval_parts.append("Cached")
    else:
        retrieval_parts.append(f"ChromaDB: {len(memory_chunks)} chunks")
    if scored_chunks:
        retrieval_parts.append(f"{len(scored_chunks)} relevant")
        # Add collection provenance to confidence line
        coll_names = []
        seen_colls = set()
        for item in scored_chunks:
            chunk_dict = item[4] if len(item) > 4 else {}
            coll_raw = chunk_dict.get("collection", "") or ""
            if coll_raw and coll_raw not in seen_colls:
                seen_colls.add(coll_raw)
                coll_names.append(_friendly_collection_name(coll_raw))
        if coll_names:
            retrieval_parts.append(f"from: {', '.join(coll_names)}")
    retrieval_status = " | ".join(retrieval_parts)

    response_parts = [
        f"**Confidence:** {confidence_label} | {retrieval_status}",
        "",
        result_text.strip(),
    ]

    # --- Auto-explain SPL code blocks in the response ---
    try:
        import re as _re
        _spl_blocks = _re.findall(r'```(?:spl|splunk)?\n(.*?)```', result_text.strip(), _re.DOTALL)
        if _spl_blocks and user_settings.get("auto_explain_spl", True):
            from chat_app.proactive_insights import explain_spl
            for _spl_block in _spl_blocks[:2]:  # Limit to first 2 SPL blocks
                _spl_clean = _spl_block.strip()
                if len(_spl_clean) > 20 and '|' in _spl_clean:
                    _expl = explain_spl(_spl_clean)
                    if _expl.steps and len(_expl.steps) >= 2:
                        _step_lines = [f"  {i}. {s}" for i, s in enumerate(_expl.steps, 1)]
                        _perf_lines = [f"  - {n}" for n in _expl.performance_notes[:2]] if _expl.performance_notes else []
                        _explain_section = "\n**Query Breakdown:**\n"
                        _explain_section += "\n".join(_step_lines)
                        if _perf_lines:
                            _explain_section += "\n\n**Performance Notes:**\n" + "\n".join(_perf_lines)
                        _explain_section += f"\n\n*Complexity: {_expl.complexity}*"
                        response_parts.append(_explain_section)
                        break  # Only explain the first significant block
    except (ImportError, AttributeError) as exc:
        logger.debug("[%s] %s", "pipeline_response.py", exc)

    show_sources = user_settings.get("show_sources", True)

    # Sources section: collection-level provenance + top document names
    sources_section = build_sources_section(scored_chunks, show_sources)
    if sources_section:
        response_parts.extend(["", sources_section])

    # References section: HTTP-linked references (PDFs, external URLs)
    valid_refs = classify_references(all_refs)
    if valid_refs and show_sources:
        response_parts.extend(["", "**References:**"])
        for ref_type, ref_url, ref_display in valid_refs[:5]:
            if ref_type == "feedback":
                response_parts.append(f"- [{ref_display}]({ref_url})" if ref_url.startswith("http") else f"- {ref_display}")
            elif ref_type == "doc":
                response_parts.append(f"- [{ref_display}]({ref_url})")
            elif ref_type == "link":
                response_parts.append(f"- [{ref_display}]({ref_url})")

    followups = await generate_followups(user_input, has_conf_context, engine)
    actions = [
        cl.Action(name="followup", label=q, payload={"question": q}, description="Click to ask this question")
        for q in followups
    ]

    return "\n".join(response_parts), actions


# --- Anti-Hallucination Guard ---

# Uncertainty markers used by the anti-hallucination guard
UNCERTAINTY_MARKERS = [
    "i don't have", "i do not have", "not in my knowledge",
    "i'm not sure", "i am not sure", "don't have enough information",
    "cannot find", "no relevant", "limited information",
    "not found in", "unable to find", "i don't know",
    "no information", "not available in", "not in my",
]


def apply_anti_hallucination_guard(
    result_text: str,
    confidence: Any,
    memory_chunks: List[Any],
    request_id: str,
) -> str:
    """Check if LLM ignored confidence instructions and hallucinated.

    Returns the (possibly modified) result_text.
    """
    if confidence and confidence.label == "VERY_LOW" and len(memory_chunks) < 2:
        response_lower = result_text.lower()
        has_uncertainty = any(marker in response_lower for marker in UNCERTAINTY_MARKERS)
        if not has_uncertainty:
            logger.warning("[GUARD] action=replace_response reason=very_low_confidence chunks=%d rid=%s", len(memory_chunks), request_id)
            result_text = (
                "I don't have enough information in my knowledge base to answer this question accurately.\n\n"
                "The retrieved context did not contain relevant information for your query. "
                "Please try rephrasing or check if the relevant documents have been ingested."
            )
    elif confidence and confidence.label == "LOW" and len(memory_chunks) < 3:
        response_lower = result_text.lower()
        has_uncertainty = any(marker in response_lower for marker in UNCERTAINTY_MARKERS)
        if not has_uncertainty:
            logger.warning("[GUARD] action=prepend_disclaimer reason=low_confidence chunks=%d rid=%s", len(memory_chunks), request_id)
            result_text = (
                "**Note:** I have very limited information in my knowledge base about this topic. "
                "The following response may not be fully accurate — please verify independently.\n\n"
                + result_text
            )
    return result_text


# --------------------------------------------------------------------------- #
#  Context Enrichment — injects agentic, memory, and personalization layers    #
# --------------------------------------------------------------------------- #

async def enrich_context(
    formatted_context: str,
    base_system_prompt: str,
    plan: Any,
    user_input: str,
    username: str,
    user_settings: Dict[str, Any],
    engine: Any,
    memory_chunks: List[Any],
    all_refs: List[str],
    feedback_match: Any,
    local_spec_content: List[str],
    workflow_context: Optional[str],
    agent_context: Optional[str],
    react_context: Optional[str],
    agent_prompt_fragment: Optional[str],
    workflow_arc: Any,
    user_context_note: Optional[str],
) -> tuple:
    """Inject agentic results, memory layers, and personalization into context.

    Returns (formatted_context, base_system_prompt, confidence).
    """
    # --- Inject comparison context for compare_commands intent ---
    _extra_ctx = getattr(plan, 'extra_context', None)
    if _extra_ctx:
        formatted_context = f"{_extra_ctx}\n\n{formatted_context}"

    # --- Inject agentic results into context ---
    if workflow_context:
        formatted_context = f"{workflow_context}\n\n{formatted_context}"
    if agent_context:
        formatted_context = f"{agent_context}\n\n{formatted_context}"
    if react_context:
        formatted_context = f"{react_context}\n\n{formatted_context}"

    # --- Inject workflow memory context (cross-session continuation) ---
    if workflow_arc:
        try:
            _wf_summary = workflow_arc.summary()
            if _wf_summary:
                formatted_context = (
                    f"### Prior Workflow Context (cross-session continuation)\n"
                    f"{_wf_summary}\n\n{formatted_context}"
                )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[%s] %%s", "pipeline_response.py", _exc)

    # --- Inject episodic memory context ---
    _episode_ctx = getattr(plan, 'episode_context', None)
    if _episode_ctx:
        formatted_context = (
            f"### Episodic Memory (similar past interactions)\n"
            f"{_episode_ctx}\n\n{formatted_context}"
        )

    # --- Inject agent personality into system prompt ---
    if agent_prompt_fragment:
        base_system_prompt = f"{agent_prompt_fragment}\n\n---\n\n{base_system_prompt}"

    # --- fast_mode: skip non-essential context enrichment ---
    _fast_mode = get_settings().fast_mode

    # --- Inject dynamic prompt overlay (learned behavioral rules) ---
    if not _fast_mode:
        try:
            from chat_app.self_learning import get_dynamic_prompt_overlay
            _overlay = get_dynamic_prompt_overlay()
            if _overlay:
                formatted_context = f"{_overlay}\n\n{formatted_context}"
        except (ImportError, AttributeError, ValueError):
            pass

    # --- Inject organization-specific context ---
    if not _fast_mode:
        try:
            from chat_app.proactive_insights import inject_org_context
            from chat_app.utils import load_config
            org_config = load_config().get("organization", {})
            org_context = inject_org_context(user_input, org_config)
            if org_context:
                formatted_context = f"{org_context}\n\n{formatted_context}"
        except (ImportError, KeyError, ValueError, OSError):
            pass

    # --- Inject semantic facts from episodic memory ---
    if not _fast_mode:
        try:
            from chat_app.episodic_memory import get_relevant_facts
            facts = await get_relevant_facts(engine, category=None, min_confidence=0.5, limit=5)
            if facts:
                fact_lines = [f"- {f['rule']}" for f in facts]
                facts_section = "### Learned Patterns (from past interactions):\n" + "\n".join(fact_lines)
                formatted_context = f"{facts_section}\n\n{formatted_context}"
        except (ImportError, KeyError, ValueError, OSError):
            pass

    # --- Inject archival memory (long-term persistent knowledge) ---
    if not _fast_mode:
        try:
            from chat_app.archival_memory import get_archival_memory
            _archival = get_archival_memory()
            _archival_notes = _archival.recall(user_input, user_id=username or "", limit=5)
            if _archival_notes:
                _arch_lines = [f"- {n.content}" for n in _archival_notes]
                _arch_section = "### Archival Memory (long-term knowledge):\n" + "\n".join(_arch_lines)
                formatted_context = f"{_arch_section}\n\n{formatted_context}"
        except (ImportError, KeyError, ValueError, OSError):
            pass

    # --- Confidence Scoring ---
    confidence = None
    try:
        from chat_app.confidence_scorer import score_confidence, format_confidence_for_context
        confidence = score_confidence(
            local_spec_content, memory_chunks, user_input, all_refs, feedback_match,
        )
        conf_note = format_confidence_for_context(confidence)
        formatted_context = f"{conf_note}\n\n{formatted_context}"
    except (ImportError, ValueError, AttributeError):
        pass

    # --- User context note (personalization) ---
    if user_context_note:
        formatted_context = f"[USER PROFILE: {user_context_note}]\n\n{formatted_context}"

    # --- User Learning Profile: inject personalization prompt ---
    try:
        from chat_app.user_profiles import get_profile_manager
        _profile_mgr = get_profile_manager()
        _user_profile = _profile_mgr.get_profile(username or "anonymous")
        _personalization = _user_profile.get_personalization_prompt()
        if _personalization:
            base_system_prompt = f"{_personalization}\n\n---\n\n{base_system_prompt}"
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_response.py", _exc)

    # --- User Persona: inject persona-specific system prompt modifier ---
    try:
        import chainlit as _cl
        _persona_id = user_settings.get("persona") or _cl.user_session.get("persona")
        if _persona_id:
            from chat_app.user_persona import get_persona_prompt_modifier
            _persona_mod = get_persona_prompt_modifier(_persona_id)
            if _persona_mod:
                base_system_prompt = f"[User Persona]\n{_persona_mod}\n\n---\n\n{base_system_prompt}"
    except (ImportError, AttributeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_response.py", _exc)

    # --- Multi-turn conversation context ---
    try:
        from chat_app.conversation_memory import get_conversation_context
        conv_context = get_conversation_context(max_turns=3)
        if conv_context:
            formatted_context = f"{conv_context}\n\n{formatted_context}"
    except (ImportError, KeyError, ValueError):
        pass

    # --- Context compression (if needed) ---
    _compress_tokens = 1500 if _fast_mode else 3000
    try:
        from chat_app.context_compressor import compress_context_if_needed
        formatted_context = compress_context_if_needed(formatted_context, max_tokens=_compress_tokens)
    except (ImportError, ValueError, AttributeError):
        pass

    return formatted_context, base_system_prompt, confidence


# --------------------------------------------------------------------------- #
#  Post-LLM processing — knowledge gaps, auto-explain, profile tips            #
# --------------------------------------------------------------------------- #

# Intent-to-profile mapping for dynamic profile tips
_INTENT_TO_PROFILE = {
    "spl_generation": "spl_expert",
    "spl_optimization": "spl_expert",
    "config_lookup": "config_helper",
    "troubleshooting": "troubleshooter",
    "cribl_pipeline": "cribl_expert",
    "cribl_config": "cribl_expert",
    "observability_metrics": "observability_expert",
    "observability_infra": "observability_expert",
}

_PROFILE_LABELS = {
    "spl_expert": "SPL Expert",
    "config_helper": "Config Helper",
    "troubleshooter": "Troubleshooter",
    "cribl_expert": "Cribl Expert",
    "observability_expert": "Observability Expert",
    "org_expert": "Org Expert",
}


def post_process_response(
    result_text: str,
    user_input: str,
    plan: Any,
    memory_chunks: List[Any],
    current_profile: str,
) -> tuple:
    """Apply knowledge gap detection, auto-explain, and profile tip.

    Returns (result_text, profile_tip_or_none).
    """
    # --- Knowledge Gap Detection ---
    try:
        from chat_app.knowledge_gap_detector import detect_knowledge_gaps, format_gap_suggestions
        gaps = detect_knowledge_gaps(user_input, memory_chunks, chunk_threshold=3)
        gap_suggestion = format_gap_suggestions(gaps)
        if gap_suggestion:
            result_text += gap_suggestion
    except (ImportError, ValueError, KeyError):
        pass

    # --- Auto-Explain: Append SPL explanation when raw SPL pasted ---
    if getattr(plan, 'auto_explain', False):
        try:
            from chat_app.proactive_insights import explain_spl
            explanation = explain_spl(user_input)
            if explanation.steps:
                explain_parts = ["\n\n---\n**Query Breakdown:**"]
                for i, step in enumerate(explanation.steps, 1):
                    explain_parts.append(f"{i}. {step}")
                if explanation.performance_notes:
                    explain_parts.append("\n**Performance Notes:**")
                    for note in explanation.performance_notes:
                        explain_parts.append(f"- {note}")
                explain_parts.append(f"\n*Complexity: {explanation.complexity}*")
                result_text += "\n".join(explain_parts)
        except (ImportError, AttributeError) as _exc:
            logger.debug("[%s] %%s", "pipeline_response.py", _exc)

    # --- Dynamic Profile Tip ---
    profile_tip = None
    try:
        _suggested = _INTENT_TO_PROFILE.get(plan.intent)
        if _suggested and _suggested != current_profile and current_profile == "general":
            _label = _PROFILE_LABELS.get(_suggested, _suggested)
            profile_tip = f"\n\n---\n*Tip: For {plan.intent.replace('_', ' ')} queries, try the **{_label}** profile for better results.*"
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[%s] %%s", "pipeline_response.py", _exc)

    return result_text, profile_tip
