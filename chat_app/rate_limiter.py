"""
Rate limiter for LLM and external service calls.

Uses token bucket algorithm with per-user and global limits.
"""
import time
import logging
from typing import Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """Token bucket rate limiter."""
    rate: float          # tokens per second
    capacity: float      # maximum burst capacity
    tokens: float = 0.0
    last_update: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        self.tokens = self.capacity

    def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens. Returns True if allowed, False if rate limited.
        """
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def wait_time(self) -> float:
        """How many seconds until the next token is available."""
        if self.tokens >= 1:
            return 0.0
        return (1.0 - self.tokens) / self.rate


class RateLimiter:
    """
    Multi-tier rate limiter with per-user and global limits.
    """

    def __init__(
        self,
        global_rate: float = 10.0,     # 10 requests per second globally
        global_capacity: int = 20,      # burst capacity
        user_rate: float = 2.0,         # 2 requests per second per user
        user_capacity: int = 5,         # per-user burst
    ):
        self.global_bucket = TokenBucket(rate=global_rate, capacity=global_capacity)
        self.user_buckets: Dict[str, TokenBucket] = {}
        self.user_rate = user_rate
        self.user_capacity = user_capacity
        self._cleanup_interval = 300  # cleanup stale buckets every 5 min
        self._last_cleanup = time.monotonic()

    def _get_user_bucket(self, user_id: str) -> TokenBucket:
        if user_id not in self.user_buckets:
            self.user_buckets[user_id] = TokenBucket(
                rate=self.user_rate, capacity=self.user_capacity
            )
        return self.user_buckets[user_id]

    def _cleanup_stale(self):
        """Remove user buckets that haven't been used recently."""
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        stale_threshold = now - 600  # 10 minutes
        stale_users = [
            uid for uid, bucket in self.user_buckets.items()
            if bucket.last_update < stale_threshold
        ]
        for uid in stale_users:
            del self.user_buckets[uid]

        self._last_cleanup = now
        if stale_users:
            logger.debug(f"Cleaned up {len(stale_users)} stale rate limiter buckets")

    def check(self, user_id: Optional[str] = None) -> bool:
        """
        Check if a request is allowed.

        Args:
            user_id: Optional user identifier for per-user limiting

        Returns:
            True if request is allowed, False if rate limited
        """
        self._cleanup_stale()

        # Check global limit first
        if not self.global_bucket.acquire():
            logger.warning("Global rate limit exceeded")
            return False

        # Check per-user limit
        if user_id:
            user_bucket = self._get_user_bucket(user_id)
            if not user_bucket.acquire():
                logger.warning(f"Per-user rate limit exceeded for: {user_id}")
                return False

        return True

    def get_wait_time(self, user_id: Optional[str] = None) -> float:
        """Get the minimum wait time before next request is allowed."""
        global_wait = self.global_bucket.wait_time()
        if user_id and user_id in self.user_buckets:
            user_wait = self.user_buckets[user_id].wait_time()
            return max(global_wait, user_wait)
        return global_wait

    def get_status(self) -> dict:
        """Get current rate limiter status."""
        return {
            "global_tokens": round(self.global_bucket.tokens, 2),
            "active_users": len(self.user_buckets),
        }


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter (singleton)."""
    global _rate_limiter
    if _rate_limiter is None:
        from chat_app.settings import get_settings
        cfg = get_settings().rate_limit
        _rate_limiter = RateLimiter(
            global_rate=cfg.global_rate,
            user_rate=cfg.user_rate,
        )
    return _rate_limiter
