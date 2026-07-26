"""Reusable event loop for Celery workers.

Each Celery worker thread gets its own persistent event loop, avoiding the
overhead of creating/destroying a loop on every task invocation.
"""

import asyncio
import threading

_loop_local = threading.local()


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop for the current worker thread."""
    loop = getattr(_loop_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _loop_local.loop = loop
    return loop


def run_async(coro):
    """Run an async coroutine inside a synchronous Celery task."""
    loop = _get_worker_loop()
    return loop.run_until_complete(coro)
