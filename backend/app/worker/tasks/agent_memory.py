"""Optional, privacy-gated consolidation into canonical Agent Memory."""

from app.core.async_runtime import run_async
from app.task_queue.celery_app import celery_app


@celery_app.task(name="tasks.consolidate_agent_memory")
def consolidate_agent_memory(turn_id: str) -> int:
    from app.services.agent_memory_service import consolidate_completed_turn

    return int(run_async(consolidate_completed_turn(turn_id)))


__all__ = ["consolidate_agent_memory"]
