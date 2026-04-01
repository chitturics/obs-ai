"""Immutable Audit Log — append-only, hash-chained, file-persisted.

Enterprise-grade audit trail for compliance and governance:
- **Hash chaining**: Each entry's SHA-256 hash includes the previous entry's hash,
  creating a tamper-evident chain (like a blockchain).
- **File persistence**: Entries appended to a JSONL file, surviving restarts.
- **Verification**: On startup, chain integrity is validated end-to-end.
- **Export**: JSON, CSV, and Splunk HEC-compatible formats.
- **Retention**: Configurable max entries with automatic rotation.

Usage:
    from chat_app.audit_log import get_audit_log

    log = get_audit_log()
    log.append(
        event_type="config_change",
        actor="admin@example.com",
        action="update",
        target="llm.model",
        details={"old": "llama2", "new": "llama3"},
        severity="medium",
    )

    # Verify chain integrity
    result = log.verify_chain()
    assert result["valid"]

    # Export for Splunk
    entries = log.export(format="splunk", limit=1000)
"""

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_LOG_DIR = "/app/data/audit"
_DEFAULT_LOG_FILE = "audit_log.jsonl"
_MAX_IN_MEMORY = 2000  # In-memory ring buffer for fast queries
_MAX_FILE_ENTRIES = 100_000  # Rotate after this many entries
_GENESIS_HASH = "0" * 64  # SHA-256 of nothing — first entry's prev_hash


# ---------------------------------------------------------------------------
# Severity levels for audit events
# ---------------------------------------------------------------------------

SEVERITY_LEVELS = ("low", "medium", "high", "critical")


# ---------------------------------------------------------------------------
# Audit Entry
# ---------------------------------------------------------------------------

