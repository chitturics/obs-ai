"""Idempotency + Dry-Run — safe execution guarantees for write tools.

Provides:
- **Idempotency keys**: Prevent duplicate execution of the same action.
  Client sends an ``X-Idempotency-Key`` header; if we've seen it before,
  we return the cached result instead of re-executing.
- **Dry-run mode**: Execute tool logic up to the point of side effects,
  return what *would* happen without actually doing it.

Storage: In-memory with TTL (default 24h). Redis when available.

Usage:
    from chat_app.idempotency import IdempotencyStore, DryRunResult

    store = get_idempotency_store()

    # Check idempotency
    cached = store.get(key)
    if cached:
        return cached  # Already executed

    # Execute and store result
    result = execute_tool(...)
    store.put(key, result, ttl_seconds=86400)

    # Dry-run
    dry_result = DryRunResult(
        tool="update_config",
        would_change={"llm.model": {"old": "llama2", "new": "llama3"}},
        side_effects=["App restart required"],
        reversible=True,
    )
"""

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dry-Run Result
# ---------------------------------------------------------------------------

@dataclass
class DryRunResult:
    """Result of a dry-run execution — what would happen without doing it."""
    tool: str
    would_change: Dict[str, Any] = field(default_factory=dict)
    side_effects: List[str] = field(default_factory=list)
    reversible: bool = True
    approval_required: bool = False
    estimated_duration_seconds: Optional[float] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "dry_run": True,
            "would_change": self.would_change,
            "side_effects": self.side_effects,
            "reversible": self.reversible,
            "approval_required": self.approval_required,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Idempotency Store Entry
# ---------------------------------------------------------------------------

@dataclass
class _IdempotencyEntry:
    key: str
    result: Any
    created_at: float  # monotonic time
    ttl_seconds: int
    tool: str = ""
    actor: str = ""
    status: str = "completed"  # completed, in_progress, failed

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_seconds


# ---------------------------------------------------------------------------
# Idempotency Store
# ---------------------------------------------------------------------------

_DEFAULT_TTL = 86400  # 24 hours
_MAX_ENTRIES = 10000
_CLEANUP_INTERVAL = 300  # 5 minutes


class IdempotencyStore:
    """In-memory idempotency key store with TTL and cleanup."""

    def __init__(self, default_ttl: int = _DEFAULT_TTL, max_entries: int = _MAX_ENTRIES):
        self._store: Dict[str, _IdempotencyEntry] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._last_cleanup = time.monotonic()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Look up an idempotency key. Returns cached result or None."""
        self._maybe_cleanup()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.expired:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return {
                "idempotency_key": entry.key,
                "cached": True,
                "result": entry.result,
                "tool": entry.tool,
                "actor": entry.actor,
                "status": entry.status,
                "age_seconds": round(time.monotonic() - entry.created_at, 1),
            }

    def put(
        self,
        key: str,
        result: Any,
        tool: str = "",
        actor: str = "",
        status: str = "completed",
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store an idempotency key with its result."""
        with self._lock:
            self._store[key] = _IdempotencyEntry(
                key=key,
                result=result,
                created_at=time.monotonic(),
                ttl_seconds=ttl_seconds or self._default_ttl,
                tool=tool,
                actor=actor,
                status=status,
            )
            # Evict oldest entries if over capacity
            if len(self._store) > self._max_entries:
                oldest_keys = sorted(
                    self._store.keys(),
                    key=lambda k: self._store[k].created_at,
                )[:len(self._store) - self._max_entries]
                for k in oldest_keys:
                    del self._store[k]

    def mark_in_progress(self, key: str, tool: str = "", actor: str = "") -> bool:
        """Mark a key as in-progress (prevents concurrent execution).

        Returns True if the key was successfully claimed, False if already in use.
        """
        with self._lock:
            existing = self._store.get(key)
            if existing and not existing.expired:
                return False  # Already claimed or completed
            self._store[key] = _IdempotencyEntry(
                key=key,
                result=None,
                created_at=time.monotonic(),
                ttl_seconds=300,  # 5-minute in-progress TTL
                tool=tool,
                actor=actor,
                status="in_progress",
            )
            return True

    def remove(self, key: str) -> bool:
        """Remove an idempotency key (e.g., on failure to allow retry)."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def get_stats(self) -> Dict[str, Any]:
        """Get store statistics."""
        with self._lock:
            active = sum(1 for e in self._store.values() if not e.expired)
            expired = len(self._store) - active
        total_requests = self._hits + self._misses
        return {
            "active_keys": active,
            "expired_keys": expired,
            "total_stored": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total_requests, 3) if total_requests > 0 else 0.0,
            "default_ttl_seconds": self._default_ttl,
            "max_entries": self._max_entries,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _maybe_cleanup(self) -> None:
        """Periodically clean up expired entries."""
        now = time.monotonic()
        if now - self._last_cleanup < _CLEANUP_INTERVAL:
            return
        with self._lock:
            self._last_cleanup = now
            expired_keys = [k for k, v in self._store.items() if v.expired]
            for k in expired_keys:
                del self._store[k]
            if expired_keys:
                logger.debug("[IDEMPOTENCY] Cleaned up %d expired entries", len(expired_keys))


# ---------------------------------------------------------------------------
# Key generation helpers
# ---------------------------------------------------------------------------

def generate_idempotency_key(tool: str, params: Dict[str, Any], actor: str = "") -> str:
    """Generate a deterministic idempotency key from tool + params + actor.

    Same tool + same params + same actor = same key.
    """
    canonical = json.dumps({"tool": tool, "params": params, "actor": actor}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store_instance: Optional[IdempotencyStore] = None
_store_lock = threading.Lock()


def get_idempotency_store() -> IdempotencyStore:
    """Get the global IdempotencyStore singleton."""
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = IdempotencyStore()
    return _store_instance
