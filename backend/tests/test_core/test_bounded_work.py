"""Real-thread capacity contracts, not a mocked asyncio semaphore."""

import asyncio
from contextvars import ContextVar
from threading import Event

import pytest

from app.core.bounded_work import BoundedWorkPool, WorkCapacityExceeded


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_kind", ["cancel", "timeout"])
async def test_running_work_keeps_permit_after_waiter_exits(cancel_kind):
    pool = BoundedWorkPool("test", workers=1, queue_size=0)
    started, release = Event(), Event()

    def blocking():
        started.set()
        assert release.wait(5)
        return "late result"

    task = asyncio.create_task(pool.run(blocking))
    try:
        await eventually(started.is_set)
        if cancel_kind == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(task, 0.01)
        assert pool.snapshot()["inflight"] == 1
        with pytest.raises(WorkCapacityExceeded):
            await pool.run(lambda: "must not start")
        release.set()
        await eventually(lambda: pool.snapshot()["inflight"] == 0)
        assert await pool.run(lambda: "next") == "next"
    finally:
        release.set()
        pool.shutdown(wait=True)


@pytest.mark.asyncio
async def test_cancel_pending_does_not_run_it_and_recovers_only_its_slot():
    pool = BoundedWorkPool("test", workers=1, queue_size=1)
    started, release, must_not_run = Event(), Event(), Event()

    def first():
        started.set()
        assert release.wait(5)

    task = asyncio.create_task(pool.run(first))
    queued = None
    try:
        await eventually(started.is_set)
        queued = asyncio.create_task(pool.run(must_not_run.set))
        await eventually(lambda: pool.snapshot()["inflight"] == 2)
        with pytest.raises(WorkCapacityExceeded):
            await pool.run(lambda: None)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert pool.snapshot()["inflight"] == 1
        release.set()
        await task
        assert not must_not_run.is_set()
        assert pool.snapshot()["inflight"] == 0
    finally:
        release.set()
        if queued:
            queued.cancel()
        pool.shutdown(wait=True)


def test_pool_survives_event_loop_changes_and_propagates_context():
    pool = BoundedWorkPool("test", workers=1, queue_size=0)
    trace = ContextVar("trace", default="unset")
    try:
        for value in ("user-one", "user-two"):
            token = trace.set(value)
            assert asyncio.run(pool.run(trace.get)) == value
            trace.reset(token)

        def fail():
            raise ValueError("failure")

        with pytest.raises(ValueError, match="failure"):
            asyncio.run(pool.run(fail))
        assert pool.snapshot()["inflight"] == 0
    finally:
        pool.shutdown(wait=True)
    with pytest.raises(WorkCapacityExceeded, match="shutting down"):
        asyncio.run(pool.run(lambda: None))


def test_closed_event_loop_does_not_release_running_work_prematurely():
    pool = BoundedWorkPool("test", workers=1, queue_size=0)
    release, started = Event(), Event()

    def blocking():
        started.set()
        assert release.wait(5)

    async def original_loop():
        task = asyncio.create_task(pool.run(blocking))
        await eventually(started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(original_loop())
        assert pool.snapshot()["inflight"] == 1
        with pytest.raises(WorkCapacityExceeded):
            asyncio.run(pool.run(lambda: None))
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert pool.snapshot()["inflight"] == 0
