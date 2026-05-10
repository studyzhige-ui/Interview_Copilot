"""Centralized background task lifecycle management.

All fire-and-forget ``asyncio.create_task()`` calls should go through
:func:`safe_background_task` instead.  This module provides:

1. **Exception logging** — unhandled exceptions in background tasks are logged
   instead of being silently swallowed.
2. **GC protection** — tasks are kept in a global set so the garbage collector
   cannot reclaim them before they finish.
3. **Graceful shutdown** — :func:`cancel_and_wait_all` can be called during
   the FastAPI lifespan shutdown to drain pending tasks.
"""

import asyncio
import logging
from typing import Coroutine

logger = logging.getLogger(__name__)

# Strong references to prevent GC from killing running tasks.
_background_tasks: set[asyncio.Task] = set()


def _task_done_callback(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Background task %s raised an exception: %s",
            task.get_name(),
            exc,
            exc_info=exc,
        )


def safe_background_task(
    coro: Coroutine,
    *,
    name: str | None = None,
) -> asyncio.Task:
    """Schedule *coro* as a background task with proper lifecycle tracking.

    This is a drop-in replacement for ``asyncio.create_task()`` that:
    - Holds a strong reference so the task isn't garbage-collected early.
    - Logs exceptions instead of swallowing them silently.
    """
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_task_done_callback)
    return task


async def cancel_and_wait_all(timeout: float = 5.0) -> None:
    """Cancel all pending background tasks and wait for them to finish.

    Call this during FastAPI lifespan shutdown.
    """
    if not _background_tasks:
        return
    logger.info("Draining %d background task(s)...", len(_background_tasks))
    tasks = list(_background_tasks)
    for task in tasks:
        task.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for task, result in zip(tasks, results):
        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
            logger.warning("Background task %s failed during shutdown: %s", task.get_name(), result)
    _background_tasks.clear()
    logger.info("All background tasks drained.")


def pending_count() -> int:
    """Return the number of currently tracked background tasks."""
    return len(_background_tasks)
