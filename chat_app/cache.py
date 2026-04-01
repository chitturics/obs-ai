"""
Redis caching layer for query responses and vector store results.
"""
import hashlib
import json
from typing import Optional, Any, List
import logging

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)


class CacheClient:
    """Redis cache client with automatic serialization and reconnection."""

    def __init__(self):
        cfg = get_settings().cache
        self.enabled = cfg.enabled
        self.ttl = cfg.ttl
        self.salt = cfg.salt
        self.client = None
        self._cfg = cfg
        self._consecutive_failures = 0
        self._max_failures_before_reconnect = 3

        if self.enabled:
            self._connect()

    def _connect(self):
        """Establish Redis connection."""
        try:
            import redis.asyncio as redis

            self.client = redis.Redis(
                host=self._cfg.host,
                port=self._cfg.port,
                password=self._cfg.password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                socket_keepalive=True,
                retry_on_timeout=True,
            )
            self._consecutive_failures = 0
            logger.info("Redis cache initialized: %s:%s", self._cfg.host, self._cfg.port)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("Redis initialization failed: %s. Caching disabled.", e)
            self.client = None

    def _handle_failure(self, operation: str, error: Exception):
        """Track failures and attempt reconnection after threshold."""
        self._consecutive_failures += 1
        logger.warning("Cache %s failed (%d consecutive): %s",
                       operation, self._consecutive_failures, error)
        if self._consecutive_failures >= self._max_failures_before_reconnect:
            logger.info("Attempting Redis reconnection after %d failures", self._consecutive_failures)
            self._connect()

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if not self.enabled or not self.client:
            return None

        try:
            cached = await self.client.get(key)
            if cached:
                self._consecutive_failures = 0
                logger.debug("Cache hit: %s...", key[:50])
                return json.loads(cached)
            return None
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            self._handle_failure("get", e)
            return None

    async def set(
        self, key: str, value: Any, ttl: Optional[int] = None
    ) -> bool:
        """Set value in cache with optional TTL."""
        if not self.enabled or not self.client:
            return False

        try:
            ttl = ttl or self.ttl
            serialized = json.dumps(value, default=str)
            await self.client.setex(key, ttl, serialized)
            self._consecutive_failures = 0
            logger.debug("Cache set: %s... (TTL: %ss)", key[:50], ttl)
            return True
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            self._handle_failure("set", e)
            return False

    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        if not self.enabled or not self.client:
            return False

        try:
            await self.client.delete(key)
            logger.debug("Cache delete: %s...", key[:50])
            return True
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("Cache delete failed for %s: %s", key[:50], e)
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern."""
        if not self.enabled or not self.client:
            return 0

        try:
            keys = []
            async for key in self.client.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                deleted = await self.client.delete(*keys)
                logger.info("Cache deleted %s keys matching: %s", deleted, pattern)
                return deleted
            return 0
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("Cache delete pattern failed for %s: %s", pattern, e)
            return 0

    async def close(self):
        """Close Redis connection."""
        if self.client:
            await self.client.close()


# Global cache instance
_cache_instance: Optional[CacheClient] = None


def get_cache() -> CacheClient:
    """Get global cache instance (singleton)."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheClient()
    return _cache_instance


def generate_cache_key(prefix: str, *args, **kwargs) -> str:
    """
    Generate deterministic cache key from arguments.

    Args:
        prefix: Key prefix (e.g., 'query', 'vector', 'config')
        *args: Positional arguments to hash
        **kwargs: Keyword arguments to hash

    Returns:
        Cache key string
    """
    salt = get_settings().cache.salt
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    combined = "|".join(key_parts)
    hash_value = hashlib.sha256(f"{salt}|{combined}".encode()).hexdigest()[:16]
    return f"{prefix}:{hash_value}"


async def get_cached_query_response(
    query: str, context_hash: str
) -> Optional[str]:
    """Get cached LLM response for query."""
    cache = get_cache()
    key = generate_cache_key("query", query, context_hash)
    return await cache.get(key)


async def cache_query_response(
    query: str, context_hash: str, response: str, ttl: Optional[int] = None
) -> bool:
    """Cache LLM response for query."""
    cache = get_cache()
    key = generate_cache_key("query", query, context_hash)
    return await cache.set(key, response, ttl)


async def get_cached_vector_results(
    query: str, k: int = 10
) -> Optional[List[dict]]:
    """Get cached vector store search results."""
    cache = get_cache()
    key = generate_cache_key("vector", query)
    cached = await cache.get(key)
    if cached is not None and isinstance(cached, list):
        return cached[:k]
    return cached


async def cache_vector_results(
    query: str, results: List[dict], k: int = 10, ttl: Optional[int] = None
) -> bool:
    """Cache vector store search results."""
    cache = get_cache()
    key = generate_cache_key("vector", query)
    return await cache.set(key, results, ttl)


async def invalidate_query_cache():
    """Invalidate all cached queries (e.g., after knowledge base update)."""
    cache = get_cache()
    deleted = await cache.delete_pattern("query:*")
    logger.info("Invalidated %s cached queries", deleted)


async def invalidate_vector_cache():
    """Invalidate all cached vector results (e.g., after reindexing)."""
    cache = get_cache()
    deleted = await cache.delete_pattern("vector:*")
    logger.info("Invalidated %s cached vector results", deleted)


async def invalidate_specific_query(query: str, context_hash: str) -> bool:
    """Invalidate a specific cached query response (e.g., after negative feedback)."""
    cache = get_cache()
    key = generate_cache_key("query", query, context_hash)
    deleted = await cache.delete(key)
    if deleted:
        logger.info("Invalidated cached response for query: %s...", query[:50])
    return deleted


# ── Prompt Cache ───────────────────────────────────────────────────────

async def get_cached_prompt(
    intent: str, profile: str, context_hash: str,
    agent_hash: str = "", overlay_hash: str = "",
) -> Optional[str]:
    """Get cached assembled prompt by content hash."""
    cache = get_cache()
    key = generate_cache_key("prompt", intent, profile, context_hash, agent_hash, overlay_hash)
    return await cache.get(key)


async def cache_prompt(
    intent: str, profile: str, context_hash: str,
    prompt: str, agent_hash: str = "", overlay_hash: str = "",
    ttl: Optional[int] = None,
) -> bool:
    """Cache an assembled prompt with TTL."""
    cache = get_cache()
    if ttl is None:
        ttl = get_settings().cache.prompt_ttl
    key = generate_cache_key("prompt", intent, profile, context_hash, agent_hash, overlay_hash)
    return await cache.set(key, prompt, ttl)


async def invalidate_prompt_cache() -> int:
    """Invalidate all cached assembled prompts."""
    cache = get_cache()
    deleted = await cache.delete_pattern("prompt:*")
    logger.info("Invalidated %s cached prompts", deleted)
    # Also clear in-memory template cache
    try:
        from chat_app.prompts import invalidate_template_cache
        invalidate_template_cache()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass
    return deleted
