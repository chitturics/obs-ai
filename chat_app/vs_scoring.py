"""Document scoring, deduplication, and result merging.

Extracted from vectorstore_search.py for maintainability.
Re-exported from vectorstore_search.py for backward-compatible imports.
"""
import hashlib
import os
import re
import logging
from typing import Optional, Dict
from concurrent.futures import ThreadPoolExecutor


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
from chat_app.vs_analysis import (
    QueryIntent,
    ScoredDocument,
    _strip_history,
    _token_overlap_score,
)
from chat_app.vs_preprocess import _keyword_score, _is_hybrid_search_enabled


def score_document(
    doc,
    coll_name: str,
    query: str,
    intent: QueryIntent,
    weight: int,
    public_url_mapper,
    user_settings: Optional[Dict] = None
) -> Optional[ScoredDocument]:
    """
    Calculate relevance score for a document with org context awareness.

    Args:
        doc: Document object
        coll_name: Collection name
        query: Original query
        intent: Analyzed query intent
        weight: Collection weight
        public_url_mapper: Function to map source to URL
        user_settings: Optional dictionary of user chat settings.

    Returns:
        ScoredDocument or None if filtered out
    """
    # Validate input
    if not doc:
        logger.warning(f"[SCORE] Received None/empty document from {coll_name}")
        return None

    user_settings = user_settings or {}

    # Extract and clean text
    text = _strip_history(doc.page_content.strip())
    text = _USER_HISTORY_PATTERN.sub("", text)

    # Allow longer text for conf/spec stanzas to preserve full parameters
    doc_filename = str(doc.metadata.get("filename", "")).lower() if hasattr(doc, "metadata") and isinstance(doc.metadata, dict) else ""
    is_conf_chunk = (
        doc_filename.endswith((".conf", ".spec"))
        or (hasattr(doc, "metadata") and isinstance(doc.metadata, dict) and doc.metadata.get("stanza"))
    )
    max_text_len = 3000 if is_conf_chunk else 800
    if len(text) > max_text_len:
        text = text[:max_text_len] + " ..."

    # Extract metadata
    source = None
    source_url = None
    doc_metadata = {}

    try:
        if hasattr(doc, "metadata") and isinstance(doc.metadata, dict):
            doc_metadata = doc.metadata.copy()
            source = doc.metadata.get("source")
            source_url = doc.metadata.get("source_url")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # Get source URL
    if not source_url and source:
        source_url = public_url_mapper(str(source))
        if not source_url:
            basename = os.path.basename(str(source))
            if basename.endswith((".spec", ".conf")):
                source_url = f"/public/documents/specs/{basename}"

    # Base score from weight + vector similarity (if available from similarity_search_with_score)
    vector_sim = doc_metadata.pop("_vector_similarity", 0.0)
    # Vector similarity contributes 0-20 points (scaled from 0.0-1.0)
    score = weight * 10 + int(vector_sim * 20)

    # Hybrid search: blend keyword overlap score when feature flag is enabled
    if _is_hybrid_search_enabled():
        kw_score = _keyword_score(query, text)
        # Keyword score contributes 0-15 points (complements vector similarity)
        hybrid_bonus = int(kw_score * 15)
        if hybrid_bonus > 0:
            score += hybrid_bonus
            logger.debug(f"[HYBRID] +{hybrid_bonus} keyword bonus for {coll_name} (kw_score={kw_score:.2f})")
    src_lower = str(source).lower() if source else ""

    # Filter based on preferences
    if intent.prefers_conf:
        if "feedback:" not in src_lower and ".conf" not in src_lower and "spec" not in src_lower:
            return None  # Filter out non-conf content
        if ".conf" in src_lower or "spec" in src_lower:
            score += 4
    else:
        score += 1

    # Token overlap bonus
    overlap = _token_overlap_score(text, intent.query_tokens)
    score += overlap

    # Pre-compute lowercase text once (used by role + version checks)
    text_lower = text.lower()

    # Role keywords bonus
    if intent.role_hits and any(rk in text_lower for rk in intent.role_hits):
        score += 2

    # Version tokens bonus
    if intent.version_tokens and any(v in text_lower for v in intent.version_tokens):
        score += 1

    # Add bonus based on QA retrieval strategy
    kind = doc_metadata.get("kind", "")
    qa_strategy = user_settings.get("qa_retrieval_strategy", "balanced")
    if qa_strategy == "prefer_generated" and "generated_qa" in kind:
        score += 25  # Significant bonus for generated Q&A
    elif qa_strategy == "prefer_raw" and "generated_qa" not in kind:
        score += 10 # Smaller bonus for raw documents

    # TARGET APP MATCHING - significant boost for matching specified app
    if intent.target_app:
        app_lower = intent.target_app.lower()
        # Check source path for app name
        if app_lower in src_lower:
            score += 15  # Major boost for app match
            logger.info(f"[SCORE] +15 app match: {intent.target_app} in {source}")
        # Also check metadata app_name
        elif doc_metadata.get("app_name", "").lower() == app_lower:
            score += 15
            logger.info(f"[SCORE] +15 app match from metadata: {intent.target_app}")

    # TARGET CONF FILE MATCHING - boost for matching specified .conf file
    if intent.target_conf:
        if intent.target_conf in src_lower:
            score += 10  # Boost for conf file match
            logger.info(f"[SCORE] +10 conf match: {intent.target_conf} in {source}")

    # ORG CONTEXT-AWARE SCORING (app type, deployment target, config type)
    if _ORG_CONTEXT_AVAILABLE:
        try:
            file_path = str(source) if source else ""
            stanza_name = doc_metadata.get("stanza")
            config_type = None

            # Detect config file type from path
            if ".conf" in file_path.lower():
                for conf_type in ["savedsearches", "inputs", "props", "transforms", "macros", "indexes", "outputs"]:
                    if f"{conf_type}.conf" in file_path.lower():
                        config_type = f"{conf_type}.conf"
                        break

            context_boost, reason = calculate_context_boost(
                query=query,
                file_path=file_path,
                stanza_name=stanza_name,
                config_type=config_type,
                metadata=doc_metadata
            )

            if context_boost > 0:
                score += context_boost
                logger.info(f"[ORG_CONTEXT] +{context_boost} for {source}: {reason}")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"[ORG_CONTEXT] Failed to calculate context boost: {e}")

    return ScoredDocument(
        score=score,
        source=source,
        source_url=source_url,
        text=text,
        collection=coll_name,
        metadata=doc_metadata
    )