def _compute_hash(entry_data: Dict[str, Any], previous_hash: str) -> str:
    """Compute SHA-256 hash for an audit entry, chaining to the previous hash.

    The hash covers: previous_hash + timestamp + event_type + actor + action +
    target + details_json + severity. This ensures any tampering (including
    reordering) breaks the chain.
    """
    canonical = "|".join([
        previous_hash,
        str(entry_data.get("timestamp", "")),
        str(entry_data.get("event_type", "")),
        str(entry_data.get("actor", "")),
        str(entry_data.get("action", "")),
        str(entry_data.get("target", "")),
        json.dumps(entry_data.get("details", {}), sort_keys=True, default=str),
        str(entry_data.get("severity", "low")),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Immutable Audit Log
# ---------------------------------------------------------------------------

class ImmutableAuditLog:
    """Append-only, hash-chained audit log with file persistence."""

    def __init__(
        self,
        log_dir: str = _DEFAULT_LOG_DIR,
        log_file: str = _DEFAULT_LOG_FILE,
        max_in_memory: int = _MAX_IN_MEMORY,
        max_file_entries: int = _MAX_FILE_ENTRIES,
    ):
        self._log_dir = Path(log_dir)
        self._log_path = self._log_dir / log_file
        self._max_in_memory = max_in_memory
        self._max_file_entries = max_file_entries

        self._entries: deque = deque(maxlen=max_in_memory)
        self._lock = threading.Lock()
        self._last_hash: str = _GENESIS_HASH
        self._entry_count: int = 0
        self._chain_valid: bool = True

        # Ensure directory exists
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # Load existing entries and rebuild chain
        self._load_from_file()

    # ----- Persistence -----

    def _load_from_file(self) -> None:
        """Load entries from the JSONL file and verify chain integrity."""
        if not self._log_path.exists():
            logger.info("[AUDIT] No existing audit log found at %s — starting fresh", self._log_path)
            return

        loaded = 0
        errors = 0
        previous_hash = _GENESIS_HASH

        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                for line_num, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("[AUDIT] Corrupt entry at line %d — skipping", line_num)
                        errors += 1
                        continue

                    # Verify chain
                    stored_hash = entry.get("hash", "")
                    stored_prev = entry.get("previous_hash", "")
                    expected_hash = _compute_hash(entry, stored_prev)

                    if stored_prev != previous_hash:
                        logger.error(
                            "[AUDIT] Chain break at line %d: expected prev_hash=%s, got=%s",
                            line_num, previous_hash[:16], stored_prev[:16],
                        )
                        self._chain_valid = False

                    if stored_hash != expected_hash:
                        logger.error(
                            "[AUDIT] Hash mismatch at line %d: expected=%s, stored=%s",
                            line_num, expected_hash[:16], stored_hash[:16],
                        )
                        self._chain_valid = False

                    self._entries.append(entry)
                    previous_hash = stored_hash
                    loaded += 1

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error("[AUDIT] Failed to load audit log: %s", exc)
            self._chain_valid = False

        self._last_hash = previous_hash
        self._entry_count = loaded
        status = "valid" if self._chain_valid else "INTEGRITY ERROR"
        logger.info(
            "[AUDIT] Loaded %d entries (%d errors) — chain %s",
            loaded, errors, status,
        )

    def _persist_entry(self, entry: Dict[str, Any]) -> None:
        """Append a single entry to the JSONL file."""
        try:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("[AUDIT] Failed to persist entry: %s", exc)

    def _rotate_if_needed(self) -> None:
        """Rotate the log file when it exceeds max entries."""
        if self._entry_count < self._max_file_entries:
            return

        rotated_name = self._log_path.stem + f"_{int(time.time())}" + self._log_path.suffix
        rotated_path = self._log_dir / rotated_name

        try:
            self._log_path.rename(rotated_path)
            logger.info("[AUDIT] Rotated audit log to %s (%d entries)", rotated_name, self._entry_count)
            self._entry_count = 0
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error("[AUDIT] Failed to rotate log: %s", exc)

    # ----- Public API -----

    def append(
        self,
        event_type: str,
        actor: str,
        action: str,
        target: str,
        details: Optional[Dict[str, Any]] = None,
        severity: str = "low",
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append an immutable, hash-chained entry to the audit log.

        Args:
            event_type: Category (config_change, auth, tool_execution, approval, etc.)
            actor: Who performed the action (username, service name, "system")
            action: What was done (create, update, delete, execute, login, etc.)
            target: What it was done to (resource identifier)
            details: Optional structured data about the change
            severity: low, medium, high, critical
            request_id: Optional correlation ID for tracing

        Returns:
            The complete audit entry with hash chain fields.
        """
        if severity not in SEVERITY_LEVELS:
            severity = "low"

        entry_data = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "actor": actor or "system",
            "action": action,
            "target": target,
            "details": details or {},
            "severity": severity,
            "request_id": request_id or "",
        }

        with self._lock:
            # Chain to previous hash
            entry_data["previous_hash"] = self._last_hash
            entry_data["hash"] = _compute_hash(entry_data, self._last_hash)
            entry_data["sequence"] = self._entry_count

            # Update state
            self._last_hash = entry_data["hash"]
            self._entry_count += 1
            self._entries.append(entry_data)

            # Persist and rotate
            self._persist_entry(entry_data)
            self._rotate_if_needed()

        return entry_data

    def verify_chain(self, full: bool = False) -> Dict[str, Any]:
        """Verify the integrity of the hash chain.

        Args:
            full: If True, re-read from file and verify every entry.
                  If False, verify only in-memory entries.

        Returns:
            Dict with valid (bool), entries_checked (int), errors (list).
        """
        entries_to_check: List[Dict[str, Any]] = []

        if full and self._log_path.exists():
            try:
                with open(self._log_path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            entries_to_check.append(json.loads(line))
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                return {
                    "valid": False,
                    "entries_checked": 0,
                    "errors": [f"Failed to read log file: {exc}"],
                }
        else:
            with self._lock:
                entries_to_check = list(self._entries)

        errors: List[str] = []
        previous_hash = _GENESIS_HASH

        for idx, entry in enumerate(entries_to_check):
            stored_hash = entry.get("hash", "")
            stored_prev = entry.get("previous_hash", "")
            expected_hash = _compute_hash(entry, stored_prev)

            if stored_prev != previous_hash:
                errors.append(
                    f"Entry {idx}: chain break — expected prev_hash {previous_hash[:16]}..., "
                    f"got {stored_prev[:16]}..."
                )
            if stored_hash != expected_hash:
                errors.append(
                    f"Entry {idx}: hash mismatch — expected {expected_hash[:16]}..., "
                    f"stored {stored_hash[:16]}..."
                )
            previous_hash = stored_hash

        return {
            "valid": len(errors) == 0,
            "entries_checked": len(entries_to_check),
            "errors": errors,
            "last_hash": previous_hash[:16] + "..." if previous_hash else "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def query(
        self,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
        severity: Optional[str] = None,
        target: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query audit entries with filtering.

        Args:
            event_type: Filter by event type.
            actor: Filter by actor (case-insensitive substring).
            severity: Filter by severity level.
            target: Filter by target (case-insensitive substring).
            since: ISO timestamp — only entries after this time.
            limit: Max entries to return.
            offset: Skip first N matching entries.

        Returns:
            List of matching entries, most recent first.
        """
        with self._lock:
            entries = list(self._entries)

        # Most recent first
        entries.reverse()

        # Apply filters
        if event_type:
            entries = [e for e in entries if e.get("event_type") == event_type]
        if actor:
            actor_lower = actor.lower()
            entries = [e for e in entries if actor_lower in e.get("actor", "").lower()]
        if severity:
            entries = [e for e in entries if e.get("severity") == severity]
        if target:
            target_lower = target.lower()
            entries = [e for e in entries if target_lower in e.get("target", "").lower()]
        if since:
            entries = [e for e in entries if e.get("timestamp", "") >= since]

        return entries[offset:offset + limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get audit log statistics."""
        with self._lock:
            entries = list(self._entries)

        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        by_actor: Dict[str, int] = {}

        for entry in entries:
            etype = entry.get("event_type", "unknown")
            by_type[etype] = by_type.get(etype, 0) + 1

            sev = entry.get("severity", "low")
            by_severity[sev] = by_severity.get(sev, 0) + 1

            act = entry.get("actor", "unknown")
            by_actor[act] = by_actor.get(act, 0) + 1

        top_actors = sorted(by_actor.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_entries": self._entry_count,
            "in_memory": len(entries),
            "chain_valid": self._chain_valid,
            "log_file": str(self._log_path),
            "log_file_exists": self._log_path.exists(),
            "log_file_size_bytes": self._log_path.stat().st_size if self._log_path.exists() else 0,
            "by_type": by_type,
            "by_severity": by_severity,
            "top_actors": [{"actor": a, "count": c} for a, c in top_actors],
            "last_hash": self._last_hash[:16] + "..." if self._last_hash != _GENESIS_HASH else "genesis",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def export(
        self,
        format: Literal["json", "csv", "splunk"] = "json",
        limit: int = 1000,
        since: Optional[str] = None,
    ) -> Any:
        """Export audit entries in the specified format.

        Args:
            format: Output format — json (list of dicts), csv (string), splunk (HEC events).
            limit: Max entries to export.
            since: ISO timestamp — only entries after this time.

        Returns:
            Formatted export data.
        """
        entries = self.query(since=since, limit=limit)

        if format == "json":
            return entries

        if format == "csv":
            import io
            import csv as csv_module
            output = io.StringIO()
            fields = ["timestamp", "event_type", "actor", "action", "target", "severity",
                       "details", "hash", "previous_hash", "sequence"]
            writer = csv_module.DictWriter(output, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for entry in entries:
                row = dict(entry)
                row["details"] = json.dumps(row.get("details", {}), default=str)
                writer.writerow(row)
            return output.getvalue()

        if format == "splunk":
            # Splunk HEC event format
            hec_events = []
            for entry in entries:
                hec_events.append({
                    "time": entry.get("timestamp", ""),
                    "sourcetype": "obsai:audit",
                    "source": "obsai_audit_log",
                    "host": os.getenv("HOSTNAME", "obsai"),
                    "event": {
                        "event_type": entry.get("event_type"),
                        "actor": entry.get("actor"),
                        "action": entry.get("action"),
                        "target": entry.get("target"),
                        "severity": entry.get("severity"),
                        "details": entry.get("details"),
                        "hash": entry.get("hash"),
                        "sequence": entry.get("sequence"),
                    },
                })
            return hec_events

        return entries


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_audit_log_instance: Optional[ImmutableAuditLog] = None
_audit_log_lock = threading.Lock()


def get_audit_log() -> ImmutableAuditLog:
    """Get the global ImmutableAuditLog singleton."""
    global _audit_log_instance
    if _audit_log_instance is None:
        with _audit_log_lock:
            if _audit_log_instance is None:
                log_dir = os.getenv("AUDIT_LOG_DIR", _DEFAULT_LOG_DIR)
                _audit_log_instance = ImmutableAuditLog(log_dir=log_dir)
    return _audit_log_instance
