"""
Langfuse LLM observability integration — DEPRECATED.

Langfuse has been replaced by OpenTelemetry (chat_app.otel_tracing) as the
primary tracing backend.  All functions in this module are now no-ops or
thin delegates to OTel to preserve backward compatibility for any callers.

Migration:
    # Old (Langfuse):
    from chat_app.langfuse_integration import observe_llm, init_langfuse
    # New (OTel):
    from chat_app.otel_tracing import trace_span, init_otel
"""

import asyncio
import logging
import functools
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def init_langfuse() -> bool:
    """No-op.  Langfuse replaced by OpenTelemetry (see chat_app.otel_tracing)."""
    logger.info("Langfuse init skipped — deprecated in favor of OpenTelemetry")
    return False


def flush_langfuse() -> None:
    """No-op.  OTel spans are flushed via the TracerProvider shutdown."""
    pass


def is_enabled() -> bool:
    """Always returns False.  Use chat_app.otel_tracing.is_otel_available() instead."""
    return False


def get_client():
    """Always returns None.  Langfuse client is no longer initialized."""
    return None


def observe_llm(name: Optional[str] = None, as_type: Optional[str] = None) -> Callable:
    """Decorator that delegates to OTel trace_span when available.

    When OTel is not available, the original function is returned unmodified.
    This preserves backward compatibility for any code still using @observe_llm.
    """
    def decorator(func: Callable) -> Callable:
        try:
            from chat_app.otel_tracing import trace_span, is_otel_available
            if not is_otel_available():
                return func

            span_name = name or getattr(func, "__name__", "unknown")

            if asyncio.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    with trace_span(span_name):
                        return await func(*args, **kwargs)
                return async_wrapper
            else:
                @functools.wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    with trace_span(span_name):
                        return func(*args, **kwargs)
                return sync_wrapper
        except Exception:  # broad catch — decorator must never break the decorated function
            return func

    return decorator


def create_trace(name: str, **kwargs: Any):
    """No-op.  Use chat_app.otel_tracing.trace_span() instead."""
    return None


def update_trace_metadata(**kwargs: Any) -> None:
    """No-op.  Use span.set_attribute() from OTel instead."""
    pass
