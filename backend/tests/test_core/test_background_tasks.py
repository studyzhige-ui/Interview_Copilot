"""测试 app.core.background_tasks 的任务追踪与生命周期管理。"""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_safe_background_task_tracks_and_removes():
    """safe_background_task 应将任务加入追踪集合，完成后自动移除。"""
    from app.core.background_tasks import safe_background_task, _background_tasks

    before = len(_background_tasks)

    async def simple():
        return 42

    task = safe_background_task(simple())
    assert len(_background_tasks) == before + 1

    result = await task
    assert result == 42

    # Give the done callback a chance to fire.
    await asyncio.sleep(0.05)
    assert task not in _background_tasks


@pytest.mark.asyncio
async def test_safe_background_task_logs_exception(caplog):
    """异常任务应被记录到日志而非静默丢失。"""
    from app.core.background_tasks import safe_background_task

    async def failing():
        raise ValueError("test explosion")

    task = safe_background_task(failing(), name="test_failing_task")
    # Wait for the task to finish
    await asyncio.sleep(0.1)

    assert task.done()
    assert any("test explosion" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_cancel_and_wait_all_drains():
    """cancel_and_wait_all 应取消并排空所有挂起任务。"""
    from app.core.background_tasks import safe_background_task, cancel_and_wait_all, pending_count

    async def forever():
        await asyncio.sleep(3600)

    safe_background_task(forever(), name="drain_test_1")
    safe_background_task(forever(), name="drain_test_2")
    assert pending_count() >= 2

    await cancel_and_wait_all(timeout=2.0)
    assert pending_count() == 0
