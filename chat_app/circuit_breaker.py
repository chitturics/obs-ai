"""Circuit Breaker — auto-disable noisy/failing tools with recovery.

Implements the circuit breaker pattern for tool/skill execution:
- **CLOSED**: Normal operation, failures counted
- **OPEN**: Tool disabled after threshold failures, returns fast error
- **HALF_OPEN**: After cooldown, allows one test request through

When a tool's circuit opens:
- Immediate error return (no execution attempted)
- Status banner surfaced via API for UI display
- Audit log records the state change
- After cooldown, a single request is allowed through (half-open)
- If it succeeds, circuit closes; if it fails, circuit reopens

Usage:
    from chat_app.circuit_breaker import get_circuit_breaker_registry

    registry = get_circuit_breaker_registry()

    # Before executing a tool
    if not registry.allow_request("splunk_search"):
        return error("Tool splunk_search is temporarily disabled (circuit open)")

    # After execution
    registry.record_success("splunk_search")
    # or
    registry.record_failure("splunk_search")
"""

import logging
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Circuit states
# ---------------------------------------------------------------------------

class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal — tracking failures
    OPEN = "open"           # Disabled — fast-failing
    HALF_OPEN = "half_open" # Testing — allowing one request


# ---------------------------------------------------------------------------
# Per-tool circuit breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Circuit breaker for a single tool/skill."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: int = 60,
        success_threshold: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.success_threshold = success_threshold

        self.state = CircuitState.CLOSED
        self.failure_count: int = 0
        self.success_count: int = 0
        self.last_failure_time: float = 0.0
        self.last_state_change: float = time.monotonic()
        self.total_trips: int = 0  # How many times circuit has opened

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if cooldown has elapsed
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.cooldown_seconds:
                self._transition(CircuitState.HALF_OPEN)
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            # Allow test request (only one at a time)
            return True

        return False

    def record_success(self) -> None:
        """Record a successful execution."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self._transition(CircuitState.CLOSED)
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0

    def record_failure(self) -> None:
        """Record a failed execution."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            # Test request failed — reopen circuit
            self._transition(CircuitState.OPEN)
        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._transition(CircuitState.OPEN)

    def reset(self) -> None:
        """Manually reset the circuit to closed state."""
        self._transition(CircuitState.CLOSED)

    def _transition(self, new_state: CircuitState) -> None:
        old_state = self.state
        self.state = new_state
        self.last_state_change = time.monotonic()

        if new_state == CircuitState.CLOSED:
            self.failure_count = 0
            self.success_count = 0
        elif new_state == CircuitState.OPEN:
            self.total_trips += 1
            self.success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self.success_count = 0

        logger.info(
            "[CIRCUIT] %s: %s → %s (failures=%d, trips=%d)",
            self.name, old_state.value, new_state.value,
            self.failure_count, self.total_trips,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state for API responses."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "success_count": self.success_count,
            "success_threshold": self.success_threshold,
            "total_trips": self.total_trips,
            "last_failure_time": self.last_failure_time,
            "seconds_since_last_state_change": round(time.monotonic() - self.last_state_change, 1),
        }


# ---------------------------------------------------------------------------
# Circuit Breaker Registry
# ---------------------------------------------------------------------------

class CircuitBreakerRegistry:
    """Manages circuit breakers for all tools/skills."""

    def __init__(
        self,
        default_failure_threshold: int = 5,
        default_cooldown_seconds: int = 60,
        default_success_threshold: int = 2,
    ):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()
        self._default_failure_threshold = default_failure_threshold
        self._default_cooldown_seconds = default_cooldown_seconds
        self._default_success_threshold = default_success_threshold

    def _get_or_create(self, tool_name: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a tool."""
        if tool_name not in self._breakers:
            with self._lock:
                if tool_name not in self._breakers:
                    self._breakers[tool_name] = CircuitBreaker(
                        name=tool_name,
                        failure_threshold=self._default_failure_threshold,
                        cooldown_seconds=self._default_cooldown_seconds,
                        success_threshold=self._default_success_threshold,
                    )
        return self._breakers[tool_name]

    def allow_request(self, tool_name: str) -> bool:
        """Check if a tool request should be allowed."""
        return self._get_or_create(tool_name).allow_request()

    def record_success(self, tool_name: str) -> None:
        """Record a successful tool execution."""
        self._get_or_create(tool_name).record_success()

    def record_failure(self, tool_name: str) -> None:
        """Record a failed tool execution."""
        self._get_or_create(tool_name).record_failure()

    def reset(self, tool_name: str) -> bool:
        """Manually reset a tool's circuit breaker."""
        breaker = self._breakers.get(tool_name)
        if breaker:
            breaker.reset()
            return True
        return False

    def get_status(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific circuit breaker."""
        breaker = self._breakers.get(tool_name)
        return breaker.to_dict() if breaker else None

    def get_all_status(self) -> List[Dict[str, Any]]:
        """Get status of all circuit breakers."""
        return [b.to_dict() for b in self._breakers.values()]

    def get_open_circuits(self) -> List[Dict[str, Any]]:
        """Get all currently open (disabled) circuit breakers — for status banner."""
        return [
            b.to_dict() for b in self._breakers.values()
            if b.state in (CircuitState.OPEN, CircuitState.HALF_OPEN)
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics."""
        total = len(self._breakers)
        open_count = sum(1 for b in self._breakers.values() if b.state == CircuitState.OPEN)
        half_open_count = sum(1 for b in self._breakers.values() if b.state == CircuitState.HALF_OPEN)
        total_trips = sum(b.total_trips for b in self._breakers.values())

        return {
            "total_breakers": total,
            "closed": total - open_count - half_open_count,
            "open": open_count,
            "half_open": half_open_count,
            "total_trips": total_trips,
            "open_tools": [b.name for b in self._breakers.values() if b.state == CircuitState.OPEN],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry_instance: Optional[CircuitBreakerRegistry] = None
_registry_lock = threading.Lock()


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """Get the global CircuitBreakerRegistry singleton."""
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = CircuitBreakerRegistry()
    return _registry_instance
