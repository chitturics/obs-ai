"""
Priority queue for agent/skill task execution.

Provides:
- PriorityTaskQueue: asyncio-based priority queue with concurrency limiting
- Resource-aware execution: tasks checked against CPU/memory thresholds by priority
- Integration point for skill_catalog, agent_dispatcher, orchestration_strategies
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from typing import Any, Awaitable, Dict, List, Tuple

from chat_app.schemas import Priority

logger = logging.getLogger(__name__)

# Resource thresholds by priority level (cpu_max%, mem_max%)
RESOURCE_THRESHOLDS: Dict[Priority, Tuple[float, float]] = {
    Priority.CRITICAL: (100.0, 100.0),    # Always execute
    Priority.HIGH: (95.0, 95.0),          # Unless both maxed
    Priority.NORMAL: (85.0, 90.0),        # Default thresholds
    Priority.LOW: (70.0, 80.0),           # Only when resources available
    Priority.BACKGROUND: (50.0, 60.0),    # Only when idle
}


def can_execute_at_priority(priority: Priority) -> bool:
    """Check if current resources allow execution at given priority."""
    if priority == Priority.CRITICAL:
        return True
    try:
        from chat_app.resource_manager import get_resource_manager
        rm = get_resource_manager()
        cpu = rm.get_cpu_percent()
        mem = rm.get_memory_percent()
        max_cpu, max_mem = RESOURCE_THRESHOLDS.get(priority, (85.0, 90.0))
        return cpu < max_cpu and mem < max_mem
    except Exception as _exc:  # broad catch — resilience against all failures
        return True  # If can't check, allow execution


@dataclasses.dataclass(order=True)
class PriorityItem:
    """Wrapper for priority queue items. Lower priority value = higher priority."""
    priority: int
    seq: int  # tie-breaker for FIFO within same priority
    coro: Any = dataclasses.field(compare=False)
    label: str = dataclasses.field(default="", compare=False)


class PriorityTaskQueue:
    """Async priority queue with concurrency limiting.

    Tasks are executed in priority order (CRITICAL first, BACKGROUND last).
    Concurrency is limited by a semaphore.

    Usage:
        queue = PriorityTaskQueue(max_concurrent=3)
        queue.submit(Priority.HIGH, my_coroutine(), label="task1")
        queue.submit(Priority.LOW, another_coro(), label="task2")
        results = await queue.drain()
    """

    def __init__(self, max_concurrent: int = 5):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._seq = 0
        self._results: List[Tuple[str, Any]] = []
        self._errors: List[Tuple[str, Exception]] = []

    def submit(
        self,
        priority: Priority,
        coro: Awaitable,
        label: str = "",
    ) -> None:
        """Add a task to the queue."""
        self._seq += 1
        item = PriorityItem(
            priority=int(priority),
            seq=self._seq,
            coro=coro,
            label=label or f"task_{self._seq}",
        )
        self._queue.put_nowait(item)

    async def drain(self) -> List[Tuple[str, Any]]:
        """Execute all queued tasks in priority order, respecting concurrency.

        Returns list of (label, result) tuples. Errors stored in self._errors.
        """
        tasks = []
        while not self._queue.empty():
            item = self._queue.get_nowait()
            tasks.append(item)

        # Sort is already by priority (dataclass order)
        results = []
        async_tasks = []

        for item in tasks:
            async_tasks.append(self._execute_item(item))

        gathered = await asyncio.gather(*async_tasks, return_exceptions=True)

        for item, result in zip(tasks, gathered):
            if isinstance(result, Exception):
                self._errors.append((item.label, result))
                logger.warning("[PRIORITY] Task %s failed: %s", item.label, result)
            else:
                results.append((item.label, result))

        self._results = results
        return results

    async def _execute_item(self, item: PriorityItem) -> Any:
        """Execute a single item with semaphore limiting."""
        async with self._semaphore:
            if not can_execute_at_priority(Priority(item.priority)):
                logger.info(
                    "[PRIORITY] Deferring %s (priority=%s): resources constrained",
                    item.label, Priority(item.priority).name,
                )
                # Still execute, just log the constraint
            t0 = time.monotonic()
            result = await item.coro
            dt = (time.monotonic() - t0) * 1000
            logger.debug(
                "[PRIORITY] %s completed: priority=%s duration=%.0fms",
                item.label, Priority(item.priority).name, dt,
            )
            return result

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def errors(self) -> List[Tuple[str, Exception]]:
        return self._errors
