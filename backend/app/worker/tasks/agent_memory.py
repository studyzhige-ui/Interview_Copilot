"""Optional, privacy-gated consolidation into canonical Agent Memory."""

from app.core.async_runtime import run_async
from app.task_queue.celery_app import celery_app


@celery_app.task(name="tasks.consolidate_agent_memory")
def consolidate_agent_memory(turn_id: str) -> int:
    from app.memory.consolidation import process_turn

    return int(run_async(process_turn(turn_id)))


@celery_app.task(name="tasks.discover_agent_memories")
def discover_agent_memories() -> int:
    from app.memory.consolidation import discover_turns
    from app.core.config import settings
    from app.db.database import SessionLocal
    from app.models.memory_pipeline import MemoryWorkspace, MemoryExtraction

    if not settings.AGENT_MEMORY_PRODUCER_ENABLED:
        return 0
    turns = discover_turns()
    for turn_id in turns:
        consolidate_agent_memory.delay(turn_id)
    # Reconcile successful extraction whose phase-2 dispatch/publication was lost.
    with SessionLocal() as db:
        owners = {
            r.user_id
            for r in db.query(MemoryWorkspace.user_id)
            .order_by(MemoryWorkspace.updated_at)
            .limit(settings.AGENT_MEMORY_SCAN_LIMIT)
            .all()
        }
        owners.update(
            r.user_id
            for r in db.query(MemoryExtraction.user_id)
            .outerjoin(
                MemoryWorkspace, MemoryWorkspace.user_id == MemoryExtraction.user_id
            )
            .filter(
                MemoryExtraction.status == "succeeded",
                MemoryWorkspace.user_id.is_(None),
            )
            .distinct()
            .limit(settings.AGENT_MEMORY_SCAN_LIMIT)
            .all()
        )
    for user_id in owners:
        consolidate_user_memories.delay(user_id)
    return len(turns)


@celery_app.task(name="tasks.consolidate_user_memories")
def consolidate_user_memories(user_id: int) -> int:
    from app.memory.consolidation import consolidate_user

    return int(run_async(consolidate_user(user_id)))


__all__ = ["consolidate_agent_memory"]
