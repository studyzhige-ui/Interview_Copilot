"""Durable job producer for resume-section Milvus synchronization."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.outbox import enqueue_job

JOB_RESUME_REINDEX = "milvus_reindex_resume"


def enqueue_resume_reindex(db: Session, *, user_pk: int, resume_id: str) -> None:
    """Queue a rebuild from current Postgres facts in the caller's transaction."""
    enqueue_job(
        db,
        user_pk=user_pk,
        job_type=JOB_RESUME_REINDEX,
        aggregate_type="resume",
        aggregate_id=resume_id,
    )


__all__ = ["JOB_RESUME_REINDEX", "enqueue_resume_reindex"]
