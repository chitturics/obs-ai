"""Query analysis, collection selection, and async search.

Extracted from vectorstore_search.py for maintainability.
Re-exported from vectorstore_search.py for backward-compatible imports.
"""
import asyncio
import os
import re
import logging
import traceback
from dataclasses import dataclass
from typing import Optional, NamedTuple, Dict
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


@dataclass(slots=True)
class QueryIntent:
    """Analyzed query intent with extracted features."""
    prefers_conf: bool
    prefers_spl: bool
    is_repo_query: bool
    has_conf_reference: bool
    has_spl_reference: bool
    role_hits: set[str]
    version_tokens: list[str]
    query_tokens: set[str]
    target_app: Optional[str] = None  # Specific app mentioned in query
    target_conf: Optional[str] = None  # Specific .conf file mentioned


@dataclass(slots=True)
class SearchConfig:
    """Configuration for search execution."""
    collections: list[tuple[str, Chroma]]
    weight_map: dict[str, int]
    top_n_per_collection: int
    keep_per_collection: int
    repo_fetch_multiplier: float
    use_parallel: bool = True


class ScoredDocument(NamedTuple):
    """Scored document result."""
    score: float
    source: Optional[str]
    source_url: Optional[str]
    text: str
    collection: str
    metadata: dict


def analyze_query_intent(query: str) -> QueryIntent:
    """
    Analyze user query to extract intent signals.

    Args:
        query: User query string

    Returns:
        QueryIntent with extracted features
    """
    query_lower = query.lower()

    # Token extraction
    query_tokens = {
        tok for tok in _TOKEN_SPLIT_PATTERN.split(query_lower)
        if len(tok) >= 3
    }

    # Extract version tokens
    version_tokens = [
        tok for tok in query_lower.replace("version", " ").split()
        if tok and tok[0].isdigit()
    ]

    # Role detection
    role_hits = {rk for rk in ROLE_KEYWORDS if rk in query_lower}

    # Extract target app from query
    # Patterns: "in app X", "in X app", "for X", "from X", app name in quotes
    target_app = None
    app_patterns = [
        r'(?:in|for|from)\s+(?:app\s+)?["\']?([a-zA-Z0-9_-]+(?:[-_][a-zA-Z0-9_-]+)*)["\']?(?:\s+app)?',
        r'app\s+["\']?([a-zA-Z0-9_-]+(?:[-_][a-zA-Z0-9_-]+)*)["\']?',
        r'["\']([a-zA-Z0-9_-]+(?:[-_][a-zA-Z0-9_-]+)*)["\']',  # Quoted app names
    ]
    for pattern in app_patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            candidate = match.group(1)
            # Filter out common words that aren't app names
            if candidate.lower() not in {'the', 'this', 'that', 'with', 'conf', 'file', 'search', 'splunk'}:
                target_app = candidate
                logger.info(f"[QUERY] Detected target app: {target_app}")
                break

    # Extract target .conf file
    target_conf = None
    conf_match = re.search(r'([a-z_]+\.conf)', query_lower)
    if conf_match:
        target_conf = conf_match.group(1)
        logger.info(f"[QUERY] Detected target conf: {target_conf}")

    return QueryIntent(
        prefers_conf=(
            ".conf" in query_lower
            or "configuration" in query_lower
            or "savedsearch" in query_lower
            or "saved search" in query_lower
            or "saved_search" in query_lower
            or "stanza" in query_lower
            or any(cf in query_lower for cf in [
                "savedsearches", "macros", "inputs.conf", "outputs.conf",
                "props.conf", "transforms.conf", "indexes.conf", "server.conf",
                "authentication.conf", "authorize.conf", "limits.conf",
            ])
        ),
        prefers_spl=any(kw in query_lower for kw in SPL_KEYWORDS),
        is_repo_query=any(kw in query_lower for kw in REPO_KEYWORDS),
        has_conf_reference=bool(_CONF_FILE_PATTERN.search(query_lower)),
        has_spl_reference=any(cmd in query_lower for cmd in SPL_KEYWORDS),
        role_hits=role_hits,
        version_tokens=version_tokens,
        query_tokens=query_tokens,
        target_app=target_app,
        target_conf=target_conf,
    )


