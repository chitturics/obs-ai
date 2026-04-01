"""
Priority-based request queue for Ollama API to ensure user queries
take precedence over background embedding requests.
"""
import asyncio
import logging
from typing import Callable, Any, Optional
from enum import IntEnum
from datetime import datetime

logger = logging.getLogger(__name__)


class RequestPriority(IntEnum):
    """Request priority levels (lower number = higher priority)."""
    USER_QUERY = 1          # Direct user questions - highest priority
    TEMPLATE_GENERATION = 2  # SPL template generation
    VALIDATION = 3           # Query validation/correction
    EMBEDDING = 4            # Embedding generation - lowest priority
    BACKGROUND = 5           # Background tasks


class PriorityRequest:
    """Represents a prioritized request."""

    def __init__(
        self,
        priority: RequestPriority,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        request_id: Optional[str] = None
    ):
        self.priority = priority
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}
        self.request_id = request_id or f"{priority.name}_{datetime.now().timestamp()}"
        self.created_at = datetime.now()
        self.future = asyncio.Future()

    def __lt__(self, other):
        """Compare by priority (lower value = higher priority)."""
        if self.priority != other.priority:
            return self.priority < other.priority
        # Same priority - FIFO
        return self.created_at < other.created_at

    async def execute(self):
        """Execute the request and set result in future."""
        try:
            if asyncio.iscoroutinefunction(self.func):
                result = await self.func(*self.args, **self.kwargs)
            else:
                result = self.func(*self.args, **self.kwargs)
            self.future.set_result(result)
            return result
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            self.future.set_exception(e)
            raise


class OllamaPriorityQueue:
    """
    Priority queue for Ollama API requests.
    Ensures user queries are processed before background embedding requests.
    """

    def __init__(self, max_concurrent: int = 2):
        """
        Initialize priority queue.

        Args:
            max_concurrent: Maximum concurrent requests to Ollama (default: 2)
                           Keeps 1-2 slots open for high-priority user queries
        """
        self.queue = asyncio.PriorityQueue()
        self.max_concurrent = max_concurrent
        self.active_requests = 0
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.worker_task = None
        self.running = False
        self._stats = {
            "user_queries": 0,
            "embeddings": 0,
            "total_requests": 0,
            "queue_waits": []
        }

    async def start(self):
        """Start the worker task."""
        if not self.running:
            self.running = True
            self.worker_task = asyncio.create_task(self._worker())
            logger.info("[OLLAMA_PRIORITY] Priority queue started")

    async def stop(self):
        """Stop the worker task."""
        self.running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                logger.debug("[OLLAMA_PRIORITY] Worker task cancelled during shutdown — normal")
        logger.info("[OLLAMA_PRIORITY] Priority queue stopped")

    async def _worker(self):
        """Background worker that processes requests by priority."""
        while self.running:
            try:
                # Get next request (blocks until available)
                priority_request: PriorityRequest = await self.queue.get()

                # Wait for semaphore (limit concurrent requests)
                async with self.semaphore:
                    self.active_requests += 1
                    wait_time = (datetime.now() - priority_request.created_at).total_seconds()

                    logger.info(
                        f"[OLLAMA_PRIORITY] Executing {priority_request.priority.name} "
                        f"request (waited {wait_time:.2f}s, active={self.active_requests})"
                    )

                    try:
                        await priority_request.execute()
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                        logger.error(f"[OLLAMA_PRIORITY] Request failed: {e}")
                    finally:
                        self.active_requests -= 1
                        self.queue.task_done()
                        self._stats["queue_waits"].append(wait_time)

            except asyncio.CancelledError:
                break
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                logger.error(f"[OLLAMA_PRIORITY] Worker error: {e}")

    async def submit(
        self,
        func: Callable,
        priority: RequestPriority = RequestPriority.USER_QUERY,
        *args,
        **kwargs
    ) -> Any:
        """
        Submit a request to the priority queue.

        Args:
            func: Function to execute (sync or async)
            priority: Request priority level
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result of the function execution
        """
        if not self.running:
            await self.start()

        request = PriorityRequest(priority, func, args, kwargs)

        # Track stats
        self._stats["total_requests"] += 1
        if priority == RequestPriority.USER_QUERY:
            self._stats["user_queries"] += 1
        elif priority == RequestPriority.EMBEDDING:
            self._stats["embeddings"] += 1

        logger.debug(
            f"[OLLAMA_PRIORITY] Queued {priority.name} request "
            f"(queue_size={self.queue.qsize()}, active={self.active_requests})"
        )

        await self.queue.put(request)

        # Wait for result
        result = await request.future
        return result

    def get_stats(self) -> dict:
        """Get queue statistics."""
        avg_wait = (
            sum(self._stats["queue_waits"]) / len(self._stats["queue_waits"])
            if self._stats["queue_waits"]
            else 0
        )

        return {
            "queue_size": self.queue.qsize(),
            "active_requests": self.active_requests,
            "total_requests": self._stats["total_requests"],
            "user_queries": self._stats["user_queries"],
            "embeddings": self._stats["embeddings"],
            "avg_wait_time": round(avg_wait, 2),
        }


# Global priority queue instance
_priority_queue: Optional[OllamaPriorityQueue] = None


def get_priority_queue(max_concurrent: int = 2) -> OllamaPriorityQueue:
    """Get or create the global priority queue."""
    global _priority_queue
    if _priority_queue is None:
        _priority_queue = OllamaPriorityQueue(max_concurrent=max_concurrent)
    return _priority_queue


async def with_priority(
    func: Callable,
    priority: RequestPriority = RequestPriority.USER_QUERY,
    *args,
    **kwargs
) -> Any:
    """
    Execute a function with priority scheduling.

    Example:
        # High priority user query
        response = await with_priority(
            chain.invoke,
            RequestPriority.USER_QUERY,
            {"input": user_question}
        )

        # Low priority embedding
        embedding = await with_priority(
            embed_function,
            RequestPriority.EMBEDDING,
            text
        )
    """
    # Original priority queue implementation
    queue = get_priority_queue()
    return await queue.submit(func, priority, *args, **kwargs)
