"""Pipeline Retrieval Stage — context retrieval from ChromaDB and local specs.

Extracted from message_handler.py per ADR-002.
Contains: retrieve_context() and retrieval helper functions.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import chainlit as cl

from cache import get_cached_vector_results, cache_vector_results
from vectorstore import search_similar_chunks
from context_builder import (
    detect_config_context,
    find_local_spec_file,
    extract_spec_stanzas,
    merge_subquery_chunks,
)
from negative_feedback import filter_negative_results
from self_adaptive_rag import get_adaptive_multipliers
from prometheus_metrics import record_cache_hit, record_cache_miss
from query_router import route_query
from chat_app.registry import Intent
from chat_app.utils import import_optional_module
from chat_app.message_context import MessageHandlerContext

PROFILES_AVAILABLE, profiles_imports = import_optional_module(
    'profiles', ['detect_profile_from_query', 'get_profile_prompt', 'get_retrieval_strategy']
)

logger = logging.getLogger(__name__)


def _simplify_query_for_retrieval(user_input: str) -> str:
    """
    Simplify a user query by stripping SPL syntax and filler words
    to get core semantic terms for better vector search.

    Example: "optimize index=main sourcetype=access_combined | stats count by status"
          -> "optimize access combined stats count status"
    """
    text = user_input.strip()
    # Strip SPL operators and syntax
    text = re.sub(r'\|\s*\w+', ' ', text)               # | stats, | eval etc.
    text = re.sub(r'\b(index|sourcetype|source|host)\s*=\s*\S+', ' ', text)  # field=value
    text = re.sub(r'\b(earliest|latest)\s*=\s*\S+', ' ', text)
    text = re.sub(r'[|=\[\]{}()"\'`]', ' ', text)       # Special chars
    text = re.sub(r'\b(by|as|where|OR|AND|NOT)\b', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    # Only return if it's meaningful (at least 2 words)
    if len(text.split()) >= 2:
        return text
    return user_input


async def retrieve_context(
    user_input: str,
    context: "MessageHandlerContext",
    user_settings: Dict[str, Any],
    profiles_available: bool,
    current_profile: str,
    map_source_to_url: Any,
    SPEC_STATIC_ROOT: str,
    LOCAL_DOCS_ROOT: str,
    SPEC_SRC_ROOT: str,
) -> Tuple[List[Any], List[str], List[str], Optional[str], str, bool, List[str]]:
    """Retrieves context from ChromaDB."""
    conf_files, stanza_hint = detect_config_context(user_input)
    input_lower = user_input.lower()
    has_conf_context = bool(conf_files) or any(kw in input_lower for kw in [
        'savedsearch', 'saved search', 'saved_search', 'stanza',
        'savedsearches', 'inputs.conf', 'props.conf', 'transforms.conf',
    ])

    local_spec_content = []
    local_spec_refs = []
    if has_conf_context:
        spec_search_roots = [SPEC_STATIC_ROOT, SPEC_SRC_ROOT, LOCAL_DOCS_ROOT]
        for conf_name in conf_files:
            spec_file = find_local_spec_file(conf_name, spec_search_roots)
            if spec_file:
                stanzas = extract_spec_stanzas(spec_file, stanza_hint, limit=2)
                local_spec_content.extend(stanzas)
                spec_url = map_source_to_url(f"file://{spec_file}")
                if spec_url and spec_url not in local_spec_refs:
                    local_spec_refs.append(spec_url)

    plan = route_query(user_input, user_settings)
    is_compound = plan.is_compound
    sub_queries = plan.sub_queries

    # Check for sequential multi-step queries
    is_sequential = False
    sequential_steps = []
    try:
        from chat_app.query_planner import detect_sequential_query
        seq_result = detect_sequential_query(user_input)
        if seq_result.is_sequential:
            is_sequential = True
            sequential_steps = seq_result.steps
            pass  # sequential info captured in pipeline summary
    except (ImportError, AttributeError, ValueError):
        pass

    detected_profile = None
    weight_map = None
    if profiles_available:
        get_retrieval_strategy = profiles_imports['get_retrieval_strategy']
        detect_profile_from_query = profiles_imports['detect_profile_from_query']
        detected_profile = detect_profile_from_query(user_input)
        if not detected_profile and current_profile and current_profile != "general":
            detected_profile = current_profile
            pass  # profile info captured in pipeline summary

        strategy = get_retrieval_strategy(detected_profile)
        base_weights = strategy.weight_map
        weight_map = get_adaptive_multipliers(base_weights, intent=plan.intent or "")

    search_depth = int(user_settings.get("search_depth", 5))
    k_multiplier = int(user_settings.get("k_multiplier", context.settings.retrieval.k_multiplier))
    k_main = max(6, search_depth * k_multiplier)
    k_sub = max(3, search_depth * (k_multiplier // 2))

    # --- GraphRAG: Expand query using KG relationships ---
    graphrag_query = user_input
    try:
        from chat_app.knowledge_graph import get_knowledge_graph as _get_kg
        _kg = _get_kg()
        if _kg:
            expansion_terms = _kg.expand_query_with_graph(
                user_input, plan.intent if plan else "general_qa", max_terms=6,
            )
            if expansion_terms:
                graphrag_query = user_input + " " + " ".join(expansion_terms)
    except (ImportError, AttributeError, ValueError):
        pass

    cached_chunks = await get_cached_vector_results(user_input, k=k_main)
    chroma_source = "cache"

    if cached_chunks and not is_compound and not is_sequential:
        memory_chunks = cached_chunks
        record_cache_hit()
    else:
        record_cache_miss()
        if is_sequential and sequential_steps:
            # Sequential multi-step retrieval
            try:
                from chat_app.query_planner import execute_sequential_retrieval
                memory_chunks, step_summaries = await execute_sequential_retrieval(
                    steps=sequential_steps,
                    search_func=search_similar_chunks,
                    store=context.vector_store,
                    k=k_main,
                    profile=detected_profile,
                    weight_map=weight_map if profiles_available else None,
                    user_settings=user_settings,
                )
                pass  # step summaries in pipeline summary
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.warning("[RETRIEVAL] sequential_fallback reason=%s", exc)
                memory_chunks = await cl.make_async(search_similar_chunks)(
                    context.vector_store, user_input, k=k_main, profile=detected_profile, weight_map_override=weight_map, user_settings=user_settings
                )
        elif is_compound and sub_queries:
            all_chunks = []
            for sub_q in sub_queries:
                sub_chunks = await cl.make_async(search_similar_chunks)(
                    context.vector_store, sub_q, k=k_sub, profile=detected_profile, weight_map_override=weight_map, user_settings=user_settings
                )
                all_chunks.append(sub_chunks)
            memory_chunks = merge_subquery_chunks(all_chunks, k=k_main, sub_queries=sub_queries)

            # For compare_commands intent, build structured comparison context
            if plan.intent == Intent.COMPARE_COMMANDS and len(all_chunks) > 1:
                try:
                    from chat_app.context_builder import build_comparison_context
                    comparison_context = build_comparison_context(all_chunks, sub_queries)
                    if comparison_context:
                        # Store for later injection into formatted_context
                        plan.extra_context = comparison_context
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                    logger.debug("[%s] %s", "pipeline_retrieval.py", exc)
        else:
            # Use GraphRAG-expanded query for richer retrieval
            memory_chunks = await cl.make_async(search_similar_chunks)(
                context.vector_store, graphrag_query, k=k_main, profile=detected_profile, weight_map_override=weight_map, user_settings=user_settings
            )

        chroma_source = "chromadb"
        if not is_compound:
            await cache_vector_results(user_input, memory_chunks, k=k_main)

    # --- Retrieval fallback strategies ---
    # Only trigger fallback if ZERO results — single result is enough for LLM context.
    # Previous threshold of 3 caused expensive double/triple searches on most queries.
    MIN_CHUNKS_BEFORE_FALLBACK = 1
    if len(memory_chunks) < MIN_CHUNKS_BEFORE_FALLBACK and not is_compound:
        # Strategy 1: Retry with "general" profile (no bias) and higher k
        if detected_profile and detected_profile != "general":
            try:
                fallback_chunks = await cl.make_async(search_similar_chunks)(
                    context.vector_store, user_input, k=k_main * 2,
                    profile="general", weight_map_override=None, user_settings=user_settings,
                )
                if len(fallback_chunks) > len(memory_chunks):
                    memory_chunks = fallback_chunks
                    chroma_source = "chromadb_fallback"
            except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as _exc:
                logger.debug("[%s] %%s", "pipeline_retrieval.py", _exc)

        # Strategy 2: Simplify query only if still zero results
        if len(memory_chunks) < MIN_CHUNKS_BEFORE_FALLBACK:
            simplified = _simplify_query_for_retrieval(user_input)
            if simplified and simplified != user_input:
                try:
                    fallback_chunks = await cl.make_async(search_similar_chunks)(
                        context.vector_store, simplified, k=k_main,
                        profile=detected_profile, weight_map_override=weight_map, user_settings=user_settings,
                    )
                    if len(fallback_chunks) > len(memory_chunks):
                        memory_chunks = fallback_chunks
                        chroma_source = "chromadb_fallback"
                except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as _exc:
                    logger.debug("[%s] %%s", "pipeline_retrieval.py", _exc)

    if memory_chunks:
        memory_chunks = await cl.make_async(filter_negative_results)(memory_chunks, user_input)

    if profiles_available and memory_chunks:
        detect_profile_from_query = profiles_imports['detect_profile_from_query']
        profile_after = detect_profile_from_query(user_input, memory_chunks)
        if profile_after and profile_after != detected_profile:
            detected_profile = profile_after

    return memory_chunks, local_spec_content, local_spec_refs, detected_profile, chroma_source, has_conf_context, conf_files
