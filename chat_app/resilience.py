"""
Resilience utilities: Circuit breaker, retry logic, and fallback mechanisms.
"""
import asyncio
import functools
import time
from typing import Callable, Any, Optional, TypeVar, Dict
from enum import Enum
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.

    Prevents cascading failures by stopping requests to failing services.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception,
        name: str = "default",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name

        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitState.CLOSED

    def call(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to wrap function with circuit breaker."""

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # Check if we should attempt recovery
            if self.state == CircuitState.OPEN:
                if (
                    self.last_failure_time
                    and time.time() - self.last_failure_time >= self.recovery_timeout
                ):
                    logger.info(
                        f"Circuit breaker '{self.name}': Attempting recovery (half-open)"
                    )
                    self.state = CircuitState.HALF_OPEN
                    self._emit_state()
                else:
                    raise Exception(
                        f"Circuit breaker '{self.name}' is OPEN. "
                        f"Service unavailable. Retry in {self.recovery_timeout}s."
                    )

            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                # Success - reset if recovering
                if self.state == CircuitState.HALF_OPEN:
                    logger.info(f"Circuit breaker '{self.name}': Recovery successful (closed)")
                    self.failure_count = 0
                    self.state = CircuitState.CLOSED
                    self._emit_state()

                return result

            except self.expected_exception as e:
                self.failure_count += 1
                self.last_failure_time = time.time()

                logger.warning(
                    f"Circuit breaker '{self.name}': Failure {self.failure_count}/{self.failure_threshold} - {e}"
                )

                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.error(
                        f"Circuit breaker '{self.name}' is now OPEN after {self.failure_count} failures"
                    )
                    self._emit_state()

                raise

        return wrapper

    def _emit_state(self):
        """Emit circuit state to Prometheus."""
        try:
            from chat_app.prometheus_metrics import PROMETHEUS_AVAILABLE, CIRCUIT_STATE
            if PROMETHEUS_AVAILABLE:
                state_val = {"closed": 0, "half_open": 1, "open": 2}.get(self.state.value, 0)
                CIRCUIT_STATE.labels(service=self.name).set(state_val)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass


async def retry_with_backoff(
    func: Callable[..., T],
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 30.0,
    jitter: bool = True,
) -> T:
    """
    Retry async function with exponential backoff.

    Args:
        func: Async function to retry
        max_attempts: Maximum number of attempts
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for delay after each attempt
        max_delay: Maximum delay between retries
        jitter: Add random jitter to prevent thundering herd

    Returns:
        Result from successful function call

    Raises:
        Last exception if all retries fail
    """
    import random

    last_exception = None
    delay = initial_delay

    for attempt in range(1, max_attempts + 1):
        try:
            result = await func()
            if attempt > 1:
                logger.info(f"Retry successful on attempt {attempt}")
            return result

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            last_exception = e

            if attempt == max_attempts:
                logger.error(f"All {max_attempts} retry attempts failed: {e}")
                break

            # Calculate delay with exponential backoff
            delay = min(initial_delay * (backoff_factor ** (attempt - 1)), max_delay)

            # Add jitter (±25% of delay)
            if jitter:
                jitter_range = delay * 0.25
                delay += random.uniform(-jitter_range, jitter_range)

            logger.warning(
                f"Attempt {attempt}/{max_attempts} failed: {e}. "
                f"Retrying in {delay:.2f}s..."
            )

            await asyncio.sleep(delay)

    raise last_exception


def with_fallback(fallback_value: Any):
    """
    Decorator that returns fallback value if function fails.

    Args:
        fallback_value: Value to return on failure
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            try:
                return await func(*args, **kwargs)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                logger.warning(
                    f"Function {func.__name__} failed: {e}. "
                    f"Returning fallback value: {fallback_value}"
                )
                return fallback_value

        return wrapper

    return decorator


# Global circuit breakers for common services
CIRCUIT_BREAKERS: Dict[str, CircuitBreaker] = {
    "ollama": CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=60,
        expected_exception=Exception,
        name="ollama",
    ),
    "chroma": CircuitBreaker(
        failure_threshold=3,
        recovery_timeout=30,
        expected_exception=Exception,
        name="chroma",
    ),
    "postgres": CircuitBreaker(
        failure_threshold=3,
        recovery_timeout=30,
        expected_exception=Exception,
        name="postgres",
    ),
}


def get_circuit_breaker(service_name: str) -> CircuitBreaker:
    """Get or create circuit breaker for a service."""
    if service_name not in CIRCUIT_BREAKERS:
        CIRCUIT_BREAKERS[service_name] = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
            expected_exception=Exception,
            name=service_name,
        )
    return CIRCUIT_BREAKERS[service_name]


async def call_with_resilience(
    func: Callable[..., T],
    service_name: str = "default",
    max_retries: int = 3,
    fallback_value: Optional[Any] = None,
) -> T:
    """
    Call function with full resilience stack: circuit breaker + retry + fallback.

    Args:
        func: Async function to call
        service_name: Name of service (for circuit breaker)
        max_retries: Maximum retry attempts
        fallback_value: Value to return if all attempts fail (None = raise exception)

    Returns:
        Function result or fallback value
    """
    circuit_breaker = get_circuit_breaker(service_name)

    async def wrapped_call():
        return await circuit_breaker.call(func)()

    try:
        return await retry_with_backoff(wrapped_call, max_attempts=max_retries)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        if fallback_value is not None:
            logger.warning(
                f"Service '{service_name}' failed after retries. "
                f"Using fallback value: {fallback_value}"
            )
            return fallback_value
        raise
