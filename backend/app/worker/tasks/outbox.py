"""Outbox drain task — reliable cross-system side effects (pipeline queue)."""

import logging

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.drain_outbox_jobs",
    # Some handlers perform embedding or an internal-model extraction. Keep
    # the batch bounded, but allow enough time for those durable operations.
    time_limit=900,
    soft_time_limit=840,
)
def drain_outbox_jobs(self):
    """Process due ``outbox_jobs`` — reliable cross-system side effects.

    Runs every minute (beat). Claims a batch of due jobs and runs each
    registered handler with retry/backoff. Idempotent and lock-guarded, so
    overlapping runs are safe.
    """
    from app.db.database import SessionLocal
    from app.services.uploads.outbox_service import run_due_outbox_jobs

    # Import for side effect: register the handlers before any job is claimed —
    # Milvus ability-index (upsert/delete_memory_ability_index), the memory
    # extraction jobs (extract_memory_realtime / extract_memory_dreaming), and
    # the Milvus knowledge-index jobs (milvus_delete_document /
    # milvus_upsert_document).
    import app.services.knowledge.knowledge_outbox  # noqa: F401
    import app.services.memory.ability_outbox  # noqa: F401
    import app.services.memory.extraction_jobs  # noqa: F401
    import app.services.resume.resume_outbox  # noqa: F401

    with SessionLocal() as db:
        processed = run_due_outbox_jobs(db, limit=10)
    if processed:
        logger.info("drain_outbox_jobs: processed %d job(s)", processed)
    return {"processed": processed}