def select_collections_and_weights(
    intent: QueryIntent,
    available_collections: list[tuple[str, Chroma]],
    profile: Optional[str] = None,
    strategy=None,
    weight_map_override: Optional[Dict[str, int]] = None
) -> SearchConfig:
    """
    Select which collections to search based on intent and profile.

    Args:
        intent: Analyzed query intent
        available_collections: List of (name, client) tuples
        profile: Optional profile name
        strategy: Optional retrieval strategy from profiles
        weight_map_override: Optional override for the weight map

    Returns:
        SearchConfig with collections and weights
    """
    # Use strategy if available, otherwise use intent-based weights
    if strategy:
        weight_map = strategy.weight_map.copy()
        top_n = strategy.top_n_per_collection
        keep_n = strategy.keep_per_collection
        repo_multiplier = 1.0
    else:
        # Intent-based weight selection
        if intent.is_repo_query or intent.has_conf_reference or intent.prefers_conf:
            # REPO-CENTRIC
            logger.info("[SEARCH] REPO-CENTRIC query detected")
            weight_map = {
                "org_repo_mxbai": 100,
                "feedback_qa": 25,
                "secondary_specs": 5,
                "spl_commands_mxbai": 5,
                "local_docs_mxbai": 2,
                "cribl_docs_mxbai": 2,
                "primary": 1,
            }
            repo_multiplier = 4.0
        elif intent.has_spl_reference:
            # SPL-CENTRIC
            logger.info("[SEARCH] SPL-CENTRIC query detected")
            weight_map = {
                "spl_commands_mxbai": 100,
                "feedback_qa": 25,
                "org_repo_mxbai": 8,
                "secondary_specs": 3,
                "local_docs_mxbai": 2,
                "cribl_docs_mxbai": 2,
                "primary": 1,
            }
            repo_multiplier = 1.0
        else:
            # GENERAL/SPEC
            logger.info("[SEARCH] GENERAL/SPEC query detected")
            weight_map = {
                "secondary_specs": 50,
                "feedback_qa": 25,
                "spl_commands_mxbai": 10,
                "org_repo_mxbai": 8,
                "local_docs_mxbai": 5,
                "cribl_docs_mxbai": 5,
                "primary": 3,
            }
            repo_multiplier = 1.0

        top_n = 15
        keep_n = 8

    if weight_map_override:
        weight_map = weight_map_override
        logger.info(f"[SEARCH] Using weight map override: {weight_map}")

    # Apply adaptive learning adjustments from feedback
    try:
        from self_adaptive_rag import get_adaptive_multipliers
        adjusted = get_adaptive_multipliers(weight_map)
        if adjusted != weight_map:
            logger.info(f"[SEARCH] Adaptive weights applied: {adjusted}")
            weight_map = adjusted
    except Exception as _exc:  # broad catch — resilience against all failures
        pass  # Adaptive RAG is optional

    # Prune low-weight collections when there is a clear dominant source
    max_weight = max(weight_map.values()) if weight_map else 1
    if max_weight >= 50:
        query_lower = intent.raw_query.lower() if hasattr(intent, 'raw_query') and intent.raw_query else ""
        pruned = {}
        for name, w in weight_map.items():
            if w <= 2:
                # Keep cribl_docs only if "cribl" appears in query
                if name == "cribl_docs_mxbai" and "cribl" in query_lower:
                    pruned[name] = w
                    continue
                logger.debug("[SEARCH] Pruning low-weight collection %s (weight=%d)", name, w)
                continue
            pruned[name] = w
        if pruned:
            weight_map = pruned

    # Filter available_collections to only those in weight_map
    filtered_collections = [
        (name, client) for name, client in available_collections
        if name in weight_map
    ]

    return SearchConfig(
        collections=filtered_collections,
        weight_map=weight_map,
        top_n_per_collection=top_n,
        keep_per_collection=keep_n,
        repo_fetch_multiplier=repo_multiplier,
        use_parallel=True
    )


