"""
Startup warmup — pre-populate caches, counters, and verify pipeline health.

Called once after application startup to:
1. Verify ChromaDB connectivity and collection stats
2. Pre-warm the embedding cache with common queries
3. Initialize agent dispatcher and skill executor singletons
4. Record baseline metrics for monitoring
5. Log a structured startup summary
"""

import logging
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

_warmup_complete = False
_warmup_result: Dict[str, Any] = {}


async def run_startup_warmup(vector_store=None, engine=None) -> Dict[str, Any]:
    """
    Run startup warmup tasks. Safe to call multiple times (idempotent).

    Returns a summary dict with warmup results.
    """
    global _warmup_complete, _warmup_result
    if _warmup_complete:
        return _warmup_result

    t0 = time.monotonic()
    result: Dict[str, Any] = {
        "started_at": time.time(),
        "checks": {},
    }

    # 1. Verify ChromaDB collections
    try:
        collections = _check_collections()
        result["checks"]["collections"] = collections
        logger.info(
            "[WARMUP] ChromaDB: %d collections, %d total docs",
            collections["count"], collections["total_docs"],
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        result["checks"]["collections"] = {"error": str(exc)}
        logger.warning("[WARMUP] ChromaDB check failed: %s", exc)

    # 2. Initialize singletons (agent dispatcher, skill executor, KG)
    try:
        singletons = _init_singletons()
        result["checks"]["singletons"] = singletons
        logger.info(
            "[WARMUP] Singletons: agents=%d skills=%d handlers=%d",
            singletons.get("agents", 0),
            singletons.get("skills", 0),
            singletons.get("handlers_resolved", 0),
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        result["checks"]["singletons"] = {"error": str(exc)}
        logger.warning("[WARMUP] Singleton init failed: %s", exc)

    # 3. Pre-warm Redis cache connection
    try:
        redis_ok = _check_redis()
        result["checks"]["redis"] = {"connected": redis_ok}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        result["checks"]["redis"] = {"connected": False, "error": str(exc)}

    # 4. Pre-warm embedding cache with common queries (fire-and-forget)
    try:
        if vector_store:
            _warmup_embeddings(vector_store)
            result["checks"]["embedding_warmup"] = "initiated"
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        result["checks"]["embedding_warmup"] = {"error": str(exc)}

    # 5. Record baseline metrics
    try:
        from chat_app.health_monitor import get_internal_metrics
        metrics = get_internal_metrics()
        metrics.flush()  # Ensure Redis-persisted counters are synced
        result["checks"]["metrics_baseline"] = {
            k: v for k, v in metrics.get_all().get("counters", {}).items() if v > 0
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    elapsed_ms = (time.monotonic() - t0) * 1000
    result["elapsed_ms"] = round(elapsed_ms, 1)
    _warmup_complete = True
    _warmup_result = result

    logger.info(
        "[WARMUP] Startup warmup complete in %.0fms: collections=%s redis=%s singletons=%s",
        elapsed_ms,
        result["checks"].get("collections", {}).get("count", "?"),
        result["checks"].get("redis", {}).get("connected", "?"),
        "ok" if "error" not in result["checks"].get("singletons", {}) else "fail",
    )

    return result


def _check_collections() -> Dict[str, Any]:
    """Check ChromaDB collection stats."""
    import chromadb
    import os

    host = os.getenv("CHROMA_HOST", "localhost")
    port = int(os.getenv("CHROMA_PORT", "8001"))
    client = chromadb.HttpClient(host=host, port=port)

    cols = client.list_collections()
    collection_stats = {}
    total_docs = 0
    for col in cols:
        count = col.count()
        collection_stats[col.name] = count
        total_docs += count

    return {
        "count": len(cols),
        "total_docs": total_docs,
        "collections": collection_stats,
    }


def _init_singletons() -> Dict[str, Any]:
    """Initialize key singletons eagerly."""
    result = {}

    # Agent catalog
    try:
        from chat_app.agent_catalog import get_agent_catalog
        catalog = get_agent_catalog()
        result["agents"] = catalog.count
    except Exception as _exc:  # broad catch — resilience against all failures
        result["agents"] = 0

    # Skill catalog + executor
    try:
        from chat_app.skill_catalog import get_skill_catalog
        from chat_app.skill_executor import get_skill_executor
        sc = get_skill_catalog()
        se = get_skill_executor()
        result["skills"] = sc.count

        # Count resolved handlers
        resolved = 0
        for skill_dict in sc.list_all():
            handler_key = skill_dict.get("handler_key", "")
            if handler_key:
                source, _ = se.resolve_handler(handler_key)
                if source:
                    resolved += 1
        result["handlers_resolved"] = resolved
    except Exception as _exc:  # broad catch — resilience against all failures
        result["skills"] = 0
        result["handlers_resolved"] = 0

    # Agent dispatcher (triggers quality restore from Redis)
    try:
        from chat_app.agent_dispatcher import get_agent_dispatcher
        get_agent_dispatcher()
        result["dispatcher"] = "ok"
    except Exception as _exc:  # broad catch — resilience against all failures
        result["dispatcher"] = "error"

    # Knowledge graph
    try:
        from chat_app.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        if kg:
            stats = kg.get_stats()
            result["knowledge_graph"] = {
                "entities": stats.get("total_entities", 0),
                "relationships": stats.get("total_relationships", 0),
            }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    return result


def _check_redis() -> bool:
    """Check Redis connectivity."""
    try:
        import redis
        from chat_app.settings import get_settings
        cfg = get_settings().cache
        if not cfg.enabled:
            return False
        r = redis.Redis(
            host=cfg.host, port=cfg.port,
            password=cfg.password, decode_responses=True,
            socket_connect_timeout=2,
        )
        return r.ping()
    except Exception as _exc:  # broad catch — resilience against all failures
        return False


def _warmup_embeddings(vector_store) -> None:
    """Pre-warm the embedding model by running a few sample queries."""
    warmup_queries = [
        "How to configure inputs.conf",
        "SPL search command syntax",
        "Splunk deployment best practices",
    ]
    for query in warmup_queries:
        try:
            # This triggers the embedding model to load into memory
            vector_store.similarity_search(query, k=1)
        except Exception as _exc:  # broad catch — resilience against all failures
            break  # If first fails, skip rest


def get_warmup_result() -> Dict[str, Any]:
    """Return the warmup result (empty dict if not yet run)."""
    return _warmup_result


def is_warmup_complete() -> bool:
    """Check if warmup has been run."""
    return _warmup_complete
