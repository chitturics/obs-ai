"""Query preprocessing: QueryPreprocessor, PreprocessedQuery, HyDE, query expansion.

Extracted from vectorstore_search.py for maintainability.
Re-exported from vectorstore_search.py for backward-compatible imports.
"""
import os
import re
import logging
from dataclasses import dataclass
from typing import Optional
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
# Query Preprocessing: expansion, decomposition, entity extraction
# ---------------------------------------------------------------------------

class QueryPreprocessor:
    """Preprocess queries with domain-specific expansion, decomposition, and entity extraction.

    Usage::

        qp = QueryPreprocessor()
        result = qp.preprocess(query)
        # result.expanded_query  -> used for embedding
        # result.original_query  -> used for keyword matching
        # result.sub_queries     -> decomposed sub-queries (if complex)
        # result.entities        -> extracted key entities
    """

    # Domain-specific synonyms for Splunk/observability terms
    SPLUNK_SYNONYMS: dict[str, list[str]] = {
        "search": ["query", "SPL", "search command"],
        "index": ["data store", "bucket", "repository"],
        "sourcetype": ["source type", "data format", "log type"],
        "dashboard": ["view", "panel", "visualization"],
        "alert": ["saved search", "trigger", "notification"],
        "forwarder": ["UF", "universal forwarder", "HF", "heavy forwarder"],
        "props": ["props.conf", "field extraction", "line breaking"],
        "transforms": ["transforms.conf", "lookup", "field transformation"],
        "inputs": ["inputs.conf", "data input", "modular input"],
        "outputs": ["outputs.conf", "forwarding", "data forwarding"],
        "savedsearches": ["savedsearches.conf", "saved search", "scheduled search", "alert"],
        "macros": ["macros.conf", "search macro", "macro definition"],
        "eventtypes": ["eventtypes.conf", "event type", "event classification"],
        "tags": ["tags.conf", "tag", "field tag"],
        "limits": ["limits.conf", "resource limit", "search limit"],
        "server": ["server.conf", "server configuration", "clustering"],
        "deployment": ["deployment server", "deployment client", "serverclass"],
        "HEC": ["HTTP Event Collector", "HEC token", "event collector"],
        "KV store": ["KVStore", "key-value store", "kvstore"],
        "data model": ["datamodel", "pivot", "accelerated data model"],
        "lookup": ["lookup table", "lookup definition", "automatic lookup"],
        "rex": ["regex extraction", "field extraction", "rex command"],
        "eval": ["calculated field", "eval expression", "eval function"],
        "stats": ["statistics", "aggregation", "stats command"],
        "timechart": ["time series", "time chart", "timechart command"],
        "tstats": ["accelerated search", "tstats command", "data model search"],
        "dedup": ["deduplicate", "remove duplicates", "dedup command"],
        "cluster": ["indexer cluster", "search head cluster", "clustering"],
        "SHC": ["search head cluster", "search head clustering"],
        "IDX": ["indexer", "indexer cluster"],
        "CM": ["cluster manager", "cluster master"],
        "DS": ["deployment server"],
        "Cribl": ["Cribl Stream", "Cribl Edge", "observability pipeline"],
    }

    # Known SPL commands for entity extraction
    _SPL_COMMANDS = {
        "abstract", "accum", "addcoltotals", "addinfo", "addtotals", "analyzefields",
        "anomalies", "anomalousvalue", "append", "appendcols", "appendpipe", "arules",
        "audit", "autoregress", "bin", "bucket", "chart", "cluster", "cofilter",
        "collect", "concurrency", "contingency", "convert", "correlate", "datamodel",
        "dbinspect", "dedup", "delete", "delta", "diff", "dispatch", "erex", "eval",
        "eventcount", "eventstats", "extract", "fieldformat", "fields", "fieldsummary",
        "filldown", "fillnull", "findtypes", "flatten", "foreach", "format", "from",
        "gauge", "gentimes", "geom", "geostats", "head", "highlight", "history",
        "iconify", "input", "inputcsv", "inputlookup", "iplocation", "join", "kmeans",
        "kvform", "loadjob", "localize", "localop", "lookup", "makecontinuous",
        "makemv", "makeresults", "map", "mcollect", "metadata", "metasearch",
        "meventcollect", "mpreview", "msearch", "mstats", "multikv", "multisearch",
        "mvcombine", "mvexpand", "nominals", "outlier", "outputcsv", "outputlookup",
        "outputtext", "overlap", "pivot", "predict", "rangemap", "rare", "regex",
        "reltime", "rename", "replace", "require", "rest", "return", "reverse",
        "rex", "rtorder", "run", "savedsearch", "script", "scrub", "search",
        "searchtxn", "selfjoin", "sendalert", "sendemail", "set", "setfields",
        "sichart", "sirare", "sistats", "sitimechart", "sitop", "sort", "spath",
        "stats", "strcat", "streamstats", "table", "tags", "tail", "timechart",
        "timewrap", "top", "transaction", "transpose", "trendline", "tscollect",
        "tstats", "typeahead", "typelearner", "typer", "union", "uniq", "untable",
        "where", "x11", "xmlkv", "xmlunescape", "xpath", "xyseries",
    }

    # Known .conf file names for entity extraction
    _CONF_FILES = {
        "inputs.conf", "outputs.conf", "props.conf", "transforms.conf",
        "savedsearches.conf", "macros.conf", "indexes.conf", "server.conf",
        "authentication.conf", "authorize.conf", "limits.conf", "web.conf",
        "alert_actions.conf", "app.conf", "commands.conf", "datamodels.conf",
        "deploymentclient.conf", "distsearch.conf", "eventtypes.conf",
        "fields.conf", "health.conf", "serverclass.conf", "tags.conf",
        "times.conf", "workflow_actions.conf",
    }

    # Compiled patterns for entity extraction
    _CONF_ENTITY_PATTERN = re.compile(r'\b([a-z_]+\.conf)\b')
    _SPLUNK_CMD_PATTERN = re.compile(r'\|\s*(\w+)')

    def __init__(self, enabled: bool = True, max_synonyms: int = 2):
        self.enabled = enabled
        self.max_synonyms = max_synonyms

    def preprocess(self, query: str) -> "PreprocessedQuery":
        """Run full preprocessing pipeline on query.

        Returns a PreprocessedQuery with expanded text, sub-queries, and entities.
        """
        if not self.enabled or not query or not query.strip():
            return PreprocessedQuery(
                original_query=query,
                expanded_query=query,
                sub_queries=[],
                entities=[],
            )

        entities = self._extract_entities(query)
        sub_queries = self._decompose_query(query)
        expanded = self._expand_query(query, entities)

        return PreprocessedQuery(
            original_query=query,
            expanded_query=expanded,
            sub_queries=sub_queries,
            entities=entities,
        )

    def _expand_query(self, query: str, entities: list[str]) -> str:
        """Add domain-specific synonyms to the query for better embedding coverage."""
        query_lower = query.lower()
        expansions: list[str] = []

        for term, synonyms in self.SPLUNK_SYNONYMS.items():
            term_lower = term.lower()
            if term_lower in query_lower:
                # Add up to max_synonyms expansions per matched term
                added = 0
                for syn in synonyms:
                    if syn.lower() not in query_lower and added < self.max_synonyms:
                        expansions.append(syn)
                        added += 1

        if expansions:
            expanded = f"{query} ({', '.join(expansions)})"
            logger.debug("[QUERY_EXPAND] '%s' -> '%s'", query[:60], expanded[:120])
            return expanded

        return query

    def _decompose_query(self, query: str) -> list[str]:
        """Split compound queries into sub-queries on 'and', '&', commas."""
        q = query.lower()
        if not any(sep in q for sep in (" and ", " & ", "&", ", ")):
            return []

        # Split on conjunctions: " and ", " & ", "&", ", "
        parts = re.split(r'\s+and\s+|\s*&\s*|,\s+', query, flags=re.IGNORECASE)
        # Keep fragments that are meaningful (2+ words)
        subs = [p.strip() for p in parts if len(p.strip().split()) >= 2]
        if len(subs) < 2:
            return []

        # Propagate question prefix to fragments missing it
        # "what is Splunk & NLS" → ["what is Splunk", "what is NLS"]
        prefix = ""
        for p in ["what is", "what are", "how to", "explain", "describe"]:
            if q.startswith(p):
                prefix = query[:len(p)] + " "
                break
        if prefix:
            subs = [s if s.lower().startswith(prefix.lower().strip()) else prefix + s for s in subs]

        logger.info("[DECOMPOSE] %d sub-queries from '%s': %s", len(subs), query[:50], subs)
        return subs

    def _extract_entities(self, query: str) -> list[str]:
        """Extract key entities: SPL commands, .conf files, field names."""
        entities: list[str] = []
        query_lower = query.lower()

        # Extract SPL commands (from pipe syntax or known command names)
        for match in self._SPLUNK_CMD_PATTERN.finditer(query):
            cmd = match.group(1).lower()
            if cmd in self._SPL_COMMANDS:
                entities.append(f"cmd:{cmd}")

        # Also check for command names mentioned without pipes
        for cmd in self._SPL_COMMANDS:
            if cmd in query_lower and f"cmd:{cmd}" not in entities:
                if re.search(rf'\b{re.escape(cmd)}\b', query_lower):
                    entities.append(f"cmd:{cmd}")

        # Extract .conf file references
        for match in self._CONF_ENTITY_PATTERN.finditer(query_lower):
            conf = match.group(1)
            if conf in self._CONF_FILES:
                entities.append(f"conf:{conf}")

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for e in entities:
            if e not in seen:
                seen.add(e)
                unique.append(e)

        if unique:
            logger.debug("[QUERY_ENTITIES] Extracted: %s", unique)
        return unique


