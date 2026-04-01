"""
Refactored vector store search with parallelization and better structure.

This module is the main entry point for vector search operations.
Implementation is split for maintainability:
    vs_preprocess.py  — QueryPreprocessor, PreprocessedQuery, query expansion
    vs_analysis.py    — QueryIntent, SearchConfig, ScoredDocument, analyze_query_intent,
                        select_collections_and_weights, _search_collection_async
    vs_scoring.py     — score_document, deduplicate_results, merge_and_deduplicate_global

All split classes and functions are re-exported here for backward-compatible imports.
"""

__all__ = [
    "search_similar_chunks_parallel",
    "analyze_query_intent",
    "select_collections_and_weights",
    "score_document",
    "QueryIntent",
    "SearchConfig",
    "ScoredDocument",
    "QueryPreprocessor",
    "_keyword_score",
    "_is_hybrid_search_enabled",
    "_generate_hyde_embedding",
    "_expand_query_template",
]

import asyncio
import os
import re
import logging
from typing import Optional, Dict
from concurrent.futures import ThreadPoolExecutor

from langchain_chroma import Chroma

# Optional org context module (loaded once, not per-document)
try:
    from obsai_context import calculate_context_boost, extract_app_context  # noqa: F401
    _ORG_CONTEXT_AVAILABLE = True
except ImportError:
    _ORG_CONTEXT_AVAILABLE = False

# Handle chromadb version differences for ResponseError
try:
    from chromadb.errors import ResponseError  # noqa: F401
except ImportError:
    try:
        from chromadb import ResponseError
    except ImportError:
        # Fallback: create a stub exception if chromadb doesn't have ResponseError
        class ResponseError(Exception):
            """Stub for chromadb ResponseError when not available"""
            pass

logger = logging.getLogger(__name__)

# Module-level compiled regex patterns (performance optimization)
_TOKEN_SPLIT_PATTERN = re.compile(r'[^a-z0-9]+')
_CONF_FILE_PATTERN = re.compile(r'\b\w+\.conf\b')
_VERSION_PATTERN = re.compile(r'\b\d+(?:\.\d+)*\b')
_USER_HISTORY_PATTERN = re.compile(r'^User:[^\n]+\n')
_DATE_PATTERN = re.compile(r'^20\d{2}-\d{2}-\d{2}')

# Module-level executor for I/O operations
_SEARCH_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="vector_search")

# Constants
ROLE_KEYWORDS = {
    "indexer", "search head", "searchhead", "forwarder",
    "deployment server", "cluster", "standalone"
}

REPO_KEYWORDS = {
    "repo", "repository", "our", "my", "organization", "org", "custom", "local"
}

# Minimum score a document must have before surrounding context chunks are fetched.
# weight=100 → base 1000, weight=50 → base 500.  Default 200 lets most weighted
# collections qualify while filtering out noise from weight-1 collections.
CONTEXT_CHUNK_MIN_SCORE = int(os.getenv("CONTEXT_CHUNK_MIN_SCORE", "200"))

SPL_KEYWORDS = {
    "timechart", "stats", "search", "eval", "where", "rename",
    "table", "chart", "tstats", "dedup", "sort", "fields"
}


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Re-exports from sub-modules (backward-compatible imports)
# ---------------------------------------------------------------------------

from chat_app.vs_preprocess import (  # noqa: F401
    QueryPreprocessor,
    PreprocessedQuery,
    _expand_query_template,
    _generate_hyde_embedding,
    _is_hyde_enabled,
    _is_query_expansion_enabled,
    _keyword_score,
    _is_hybrid_search_enabled,
)

from chat_app.vs_analysis import (  # noqa: F401
    QueryIntent,
    SearchConfig,
    ScoredDocument,
    analyze_query_intent,
    select_collections_and_weights,
    _strip_history,
    _token_overlap_score,
    _search_collection_async,
)

from chat_app.vs_scoring import (  # noqa: F401
    score_document,
    deduplicate_results,
    merge_and_deduplicate_global,
)


