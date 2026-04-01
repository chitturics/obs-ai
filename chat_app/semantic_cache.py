"""
Semantic cache for similar queries using embedding similarity.
Uses LangChain OllamaEmbeddings when available, falls back to trigram hashing.
"""
import hashlib
import time
from typing import Dict, List, Optional, Tuple
from collections import OrderedDict
import logging

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)

_MAX_EMBED_FAILURES = 5


class SemanticCache:
    """
    In-memory semantic cache that matches similar queries.
    Uses Ollama embeddings for true semantic similarity, with trigram fallback.
    """

    def __init__(self, max_size: int = 1000, similarity_threshold: float = 0.85, ttl: int = 3600):
        self.max_size = max_size
        self.similarity_threshold = similarity_threshold
        self.ttl = ttl
        self.cache: OrderedDict[str, Tuple[str, List[float], str, float]] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self._embedder = None
        self._embed_fail_count = 0
        self._embedder_init_attempted = False

    def _get_embedder(self):
        """Lazy-init LangChain OllamaEmbeddings."""
        if self._embedder is not None:
            return self._embedder
        if self._embedder_init_attempted:
            return None
        self._embedder_init_attempted = True
        try:
            from langchain_ollama import OllamaEmbeddings
            cfg = get_settings().ollama
            self._embedder = OllamaEmbeddings(
                model=cfg.embed_model,
                base_url=cfg.base_url,
            )
            logger.info("Semantic cache using OllamaEmbeddings (%s)", cfg.embed_model)
            return self._embedder
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning(f"OllamaEmbeddings init failed, using trigram fallback: {exc}")
            return None

    def _compute_embedding(self, text: str) -> List[float]:
        """Compute embedding using Ollama if available, else trigram fallback."""
        if self._embed_fail_count < _MAX_EMBED_FAILURES:
            embedder = self._get_embedder()
            if embedder is not None:
                try:
                    result = embedder.embed_query(text)
                    self._embed_fail_count = 0  # Reset on success
                    return result
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                    self._embed_fail_count += 1
                    logger.warning(f"Embedding failed ({self._embed_fail_count}/{_MAX_EMBED_FAILURES}): {exc}")

        return self._trigram_fallback(text)

    @staticmethod
    def _trigram_fallback(text: str) -> List[float]:
        """Fallback: fixed-dimension character trigram frequency vector."""
        dim = 256
        embedding = [0.0] * dim
        text_lower = text.lower().strip()
        for i in range(len(text_lower) - 2):
            trigram = text_lower[i:i+3]
            bucket = hash(trigram) % dim
            embedding[bucket] += 1.0
        # L2 normalize
        norm = sum(v * v for v in embedding) ** 0.5
        if norm > 0:
            embedding = [v / norm for v in embedding]
        return embedding

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _is_expired(self, timestamp: float) -> bool:
        return (time.time() - timestamp) > self.ttl

    def _evict_lru(self):
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)

    def _cleanup_expired(self):
        current_time = time.time()
        expired_keys = [
            key for key, (_, _, _, ts) in self.cache.items()
            if (current_time - ts) > self.ttl
        ]
        for key in expired_keys:
            del self.cache[key]

    def get(self, query: str) -> Optional[str]:
        """Get cached response for query if similar query exists."""
        if not query.strip():
            return None

        if len(self.cache) > 0 and (self.hits + self.misses) % 100 == 0:
            self._cleanup_expired()

        query_embedding = self._compute_embedding(query)

        best_match = None
        best_similarity = 0.0

        for cached_query, cached_emb, cached_response, ts in self.cache.values():
            if self._is_expired(ts):
                continue

            similarity = self._cosine_similarity(query_embedding, cached_emb)
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = (cached_query, cached_response)

        if best_match and best_similarity >= self.similarity_threshold:
            self.hits += 1
            logger.info(f"Cache HIT (sim={best_similarity:.3f}): '{query[:50]}...'")
            return best_match[1]

        self.misses += 1
        return None

    def set(self, query: str, response: str):
        """Cache response for query."""
        if not query.strip() or not response.strip():
            return

        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        query_embedding = self._compute_embedding(query)
        timestamp = time.time()

        self._evict_lru()

        if query_hash in self.cache:
            del self.cache[query_hash]

        self.cache[query_hash] = (query, query_embedding, response, timestamp)

    def clear(self):
        self.cache.clear()
        self.hits = 0
        self.misses = 0

    def get_stats(self) -> Dict[str, any]:
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0.0
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate,
            "threshold": self.similarity_threshold,
            "using_embeddings": self._embedder is not None and self._embed_fail_count < _MAX_EMBED_FAILURES,
        }


# Global instance
_semantic_cache: Optional[SemanticCache] = None


def get_semantic_cache() -> SemanticCache:
    """Get global semantic cache instance (singleton)."""
    global _semantic_cache
    if _semantic_cache is None:
        _semantic_cache = SemanticCache(
            max_size=1000,
            similarity_threshold=0.85,
            ttl=3600,
        )
    return _semantic_cache
