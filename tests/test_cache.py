"""Unit tests for cache.py - testing non-Redis parts."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chat_app'))

from cache import generate_cache_key


class TestCacheKeyGeneration:
    """Test cache key generation."""

    def test_deterministic_keys(self):
        key1 = generate_cache_key("query", "test input", "hash123")
        key2 = generate_cache_key("query", "test input", "hash123")
        assert key1 == key2

    def test_different_inputs_different_keys(self):
        key1 = generate_cache_key("query", "input1", "hash123")
        key2 = generate_cache_key("query", "input2", "hash123")
        assert key1 != key2

    def test_prefix_included(self):
        key = generate_cache_key("query", "test")
        assert key.startswith("query:")

    def test_kwargs_affect_key(self):
        key1 = generate_cache_key("vector", "test", k=5)
        key2 = generate_cache_key("vector", "test", k=10)
        assert key1 != key2