@dataclass(slots=True)
class PreprocessedQuery:
    """Result of query preprocessing."""
    original_query: str       # Original user query (for keyword matching)
    expanded_query: str       # Expanded query (for embedding)
    sub_queries: list[str]    # Decomposed sub-queries (if complex)
    entities: list[str]       # Extracted entities (cmd:X, conf:Y)


# ---------------------------------------------------------------------------
# HyDE (Hypothetical Document Embeddings)
# ---------------------------------------------------------------------------

def _expand_query_template(query: str) -> Optional[str]:
    """Generate a hypothetical document using templates (no LLM needed).

    This provides HyDE-like benefits for common query patterns without
    the latency and CPU cost of an actual LLM call. The hypothetical
    document is embedded and used for retrieval, improving recall for
    conceptual or how-to queries.
    """
    q = query.lower().strip()

    # "What is X?" pattern
    if q.startswith("what is ") or q.startswith("what are "):
        topic = q.replace("what is ", "").replace("what are ", "").strip().rstrip("?")
        return (
            f"{topic} is a component or concept in Splunk and observability platforms. "
            f"It provides capabilities for data analysis, search, and monitoring. "
            f"{topic} is commonly used for log management, security monitoring, "
            f"and IT operations in enterprise environments. "
            f"Key features of {topic} include configuration via .conf files, "
            f"SPL (Search Processing Language) queries, dashboards, and alerts."
        )

    # "How to X" / "How do I X" pattern
    if q.startswith("how to ") or q.startswith("how do i ") or q.startswith("how can i "):
        action = (q.replace("how to ", "")
                   .replace("how do i ", "")
                   .replace("how can i ", "")
                   .strip().rstrip("?"))
        first_word = action.split()[0] if action.split() else "search"
        return (
            f"To {action} in Splunk, follow these steps: "
            f"First, configure the relevant settings in the appropriate .conf file. "
            f"Then use the SPL command or UI to perform the operation. "
            f"Example SPL: | {first_word} ... "
            f"You can also configure this through the Splunk Web interface "
            f"under Settings or via the REST API. "
            f"Refer to the {first_word} command documentation for detailed syntax."
        )

    # "Difference between X and Y" pattern
    diff_match = re.match(
        r'(?:what(?:\'s| is) the )?(?:difference|diff) between (.+?) and (.+?)[\?]?$', q
    )
    if diff_match:
        a, b = diff_match.group(1).strip(), diff_match.group(2).strip()
        return (
            f"{a} and {b} are both components in Splunk/observability. "
            f"{a} is used for specific data processing and configuration tasks. "
            f"{b} provides complementary functionality. "
            f"The key differences include their configuration files, "
            f"use cases, and how they interact with the Splunk architecture. "
            f"Both can be configured via .conf files and managed through the CLI or UI."
        )

    # "Why" pattern
    if q.startswith("why "):
        topic = q.replace("why ", "").strip().rstrip("?")
        return (
            f"The reason for {topic} in Splunk relates to data processing, "
            f"search optimization, or system architecture. "
            f"This behavior is controlled by configuration settings "
            f"and can be adjusted through .conf files or the Splunk Web UI. "
            f"Common causes include resource limits, configuration mismatches, "
            f"or specific feature behaviors documented in the admin manual."
        )

    # "Configure X" / "Set up X" pattern
    if q.startswith(("configure ", "set up ", "setup ")):
        topic = (q.replace("configure ", "")
                  .replace("set up ", "")
                  .replace("setup ", "")
                  .strip().rstrip("?"))
        return (
            f"To configure {topic}, edit the relevant .conf file "
            f"(typically found in $SPLUNK_HOME/etc/system/local/ or an app directory). "
            f"Add or modify the appropriate stanza and settings. "
            f"After making changes, restart Splunk or use the debug/refresh endpoint. "
            f"You can also configure {topic} through Splunk Web under Settings. "
            f"Key parameters include enabled, disabled, and related attributes."
        )

    # "Troubleshoot X" / "Debug X" / "Fix X" pattern
    if q.startswith(("troubleshoot ", "debug ", "fix ", "resolve ")):
        topic = (q.replace("troubleshoot ", "")
                  .replace("debug ", "")
                  .replace("fix ", "")
                  .replace("resolve ", "")
                  .strip().rstrip("?"))
        return (
            f"To troubleshoot {topic} in Splunk, start by checking the internal logs "
            f"(index=_internal) and the splunkd.log file. "
            f"Common causes include misconfigured .conf files, resource constraints, "
            f"network issues, or permission problems. "
            f"Use | rest /services/server/info to verify system status. "
            f"Check limits.conf for resource limits that may affect {topic}."
        )

    return None


