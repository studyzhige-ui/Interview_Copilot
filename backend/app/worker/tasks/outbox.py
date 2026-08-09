"""Resource-isolated drains for reliable cross-system side effects."""

import logging
from collections.abc import Collection

from app.task_queue.celery_app import celery_app

logger = logging.getLogger(__name__)


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
    from app.db.database import SessionLocal
    from app.rag.index.reconciliation import enqueue_stale_documents
    from app.services.outbox import INDEX_JOB_TYPES

    with SessionLocal() as db:
        enqueued = enqueue_stale_documents(db, limit=100)
    result = _drain(INDEX_JOB_TYPES, limit=10)
    result["generation_jobs_enqueued"] = enqueued
    return result


@celery_app.task(
    name="tasks.drain_intelligence_outbox_jobs",
    time_limit=900,
    soft_time_limit=840,
)
def drain_intelligence_outbox_jobs():
    """Run durable memory extraction on the background-intelligence queue."""
    from app.services.outbox import INTELLIGENCE_JOB_TYPES

    return _drain(INTELLIGENCE_JOB_TYPES, limit=4)


@celery_app.task(
    name="tasks.drain_cleanup_outbox_jobs",
    time_limit=300,
    soft_time_limit=270,
)
def drain_cleanup_outbox_jobs():
    """Delete orphaned blobs without loading AI runtimes."""
    from app.services.outbox import CLEANUP_JOB_TYPES

    return _drain(CLEANUP_JOB_TYPES, limit=25)


__all__ = [
    "drain_cleanup_outbox_jobs",
    "drain_index_outbox_jobs",
    "drain_intelligence_outbox_jobs",
]