def _strip_history(text: str) -> str:
    """
    Remove Q&A history and date prefixes from text.

    Args:
        text: Input text

    Returns:
        Cleaned text
    """
    lines = []
    for line in text.splitlines():
        low = line.lower()
        # Skip Q&A history lines
        if "| q:" in low or "| a:" in low:
            continue
        # Skip date lines
        if _DATE_PATTERN.match(line):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


def _token_overlap_score(text: str, query_tokens: set[str]) -> int:
    """
    Calculate token overlap score between text and query.

    Args:
        text: Document text
        query_tokens: Set of query tokens

    Returns:
        Overlap count
    """
    text_lower = text.lower()
    return sum(1 for tok in query_tokens if tok in text_lower)


async def _search_collection_async(
    client: Chroma,
    coll_name: str,
    query: str,
    k_fetch: int,
    query_embedding: list = None,
) -> tuple[str, list]:
    """
    Search a single collection asynchronously.

    Args:
        client: Chroma client for collection
        coll_name: Collection name
        query: Query string
        k_fetch: Number of results to fetch
        query_embedding: Pre-computed query embedding vector (avoids redundant Ollama calls)

    Returns:
        (collection_name, documents) tuple
    """
    loop = asyncio.get_running_loop()

    def _search_sync():
        """Synchronous search function to run in executor"""
        try:
            logger.info(f"[SEARCH] Searching {coll_name} with k={k_fetch}")
            # Use pre-computed embedding if available (avoids N embedding calls)
            if query_embedding is not None:
                try:
                    results_with_scores = client.similarity_search_by_vector_with_relevance_scores(
                        query_embedding, k=k_fetch
                    )
                    docs = []
                    for doc, score in results_with_scores:
                        doc.metadata["_vector_similarity"] = max(0.0, score)
                        docs.append(doc)
                    logger.info(f"[SEARCH] {coll_name} returned {len(docs)} results (pre-embedded, with scores)")
                    return docs
                except (AttributeError, TypeError):
                    # Fallback: try similarity_search_by_vector without scores
                    try:
                        res = client.similarity_search_by_vector(query_embedding, k=k_fetch)
                        logger.info(f"[SEARCH] {coll_name} returned {len(res)} results (pre-embedded, no scores)")
                        return res
                    except (AttributeError, TypeError):
                        pass  # Fall through to text-based search

            # Fallback: text-based search (embeds query internally — slow if done per collection)
            # WARNING: This re-embeds the query via Ollama, adding 10-14s per collection on CPU.
            # This path should only be hit if pre-embedding failed above.
            logger.warning(f"[SEARCH] SLOW PATH: text-based search on {coll_name} (will re-embed query)")
            try:
                results_with_scores = client.similarity_search_with_score(query, k=k_fetch)
                docs = []
                for doc, distance in results_with_scores:
                    similarity = max(0.0, 1.0 - distance / 2.0)
                    doc.metadata["_vector_similarity"] = similarity
                    docs.append(doc)
                logger.info(f"[SEARCH] {coll_name} returned {len(docs)} results (text query, with scores)")
                return docs
            except (AttributeError, TypeError):
                res = client.similarity_search(query, k=k_fetch)
                logger.info(f"[SEARCH] {coll_name} returned {len(res)} results (text query, no scores)")
                return res
        except ResponseError as exc:
            logger.error(f"[SEARCH] similarity_search failed on {coll_name}: {exc}")
            return []
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error(f"[SEARCH] unexpected error on {coll_name}: {exc}\n{traceback.format_exc()}")
            return []

    try:
        docs = await loop.run_in_executor(_SEARCH_EXECUTOR, _search_sync)
        return coll_name, docs
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"[SEARCH] Collection {coll_name} async search failed: {e}")
        return coll_name, []


