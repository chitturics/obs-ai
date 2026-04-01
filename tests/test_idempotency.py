"""Tests for idempotency + dry-run framework."""

import pytest


@pytest.fixture
def store():
    from chat_app.idempotency import IdempotencyStore
    return IdempotencyStore(default_ttl=10, max_entries=100)


class TestIdempotencyStore:

    def test_miss_on_empty(self, store):
        assert store.get("nonexistent") is None

    def test_put_and_get(self, store):
        store.put("key1", {"result": "ok"}, tool="test")
        cached = store.get("key1")
        assert cached is not None
        assert cached["cached"] is True
        assert cached["result"] == {"result": "ok"}
        assert cached["tool"] == "test"

    def test_hit_increments_counter(self, store):
        store.put("key1", "result")
        store.get("key1")
        store.get("key1")
        stats = store.get_stats()
        assert stats["hits"] == 2

    def test_miss_increments_counter(self, store):
        store.get("missing1")
        store.get("missing2")
        stats = store.get_stats()
        assert stats["misses"] == 2

    def test_expired_entry_returns_none(self):
        from chat_app.idempotency import IdempotencyStore
        store = IdempotencyStore(default_ttl=0)  # Immediate expiry
        store.put("key1", "result")
        import time
        time.sleep(0.01)
        assert store.get("key1") is None

    def test_remove_key(self, store):
        store.put("key1", "result")
        assert store.remove("key1") is True
        assert store.get("key1") is None
        assert store.remove("key1") is False  # Already removed

    def test_eviction_on_overflow(self):
        from chat_app.idempotency import IdempotencyStore
        store = IdempotencyStore(max_entries=5)
        for i in range(10):
            store.put(f"key{i}", f"result{i}")
        stats = store.get_stats()
        assert stats["total_stored"] <= 5


class TestMarkInProgress:

    def test_claim_key(self, store):
        assert store.mark_in_progress("key1", tool="test") is True

    def test_cannot_double_claim(self, store):
        store.mark_in_progress("key1")
        assert store.mark_in_progress("key1") is False

    def test_completed_blocks_claim(self, store):
        store.put("key1", "result")
        assert store.mark_in_progress("key1") is False


class TestKeyGeneration:

    def test_deterministic(self):
        from chat_app.idempotency import generate_idempotency_key
        key1 = generate_idempotency_key("tool", {"a": 1}, "user1")
        key2 = generate_idempotency_key("tool", {"a": 1}, "user1")
        assert key1 == key2

    def test_different_params_different_key(self):
        from chat_app.idempotency import generate_idempotency_key
        key1 = generate_idempotency_key("tool", {"a": 1}, "user1")
        key2 = generate_idempotency_key("tool", {"a": 2}, "user1")
        assert key1 != key2

    def test_different_actor_different_key(self):
        from chat_app.idempotency import generate_idempotency_key
        key1 = generate_idempotency_key("tool", {"a": 1}, "user1")
        key2 = generate_idempotency_key("tool", {"a": 1}, "user2")
        assert key1 != key2

    def test_key_length(self):
        from chat_app.idempotency import generate_idempotency_key
        key = generate_idempotency_key("tool", {})
        assert len(key) == 32


class TestDryRunResult:

    def test_to_dict(self):
        from chat_app.idempotency import DryRunResult
        result = DryRunResult(
            tool="update_config",
            would_change={"model": {"old": "llama2", "new": "llama3"}},
            side_effects=["App restart required"],
            reversible=True,
        )
        d = result.to_dict()
        assert d["dry_run"] is True
        assert d["tool"] == "update_config"
        assert "model" in d["would_change"]
        assert len(d["side_effects"]) == 1

    def test_defaults(self):
        from chat_app.idempotency import DryRunResult
        result = DryRunResult(tool="test")
        d = result.to_dict()
        assert d["reversible"] is True
        assert d["approval_required"] is False
        assert d["would_change"] == {}


class TestStats:

    def test_initial_stats(self, store):
        stats = store.get_stats()
        assert stats["active_keys"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_hit_rate(self, store):
        store.put("k1", "v1")
        store.get("k1")  # hit
        store.get("k1")  # hit
        store.get("k2")  # miss
        stats = store.get_stats()
        assert stats["hit_rate"] == pytest.approx(0.667, abs=0.01)
