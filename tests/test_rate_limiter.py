"""Unit tests for rate_limiter.py."""
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chat_app'))

from rate_limiter import TokenBucket, RateLimiter


class TestTokenBucket:
    """Test token bucket algorithm."""

    def test_initial_full_capacity(self):
        bucket = TokenBucket(rate=1.0, capacity=5)
        assert bucket.tokens == 5.0

    def test_acquire_reduces_tokens(self):
        bucket = TokenBucket(rate=1.0, capacity=5)
        assert bucket.acquire() is True
        assert bucket.tokens == 4.0

    def test_acquire_multiple(self):
        bucket = TokenBucket(rate=1.0, capacity=5)
        for _ in range(5):
            assert bucket.acquire() is True
        assert bucket.acquire() is False  # 6th should fail

    def test_tokens_replenish(self):
        bucket = TokenBucket(rate=100.0, capacity=5)
        # Drain all tokens
        for _ in range(5):
            bucket.acquire()
        assert bucket.acquire() is False
        # Wait a bit for replenishment
        time.sleep(0.1)
        assert bucket.acquire() is True

    def test_wait_time(self):
        bucket = TokenBucket(rate=1.0, capacity=1)
        bucket.acquire()
        wait = bucket.wait_time()
        assert wait > 0


class TestRateLimiter:
    """Test multi-tier rate limiter."""

    def test_allows_within_limit(self):
        limiter = RateLimiter(global_rate=100, global_capacity=100, user_rate=10, user_capacity=10)
        assert limiter.check("user1") is True

    def test_global_limit_enforced(self):
        limiter = RateLimiter(global_rate=0.1, global_capacity=2, user_rate=100, user_capacity=100)
        assert limiter.check("user1") is True
        assert limiter.check("user1") is True
        assert limiter.check("user1") is False  # Global limit hit

    def test_per_user_limit_enforced(self):
        limiter = RateLimiter(global_rate=100, global_capacity=100, user_rate=0.1, user_capacity=2)
        assert limiter.check("user1") is True
        assert limiter.check("user1") is True
        assert limiter.check("user1") is False  # Per-user limit hit
        # Different user should still work
        assert limiter.check("user2") is True

    def test_no_user_id(self):
        limiter = RateLimiter(global_rate=100, global_capacity=100)
        assert limiter.check() is True

    def test_get_status(self):
        limiter = RateLimiter()
        limiter.check("user1")
        status = limiter.get_status()
        assert "global_tokens" in status
        assert "active_users" in status
        assert status["active_users"] == 1
