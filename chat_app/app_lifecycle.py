"""
App Lifecycle — Graceful shutdown handler for the Chainlit application.

Extracted from app.py to keep that file under 600 lines.
Called by app.py at module-import time; sets up atexit and SIGTERM handlers.
"""
import asyncio
import atexit
import logging
import signal

logger = logging.getLogger(__name__)


def register_shutdown_handler(shutdown_event_getter=None):
    """
    Register graceful-shutdown callbacks (atexit + SIGTERM).

    Args:
        shutdown_event_getter: Optional callable that returns the asyncio.Event
            used to signal background tasks. Called at shutdown time so that
            the event can be set even if it was created after registration.
    """
    def _graceful_shutdown(signum=None, frame=None):
        """Flush caches and close connections on shutdown."""
        logger.info("[SHUTDOWN] Graceful shutdown initiated (signal=%s)", signum)

        # Signal background tasks to stop
        if shutdown_event_getter is not None:
            _ev = shutdown_event_getter()
            if _ev is not None:
                _ev.set()

        try:
            from chat_app.cache import get_cache
            cache = get_cache()
            if cache.client:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(cache.close())
                except RuntimeError:
                    # No running loop — use new event loop safely
                    try:
                        _loop = asyncio.new_event_loop()
                        _loop.run_until_complete(cache.close())
                        _loop.close()
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                        logger.debug("[SHUTDOWN] Cache close fallback: %s", e)
            logger.info("[SHUTDOWN] Cache connection closed")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[SHUTDOWN] Cache close: %s", exc)

        try:
            from chat_app.health_monitor import InternalMetrics
            InternalMetrics()._persist_to_redis()
            logger.info("[SHUTDOWN] Metrics flushed to Redis")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[SHUTDOWN] Metrics flush: %s", exc)

        # Flush execution journal (drain buffered events to disk)
        try:
            from chat_app.execution_journal import get_journal
            import asyncio as _shutdown_aio
            _journal = get_journal()
            if _journal._running:
                try:
                    loop = _shutdown_aio.get_running_loop()
                    loop.create_task(_journal.stop())
                except RuntimeError:
                    try:
                        _loop = _shutdown_aio.new_event_loop()
                        _loop.run_until_complete(_journal.stop())
                        _loop.close()
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                        logger.debug("[SHUTDOWN] Journal stop fallback: %s", e)
            logger.info("[SHUTDOWN] Execution journal flushed")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[SHUTDOWN] Journal flush: %s", exc)

        # Shutdown OpenTelemetry (flush pending spans)
        try:
            from opentelemetry import trace as _otel_trace_shutdown
            _provider = _otel_trace_shutdown.get_tracer_provider()
            if hasattr(_provider, 'shutdown'):
                _provider.shutdown()
                logger.info("[SHUTDOWN] OpenTelemetry spans flushed")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[SHUTDOWN] OTel shutdown: %s", exc)

        logger.info("[SHUTDOWN] Graceful shutdown complete")

    atexit.register(_graceful_shutdown)
    try:
        signal.signal(signal.SIGTERM, _graceful_shutdown)
    except (ValueError, OSError):
        pass  # Can't set signal handler in non-main thread
