"""
Framework-agnostic session state store.

Drop-in replacement for cl.user_session when running outside Chainlit
(e.g., the OpenAI-compatible API mode for Open WebUI).

Sessions are keyed by thread_id and auto-expire after a configurable timeout.
"""
import logging
import time
import threading
from typing import Any, Dict

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 7200  # 2 hours


class _Session:
    __slots__ = ("data", "last_access")

    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}
        self.last_access: float = time.monotonic()


class SessionStore:
    """Thread-safe, in-memory session store keyed by thread_id."""

    def __init__(self, ttl: int = _DEFAULT_TTL) -> None:
        self._sessions: Dict[str, _Session] = {}
        self._lock = threading.Lock()
        self._ttl = ttl

    def get(self, thread_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            session = self._sessions.get(thread_id)
            if session is None:
                return default
            session.last_access = time.monotonic()
            return session.data.get(key, default)

    def set(self, thread_id: str, key: str, value: Any) -> None:
        with self._lock:
            session = self._sessions.get(thread_id)
            if session is None:
                session = _Session()
                self._sessions[thread_id] = session
            session.data[key] = value
            session.last_access = time.monotonic()

    def create_session(self, thread_id: str) -> None:
        with self._lock:
            if thread_id not in self._sessions:
                self._sessions[thread_id] = _Session()

    def delete_session(self, thread_id: str) -> None:
        with self._lock:
            self._sessions.pop(thread_id, None)

    def cleanup_expired(self) -> int:
        """Remove sessions older than TTL. Returns count of removed sessions."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            expired = [
                tid for tid, s in self._sessions.items()
                if (now - s.last_access) > self._ttl
            ]
            for tid in expired:
                del self._sessions[tid]
                removed += 1
        if removed:
            logger.info("Cleaned up %d expired sessions", removed)
        return removed


# Singleton instance
session_store = SessionStore()