async def _generate_hyde_embedding(
    query: str,
    embedding_fn,
) -> Optional[list]:
    """Generate a hypothetical document and embed it for better retrieval.

    Uses template-based expansion (not LLM) for CPU efficiency. The
    hypothetical document provides a better embedding target for
    conceptual queries where the user's short question would not match
    well against longer document chunks.

    Args:
        query: The user query.
        embedding_fn: An object with an ``embed_query(text)`` method.

    Returns:
        An embedding vector, or *None* if HyDE is not applicable.
    """
    try:
        from chat_app.settings import get_settings
        if get_settings().fast_mode:
            return None  # Skip in fast_mode for speed

        hypothetical = _expand_query_template(query)
        if hypothetical and hasattr(embedding_fn, 'embed_query'):
            emb = embedding_fn.embed_query(hypothetical)
            logger.info("[HyDE] Generated hypothetical embedding (len=%d chars)", len(hypothetical))
            return emb
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[HyDE] Failed to generate hypothetical embedding: %s", exc)
    return None


def _is_hyde_enabled() -> bool:
    """Check if HyDE feature is enabled in config.yaml features section."""
    try:
        from chat_app.settings import _load_yaml_config
        cfg = _load_yaml_config()
        return bool(cfg.get("features", {}).get("hyde", True))
    except Exception as _exc:  # broad catch — resilience against all failures
        return True  # Enabled by default


