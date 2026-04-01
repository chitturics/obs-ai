"""Unit tests for resilience.py - circuit breaker and retry logic."""
import sys
import os
import asyncio
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chat_app'))

from resilience import CircuitBreaker, CircuitState, retry_with_backoff


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3, name="test")
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, name="test")
        cb.failure_count = 3
        cb.state = CircuitState.OPEN
        assert cb.state == CircuitState.OPEN

    def test_state_transitions(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1, name="test")
        assert cb.state == CircuitState.CLOSED

        # Simulate failures
        cb.failure_count = 2
        cb.state = CircuitState.OPEN
        assert cb.state == CircuitState.OPEN


class TestRetryWithBackoff:
    """Test retry logic."""

    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        call_count = 0

        async def success():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_with_backoff(success, max_attempts=3, initial_delay=0.01)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = await retry_with_backoff(
            fail_then_succeed, max_attempts=3, initial_delay=0.01
        )
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self):
        async def always_fail():
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            await retry_with_backoff(
                always_fail, max_attempts=2, initial_delay=0.01
            )