async def search_similar_chunks_parallel(
    store: Chroma,
    query: str,
    k: int = 4,
    profile: Optional[str] = None,
    get_surrounding_chunks_func=None,
    public_url_mapper=None,
    weight_map_override: Optional[Dict[str, int]] = None,
    user_settings: Optional[Dict] = None
) -> list[dict]:
    """
    Search for similar chunks across collections with parallelization.

    This is a refactored, parallelized version of the original search_similar_chunks.

    Args:
        store: Primary Chroma vector store
        query: User query string
        k: Number of results to return
        profile: Optional profile override
        get_surrounding_chunks_func: Function to get context chunks
        public_url_mapper: Function to map source paths to public URLs
        user_settings: Optional dictionary of user chat settings.

    Returns:
        List of relevant documents with metadata
    """
    logger.info(f"[SEARCH] Parallel search started: '{query[:100]}', k={k}, profile={profile}")
    user_settings = user_settings or {}

    if not store or not query:
        logger.warning("[SEARCH] Empty store or query, returning empty results")
        return []

    # Step 0: Query preprocessing (expansion, decomposition, entity extraction)
    preprocessed = None
    embedding_query = query  # Query text used for embedding (may be expanded)
    if _is_query_expansion_enabled():
        try:
            qp = QueryPreprocessor(enabled=True)
            preprocessed = qp.preprocess(query)
            embedding_query = preprocessed.expanded_query
            if preprocessed.entities:
                logger.info(f"[SEARCH] Extracted entities: {preprocessed.entities}")
            if preprocessed.sub_queries:
                logger.info(f"[SEARCH] Decomposed into {len(preprocessed.sub_queries)} sub-queries")
            if embedding_query != query:
                logger.info(f"[SEARCH] Expanded query for embedding: '{embedding_query[:120]}'")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as qp_exc:
            logger.debug("[SEARCH] Query preprocessing failed: %s", qp_exc)

    # Step 1: Analyze query intent (uses original query for keyword matching)
    intent = analyze_query_intent(query)
    logger.info(
        f"[SEARCH] Intent: conf={intent.prefers_conf}, spl={intent.prefers_spl}, "
        f"repo={intent.is_repo_query}"
    )

    # Step 2: Get available collections
    try:
        # Import helper functions
        from vectorstore import (
            ensure_feedback_store,
            ensure_secondary_store,
            ensure_additional_stores,
            _public_url_for_path
        )

        feedback = ensure_feedback_store()
        secondary = ensure_secondary_store()
        additional = ensure_additional_stores()

        # Use provided mapper or fallback
        if public_url_mapper is None:
            public_url_mapper = _public_url_for_path

    except ImportError:
        logger.warning("[SEARCH] Could not import vectorstore helpers")
        feedback = None
        secondary = None
        additional = []
        public_url_mapper = lambda x: None

    # Build collections list
    collections = []

    # Derive actual collection names from store objects (not hardcoded!)
    # The order of additional stores depends on CHROMA_ADDITIONAL_COLLECTIONS env var,
    # so we must read the real name from each store's underlying collection.
    if feedback:
        collections.append(("feedback_qa", feedback))
    for idx, extra in enumerate(additional):
        try:
            coll_obj = getattr(extra, "_collection", None)
            name = coll_obj.name if coll_obj else f"additional_{idx+1}"
        except (AttributeError, TypeError) as _exc:
            name = f"additional_{idx+1}"
        collections.append((name, extra))
    if secondary:
        try:
            sec_obj = getattr(secondary, "_collection", None)
            sec_name = sec_obj.name if sec_obj else "secondary_specs"
        except (AttributeError, TypeError) as _exc:
            sec_name = "secondary_specs"
        collections.append((sec_name, secondary))
    collections.append(("primary", store))

    # Step 3: Get profile strategy if available
    strategy = None
    try:
        from profiles import get_retrieval_strategy, detect_profile_from_query

        if profile is None:
            detected = detect_profile_from_query(query)
            if detected:
                logger.info(f"[SEARCH] Auto-detected profile: {detected}")
                profile = detected

        if profile:
            strategy = get_retrieval_strategy(profile)
            logger.info(f"[SEARCH] Using profile strategy: {strategy.description}")
    except ImportError:
        logger.warning("[SEARCH] profiles.py not available, using intent-based strategy")

    # Step 4: Select collections and weights
    config = select_collections_and_weights(intent, collections, profile, strategy, weight_map_override=weight_map_override)
    logger.info(f"[SEARCH] Selected {len(config.collections)} collections")

    # Step 5: Build search tasks (shared logic for parallel and sequential)
    def _k_fetch_for(coll_name: str) -> int:
        """Determine how many results to fetch for a collection, scaled by weight."""
        if strategy:
            try:
                from profiles import get_fetch_count
                return get_fetch_count(strategy, coll_name)
            except ImportError:
                return config.top_n_per_collection
        if coll_name == "org_repo_mxbai" and config.repo_fetch_multiplier > 1.0:
            return int(config.top_n_per_collection * config.repo_fetch_multiplier)
        # Scale fetch count by collection weight relative to max weight
        w = config.weight_map.get(coll_name, 1)
        max_w = max(config.weight_map.values()) if config.weight_map else 1
        scaled = max(3, config.top_n_per_collection * w // max_w)
        return scaled

    # Step 5b: Pre-embed query ONCE to avoid N embedding calls (one per collection)
    # Uses the expanded query (from query preprocessing) for better embedding coverage.
    _query_embedding = None
    _hyde_embedding = None
    try:
        _embed_start = __import__('time').monotonic()
        _ef = getattr(store, '_embedding_function', None)
        if _ef and hasattr(_ef, 'embed_query'):
            # Embed the expanded query (includes synonyms) for better coverage
            _query_embedding = _ef.embed_query(embedding_query)
            _embed_ms = int((__import__('time').monotonic() - _embed_start) * 1000)
            logger.info(f"[SEARCH] Pre-embedded query in {_embed_ms}ms (dim={len(_query_embedding)})")
            # Record embedding cost
            try:
                from chat_app.cost_tracker import record_llm_cost
                _est_tokens = len(embedding_query) // 4
                record_llm_cost(
                    model="mxbai-embed-large",
                    purpose="embedding",
                    input_tokens=_est_tokens,
                    output_tokens=0,
                    latency_ms=_embed_ms,
                )
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)  # was: pass

            # Step 5c: HyDE — generate hypothetical document embedding for conceptual queries
            if _is_hyde_enabled():
                try:
                    _hyde_embedding = await _generate_hyde_embedding(query, _ef)
                    if _hyde_embedding:
                        logger.info("[SEARCH] HyDE embedding generated, will blend with query embedding")
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _hyde_exc:
                    logger.debug("[SEARCH] HyDE embedding failed: %s", _hyde_exc)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _emb_exc:
        logger.warning(f"[SEARCH] Pre-embedding failed, falling back to per-collection: {_emb_exc}")

    # Build search tasks using the primary query embedding
    search_tasks = [
        _search_collection_async(client, coll_name, query, _k_fetch_for(coll_name),
                                 query_embedding=_query_embedding)
        for coll_name, client in config.collections
    ]

    # If HyDE embedding is available, add a second search pass with it
    # (searches same collections but with the hypothetical document embedding)
    if _hyde_embedding is not None:
        hyde_tasks = [
            _search_collection_async(client, coll_name, query,
                                     max(2, _k_fetch_for(coll_name) // 2),
                                     query_embedding=_hyde_embedding)
            for coll_name, client in config.collections
        ]
        search_tasks.extend(hyde_tasks)
        logger.info(f"[SEARCH] Added {len(hyde_tasks)} HyDE search tasks")

    # If sub-queries exist from decomposition, add searches for each sub-query.
    # Skip in fast_mode — each embed_query call takes 10-14s on CPU Ollama,
    # and the main query embedding already covers the core semantics.
    _skip_sub_embed = False
    try:
        from chat_app.settings import get_settings as _gs
        _skip_sub_embed = _gs().fast_mode
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    if preprocessed and preprocessed.sub_queries and _ef and not _skip_sub_embed:
        for sq in preprocessed.sub_queries[:3]:  # Limit to 3 sub-queries
            try:
                sq_emb = _ef.embed_query(sq)
                for coll_name, client in config.collections:
                    search_tasks.append(
                        _search_collection_async(
                            client, coll_name, sq,
                            max(2, _k_fetch_for(coll_name) // 3),
                            query_embedding=sq_emb,
                        )
                    )
                logger.info(f"[SEARCH] Added sub-query search: '{sq[:60]}'")
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)  # was: pass
    elif preprocessed and preprocessed.sub_queries and _skip_sub_embed:
        logger.info("[SEARCH] Skipping sub-query embedding in fast_mode (saves %d embed calls)",
                     len(preprocessed.sub_queries[:3]))

    # Execute searches (parallel by default, sequential as fallback)
    all_scored_docs = []
    if config.use_parallel:
        logger.info(f"[SEARCH] Executing {len(search_tasks)} parallel searches")
        results = await asyncio.gather(*search_tasks, return_exceptions=True)
    else:
        logger.warning("[SEARCH] Using sequential search (parallel disabled)")
        results = []
        for task in search_tasks:
            try:
                results.append(await task)
            except Exception as exc:  # Broad catch intentional: mirrors asyncio.gather(return_exceptions=True) — stores any task error as a value
                results.append(exc)

    # Score results (same logic regardless of parallel/sequential)
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[SEARCH] Task failed: {result}")
            continue

        coll_name, docs = result
        weight = config.weight_map.get(coll_name, 1)

        for doc in docs:
            scored_doc = score_document(
                doc, coll_name, query, intent, weight, public_url_mapper, user_settings
            )
            if scored_doc:
                all_scored_docs.append(scored_doc)

    logger.info(f"[SEARCH] Retrieved {len(all_scored_docs)} total scored documents")

    # Step 6: Deduplicate per collection
    deduped = deduplicate_results(all_scored_docs, config.keep_per_collection)

    # Step 7: Global merge and dedup
    final_cap = max(k, config.keep_per_collection * len(config.collections))
    final_results = merge_and_deduplicate_global(deduped, final_cap)

    logger.info(f"[SEARCH] Returning {len(final_results)} chunks (cap={final_cap})")

    # Step 8: Add context chunks for top results (if function provided)
    chunks = []
    for doc in final_results:
        context_chunks = []

        if (get_surrounding_chunks_func and
            doc.score >= CONTEXT_CHUNK_MIN_SCORE and
            doc.collection in ["org_repo_mxbai", "spl_commands_mxbai", "secondary_specs"]):

            # Find the client for this collection
            for stored_coll_name, stored_client in config.collections:
                if stored_coll_name == doc.collection:
                    try:
                        surrounding = get_surrounding_chunks_func(
                            stored_client,
                            doc.metadata,
                            context_window=2
                        )
                        if surrounding:
                            context_chunks = [chunk_text for chunk_text, _ in surrounding]
                            logger.info(f"[CONTEXT] Added {len(context_chunks)} context chunks for {doc.source}")
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                        logger.warning(f"[CONTEXT] Failed to get context for {doc.source}: {e}")
                    break

        # Build result dictionary
        chunk_dict = {
            "text": doc.text,
            "source": doc.source,
            "source_url": doc.source_url,
            "collection": doc.collection,
            "score": doc.score,
            "context": context_chunks if context_chunks else None,
        }

        # Include rich metadata for .conf/.spec files
        if doc.metadata:
            for key in ["stanza", "conf_type", "is_savedsearch", "app_type", "app_name", "app_path", "app_subdir", "filename", "full_app_path"]:
                if key in doc.metadata:
                    chunk_dict[key] = doc.metadata[key]

        # If app_name not in metadata, extract from source path using org context
        if _ORG_CONTEXT_AVAILABLE and ("app_name" not in chunk_dict or not chunk_dict.get("app_name")):
            source_path = chunk_dict.get("source", "")
            if source_path:
                try:
                    app_ctx = extract_app_context(source_path)
                    if app_ctx:
                        chunk_dict["app_name"] = app_ctx.app_name
                        if "app_type" not in chunk_dict:
                            chunk_dict["app_type"] = app_ctx.app_type
                        logger.debug(f"[ORG_CONTEXT] Extracted app_name='{app_ctx.app_name}' from {source_path[:60]}")
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                    logger.debug(f"[ORG_CONTEXT] Could not extract app context: {e}")

        chunks.append(chunk_dict)

    # Log top results
    if chunks:
        top5 = [(c.get('collection'), c.get('score'), (c.get('source') or '')[:40]) for c in chunks[:5]]
        logger.info(f"[SEARCH] Top 5 merged: {top5}")

    return chunks