def _is_query_expansion_enabled() -> bool:
    """Check if query_expansion feature is enabled in config.yaml features section."""
    try:
        from chat_app.settings import _load_yaml_config
        cfg = _load_yaml_config()
        return bool(cfg.get("features", {}).get("query_expansion", True))
    except Exception as _exc:  # broad catch — resilience against all failures
        return True  # Enabled by default


# ---------------------------------------------------------------------------
# Hybrid search: keyword scoring for BM25-style blending
# ---------------------------------------------------------------------------

def _keyword_score(query: str, doc_text: str) -> float:
    """Simple keyword overlap score (0-1) for hybrid search blending.

    Computes the fraction of query tokens that appear in the document text.
    Acts as a lightweight BM25-style signal to complement vector similarity.
    """
    query_tokens = set(query.lower().split())
    # Remove very short tokens (articles, prepositions)
    query_tokens = {t for t in query_tokens if len(t) >= 3}
    if not query_tokens:
        return 0.0
    doc_lower = doc_text.lower()
    overlap = sum(1 for t in query_tokens if t in doc_lower)
    return overlap / len(query_tokens)


def _is_hybrid_search_enabled() -> bool:
    """Check if hybrid_search feature flag is enabled in config.yaml."""
    try:
        from chat_app.settings import _load_yaml_config
        cfg = _load_yaml_config()
        return bool(cfg.get("features", {}).get("hybrid_search", False))
    except Exception as _exc:  # broad catch — resilience against all failures
        return False


