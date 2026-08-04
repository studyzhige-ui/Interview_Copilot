"""Resource-isolated drains for reliable cross-system side effects."""

import logging
from collections.abc import Collection

from app.task_queue.celery_app import celery_app

logger = logging.getLogger(__name__)

INDEX_JOB_TYPES = frozenset(
    {
        "milvus_delete_document",
        "milvus_upsert_document",
        "milvus_reindex_resume",
        "upsert_memory_ability_index",
        "delete_memory_ability_index",
    }
)
INTELLIGENCE_JOB_TYPES = frozenset(
    {"extract_memory_realtime", "extract_memory_dreaming", "dream_check_user"}
)
CLEANUP_JOB_TYPES = frozenset({"delete_object", "cleanup_failed_upload"})


def _register_handlers() -> None:
    import app.worker.outbox_handlers.ability  # noqa: F401
    import app.worker.outbox_handlers.knowledge  # noqa: F401
    import app.worker.outbox_handlers.memory  # noqa: F401
    import app.worker.outbox_handlers.resume  # noqa: F401


def _drain(job_types: Collection[str], *, limit: int) -> dict[str, int]:
    from app.db.database import SessionLocal
    from app.services.outbox import run_due_outbox_jobs

    _register_handlers()
    with SessionLocal() as db:
        processed = run_due_outbox_jobs(db, limit=limit, job_types=job_types)
    if processed:
        logger.info("outbox drain processed %d job(s)", processed)
    return {"processed": processed}


@celery_app.task(
    name="tasks.drain_index_outbox_jobs",
    time_limit=900,
    soft_time_limit=840,
)
def drain_index_outbox_jobs():
    """Run Milvus/embedding synchronization without waiting for LLM jobs."""
    return _drain(INDEX_JOB_TYPES, limit=10)


@celery_app.task(
    name="tasks.drain_intelligence_outbox_jobs",
    time_limit=900,
    soft_time_limit=840,
)
def drain_intelligence_outbox_jobs():
    """Run durable memory extraction on the background-intelligence queue."""
    return _drain(INTELLIGENCE_JOB_TYPES, limit=4)


@celery_app.task(
    name="tasks.drain_cleanup_outbox_jobs",
    time_limit=300,
    soft_time_limit=270,
)
def drain_cleanup_outbox_jobs():
    """Delete orphaned blobs without loading AI runtimes."""
    return _drain(CLEANUP_JOB_TYPES, limit=25)


__all__ = [
    "CLEANUP_JOB_TYPES",
    "INDEX_JOB_TYPES",
    "INTELLIGENCE_JOB_TYPES",
    "drain_cleanup_outbox_jobs",
    "drain_index_outbox_jobs",
    "drain_intelligence_outbox_jobs",
]