def deduplicate_results(
    scored_docs: list[ScoredDocument],
    keep_per_collection: int
) -> list[ScoredDocument]:
    """
    Remove duplicate documents per collection.

    Args:
        scored_docs: List of scored documents
        keep_per_collection: Max docs to keep per collection

    Returns:
        Deduplicated and sorted list
    """
    # Group by collection
    per_collection: dict[str, list[ScoredDocument]] = {}

    for doc in scored_docs:
        if doc.collection not in per_collection:
            per_collection[doc.collection] = []
        per_collection[doc.collection].append(doc)

    # Deduplicate and sort each collection
    result = []
    for coll_name, docs in per_collection.items():
        # Dedup within collection (use hash to reduce memory)
        seen_hashes = set()
        unique_docs = []

        for doc in docs:
            h = hashlib.sha256(doc.text.encode("utf-8", errors="ignore")).hexdigest()
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique_docs.append(doc)

        # Sort by score (descending)
        unique_docs.sort(key=lambda x: -x.score)

        # Keep top N per collection
        kept = unique_docs[:keep_per_collection]
        result.extend(kept)

        logger.info(
            f"[SEARCH] {coll_name}: kept {len(kept)} of {len(docs)} "
            f"after dedup (weight={docs[0].score // 10 if docs else 0}x)"
        )

    return result


def merge_and_deduplicate_global(
    per_collection_results: list[ScoredDocument],
    final_cap: int
) -> list[ScoredDocument]:
    """
    Merge results from all collections and remove global duplicates.

    Args:
        per_collection_results: Results from all collections
        final_cap: Maximum number of final results

    Returns:
        Merged and deduplicated list
    """
    # Global deduplication (use hash to reduce memory)
    seen_hashes = set()
    unique_docs = []

    for doc in per_collection_results:
        h = hashlib.sha256(doc.text.encode("utf-8", errors="ignore")).hexdigest()
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_docs.append(doc)

    # Sort by score (descending), then collection, then source
    unique_docs.sort(
        key=lambda x: (
            -x.score,
            x.collection,
            str(x.source) if x.source else "",
            x.text[:40]
        )
    )

    return unique_docs[:final_cap]

