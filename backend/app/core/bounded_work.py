"""Bound synchronous work, including work whose async caller has timed out.

Cancelling an asyncio waiter cannot interrupt a running Python thread. A permit
therefore belongs to the concurrent Future, not the waiter or request. These are
process-local capacity limits, not distributed quotas or a security sandbox.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from functools import partial
from threading import BoundedSemaphore, Lock
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


class WorkCapacityExceeded(RuntimeError):
    """The service has no capacity; this is not evidence of absent documents."""


class BoundedWorkPool:
    def __init__(self, name: str, *, workers: int, queue_size: int) -> None:
        if workers < 1 or queue_size < 0:
            raise ValueError("workers must be positive and queue_size nonnegative")
        self.name = name
        self._capacity = workers + queue_size
        self._slots = BoundedSemaphore(self._capacity)
        self._lock = Lock()
        self._closed = False
        self._inflight = 0
        self._rejected = 0
        self._executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix=f"bounded-{name}"
        )

    def snapshot(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "capacity": self._capacity,
                "inflight": self._inflight,
                "rejected": self._rejected,
                "closed": self._closed,
            }

    def _finished(self, _future: object) -> None:
        with self._lock:
            self._inflight -= 1
        self._slots.release()

    async def run(self, func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        if not self._slots.acquire(blocking=False):
            with self._lock:
                self._rejected += 1
            raise WorkCapacityExceeded(f"{self.name}: capacity exhausted")
        context = copy_context()
        try:
            with self._lock:
                if self._closed:
                    raise WorkCapacityExceeded(f"{self.name}: shutting down")
                future = self._executor.submit(
                    context.run, partial(func, *args, **kwargs)
                )
                self._inflight += 1
        except BaseException:
            self._slots.release()
            raise
        # Add outside _lock: an already finished Future invokes this inline.
        future.add_done_callback(self._finished)
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            # Pending work may be cancelled. Running work keeps its permit until
            # the real Future completes, including when the event loop closes.
            future.cancel()
            raise

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=True)
