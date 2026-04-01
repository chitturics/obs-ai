"""
Persistent JSONL execution journal for skill, agent, and orchestration events.

Provides non-blocking, async-buffered persistence to daily JSONL files.
Events are fire-and-forget — the journal never blocks the main pipeline.

Usage:
    from chat_app.execution_journal import get_journal
    journal = get_journal()
    journal.log(event)  # non-blocking
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Thread pool for file I/O (shared, small)
_io_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="journal_io")


class JournalWriter:
    """Async, non-blocking, buffered JSONL writer.

    - Uses asyncio.Queue to buffer events
    - Flushes to disk periodically via run_in_executor
    - Daily file rotation by date suffix
    - 30-day retention (configurable)
    """

    def __init__(
        self,
        base_dir: str = "/app/data/execution_logs",
        flush_interval: float = 5.0,
        retention_days: int = 30,
        max_queue_size: int = 1000,
    ):
        self.base_dir = Path(base_dir)
        self.flush_interval = flush_interval
        self.retention_days = retention_days
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None
        self._event_counts: Dict[str, int] = {}
        self._total_events = 0
        self._total_flushes = 0
        self._errors = 0

    async def start(self) -> None:
        """Start the background flush loop."""
        if self._running:
            return
        self._running = True
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("[JOURNAL] Started: dir=%s, flush=%ss, retention=%dd",
                     self.base_dir, self.flush_interval, self.retention_days)

    async def stop(self) -> None:
        """Drain queue and stop."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                logger.debug("[JOURNAL] Flush task cancelled during shutdown — normal")
        # Final flush
        await self._flush_all()
        logger.info("[JOURNAL] Stopped. Total events: %d, flushes: %d",
                     self._total_events, self._total_flushes)

    def log(self, event: Union[BaseModel, Dict[str, Any]]) -> bool:
        """Non-blocking: enqueue an event. Returns False if queue full."""
        try:
            if isinstance(event, BaseModel):
                data = event.model_dump()
            else:
                data = dict(event)
            self._queue.put_nowait(data)
            return True
        except asyncio.QueueFull:
            self._errors += 1
            return False
        except Exception as _exc:  # broad catch — resilience against all failures
            self._errors += 1
            return False

    async def _flush_loop(self) -> None:
        """Periodically flush buffered events to disk."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self._flush_all()
            except asyncio.CancelledError:
                break
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.warning("[JOURNAL] Flush loop error: %s", exc)
                self._errors += 1

    async def _flush_all(self) -> None:
        """Drain queue and write to JSONL files."""
        events: List[Dict[str, Any]] = []
        while not self._queue.empty():
            try:
                events.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not events:
            return

        # Group by event_type
        by_type: Dict[str, List[str]] = {}
        today = datetime.date.today().isoformat()
        for evt in events:
            etype = evt.get("event_type", "unknown")
            line = json.dumps(evt, default=str)
            by_type.setdefault(etype, []).append(line)
            self._event_counts[etype] = self._event_counts.get(etype, 0) + 1

        self._total_events += len(events)
        self._total_flushes += 1

        # Write to files in thread pool
        loop = asyncio.get_running_loop()
        for etype, lines in by_type.items():
            fname = f"{etype}_{today}.jsonl"
            fpath = self.base_dir / fname
            try:
                await loop.run_in_executor(_io_pool, self._append_lines, fpath, lines)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                logger.warning("[JOURNAL] Write error for %s: %s", fname, exc)
                self._errors += 1

    @staticmethod
    def _append_lines(fpath: Path, lines: List[str]) -> None:
        """Synchronous file append (runs in thread pool)."""
        with open(fpath, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")

    async def cleanup_old_files(self) -> int:
        """Remove journal files older than retention_days."""
        cutoff = datetime.date.today() - datetime.timedelta(days=self.retention_days)
        removed = 0
        if not self.base_dir.exists():
            return 0
        loop = asyncio.get_running_loop()
        for fpath in self.base_dir.glob("*.jsonl"):
            try:
                # Extract date from filename: event_type_YYYY-MM-DD.jsonl
                # rsplit by _ to get last part which is the date
                stem = fpath.stem  # e.g. "skill_execution_2026-03-13"
                # The date is the last 10 chars of the stem (YYYY-MM-DD)
                date_str = stem[-10:]
                fdate = datetime.date.fromisoformat(date_str)
                if fdate < cutoff:
                    await loop.run_in_executor(_io_pool, fpath.unlink)
                    removed += 1
            except (ValueError, OSError):
                continue
        if removed:
            logger.info("[JOURNAL] Cleaned up %d old files (before %s)", removed, cutoff)
        return removed

    def get_stats(self) -> Dict[str, Any]:
        """Return journal statistics."""
        files = []
        total_size = 0
        if self.base_dir.exists():
            for f in sorted(self.base_dir.glob("*.jsonl")):
                sz = f.stat().st_size
                total_size += sz
                files.append({"name": f.name, "size_bytes": sz})

        return {
            "enabled": self._running,
            "base_dir": str(self.base_dir),
            "total_events": self._total_events,
            "total_flushes": self._total_flushes,
            "queue_size": self._queue.qsize(),
            "event_counts": dict(self._event_counts),
            "errors": self._errors,
            "files": files,
            "total_size_bytes": total_size,
            "retention_days": self.retention_days,
        }

    def query_events(
        self,
        event_type: Optional[str] = None,
        date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query events from journal files. Synchronous (for admin API)."""
        if not self.base_dir.exists():
            return []

        target_date = date or datetime.date.today().isoformat()
        results = []

        if event_type:
            patterns = [f"{event_type}_{target_date}.jsonl"]
        else:
            patterns = [f"*_{target_date}.jsonl"]

        for pattern in patterns:
            for fpath in sorted(self.base_dir.glob(pattern)):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                results.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
                except OSError:
                    continue

        # Return most recent first, limited
        results.reverse()
        return results[:limit]

    def list_files(self) -> List[Dict[str, Any]]:
        """List all journal files with metadata."""
        if not self.base_dir.exists():
            return []
        files = []
        for f in sorted(self.base_dir.glob("*.jsonl"), reverse=True):
            stat = f.stat()
            files.append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "modified": datetime.datetime.fromtimestamp(
                    stat.st_mtime, tz=datetime.timezone.utc
                ).isoformat(),
            })
        return files


# ── Singleton ──────────────────────────────────────────────────────────

_journal_instance: Optional[JournalWriter] = None


def get_journal() -> JournalWriter:
    """Get global journal writer (singleton). Call start() separately."""
    global _journal_instance
    if _journal_instance is None:
        try:
            from chat_app.settings import get_settings
            s = get_settings()
            base_dir = getattr(s, "journal", None)
            if base_dir and hasattr(base_dir, "base_dir"):
                _journal_instance = JournalWriter(
                    base_dir=base_dir.base_dir,
                    flush_interval=base_dir.flush_interval,
                    retention_days=base_dir.retention_days,
                )
            else:
                _journal_instance = JournalWriter()
        except Exception as _exc:  # broad catch — resilience against all failures
            _journal_instance = JournalWriter()
    return _journal_instance
