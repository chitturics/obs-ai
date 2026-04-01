"""Tests for the circuit breaker pattern."""

import time
import pytest


@pytest.fixture
def registry():
    from chat_app.circuit_breaker import CircuitBreakerRegistry
    return CircuitBreakerRegistry(
        default_failure_threshold=3,
        default_cooldown_seconds=1,  # Short for testing
        default_success_threshold=2,
    )


class TestCircuitBreakerStates:

    def test_starts_closed(self, registry):
        assert registry.allow_request("tool_a") is True

    def test_opens_after_threshold_failures(self, registry):
        for _ in range(3):
            registry.record_failure("tool_a")
        assert registry.allow_request("tool_a") is False

    def test_stays_closed_below_threshold(self, registry):
        registry.record_failure("tool_a")
        registry.record_failure("tool_a")
        assert registry.allow_request("tool_a") is True

    def test_success_resets_failure_count(self, registry):
        registry.record_failure("tool_a")
        registry.record_failure("tool_a")
        registry.record_success("tool_a")
        registry.record_failure("tool_a")
        registry.record_failure("tool_a")
        # Still needs one more failure to trip
        assert registry.allow_request("tool_a") is True

    def test_half_open_after_cooldown(self, registry):
        for _ in range(3):
            registry.record_failure("tool_a")
        assert registry.allow_request("tool_a") is False

        # Wait for cooldown
        time.sleep(1.1)
        assert registry.allow_request("tool_a") is True  # Half-open

    def test_closes_after_success_in_half_open(self, registry):
        for _ in range(3):
            registry.record_failure("tool_a")
        time.sleep(1.1)

        # Half-open — test requests
        registry.allow_request("tool_a")  # Transitions to half-open
        registry.record_success("tool_a")
        registry.record_success("tool_a")  # success_threshold=2

        # Should be closed again
        status = registry.get_status("tool_a")
        assert status["state"] == "closed"

    def test_reopens_on_failure_in_half_open(self, registry):
        for _ in range(3):
            registry.record_failure("tool_a")
        time.sleep(1.1)

        registry.allow_request("tool_a")
        registry.record_failure("tool_a")  # Fails in half-open

        assert registry.allow_request("tool_a") is False
        status = registry.get_status("tool_a")
        assert status["state"] == "open"


class TestCircuitBreakerRegistry:

    def test_independent_breakers(self, registry):
        for _ in range(3):
            registry.record_failure("tool_a")
        assert registry.allow_request("tool_a") is False
        assert registry.allow_request("tool_b") is True

    def test_manual_reset(self, registry):
        for _ in range(3):
            registry.record_failure("tool_a")
        assert registry.allow_request("tool_a") is False

        registry.reset("tool_a")
        assert registry.allow_request("tool_a") is True

    def test_get_open_circuits(self, registry):
        for _ in range(3):
            registry.record_failure("tool_a")
        for _ in range(3):
            registry.record_failure("tool_b")
        registry.record_success("tool_c")

        open_circuits = registry.get_open_circuits()
        names = [c["name"] for c in open_circuits]
        assert "tool_a" in names
        assert "tool_b" in names
        assert "tool_c" not in names

    def test_get_all_status(self, registry):
        registry.record_success("tool_a")
        registry.record_failure("tool_b")
        status = registry.get_all_status()
        assert len(status) == 2

    def test_get_stats(self, registry):
        for _ in range(3):
            registry.record_failure("tool_a")
        registry.record_success("tool_b")

        stats = registry.get_stats()
        assert stats["total_breakers"] == 2
        assert stats["open"] == 1
        assert stats["closed"] == 1
        assert "tool_a" in stats["open_tools"]

    def test_total_trips_counted(self, registry):
        for _ in range(3):
            registry.record_failure("tool_a")
        time.sleep(1.1)
        registry.allow_request("tool_a")
        registry.record_failure("tool_a")  # Reopen

        status = registry.get_status("tool_a")
        assert status["total_trips"] == 2


class TestCircuitBreakerSerialization:

    def test_to_dict(self, registry):
        registry.record_failure("tool_a")
        status = registry.get_status("tool_a")
        assert "name" in status
        assert "state" in status
        assert "failure_count" in status
        assert "failure_threshold" in status
        assert status["name"] == "tool_a"
        assert status["failure_count"] == 1

    def test_nonexistent_tool(self, registry):
        status = registry.get_status("nonexistent")
        assert status is None
