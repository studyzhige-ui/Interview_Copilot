"""Tests for app.core.background_tasks — lifecycle, exception logging, drain."""
from __future__ import annotations

import asyncio
import logging

import pytest

from app.core.background_tasks import (
    _background_tasks,
    cancel_and_wait_all,
    pending_count,
    safe_background_task,
)


@pytest.fixture(autouse=True)
async def _isolate_background_tasks():
    """Drain any tasks left over from a previous test so counts are deterministic."""
    if _background_tasks:
        await cancel_and_wait_all(timeout=2.0)
    yield
    if _background_tasks:
        await cancel_and_wait_all(timeout=2.0)


async def test_safe_background_task_returns_result_and_untracks_on_completion():
    async def simple():
        return 42

    task = safe_background_task(simple(), name="simple_ok")
    assert task in _background_tasks
    assert pending_count() == 1

    result = await task
    assert result == 42

    # done_callback fires synchronously when we await, but give the loop a tick
    # in case the scheduler defers it.
    for _ in range(5):
        if task not in _background_tasks:
            break
        await asyncio.sleep(0)
    assert task not in _background_tasks
    assert pending_count() == 0


async def test_safe_background_task_logs_exception(caplog):
    async def boom():
        raise RuntimeError("kaboom-marker")

    with caplog.at_level(logging.ERROR, logger="app.core.background_tasks"):
        task = safe_background_task(boom(), name="boomer")
        # Wait for the task to finish and the done_callback to fire.
        with pytest.raises(RuntimeError):
            await task
        # done_callback may run on a separate scheduler tick.
        for _ in range(10):
            if any("kaboom-marker" in r.getMessage() for r in caplog.records):
                break
            await asyncio.sleep(0.01)

    msgs = [r.getMessage() for r in caplog.records]
    assert any("kaboom-marker" in m for m in msgs), msgs
    assert any("boomer" in m for m in msgs), msgs


async def test_cancel_and_wait_all_drains_pending_tasks():
    async def forever():
        await asyncio.sleep(3600)

    safe_background_task(forever(), name="drain1")
    safe_background_task(forever(), name="drain2")
    safe_background_task(forever(), name="drain3")
    assert pending_count() == 3

    await cancel_and_wait_all(timeout=2.0)
    assert pending_count() == 0
    assert not _background_tasks


async def test_cancel_and_wait_all_is_safe_when_empty():
    # Should be a no-op, no exceptions.
    assert pending_count() == 0
    await cancel_and_wait_all(timeout=0.1)
    assert pending_count() == 0


async def test_cancelled_task_does_not_log_as_error(caplog):
    async def forever():
        await asyncio.sleep(3600)

    with caplog.at_level(logging.ERROR, logger="app.core.background_tasks"):
        task = safe_background_task(forever(), name="cancelled_one")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)

    error_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert not any("cancelled_one" in m for m in error_messages), error_messages
