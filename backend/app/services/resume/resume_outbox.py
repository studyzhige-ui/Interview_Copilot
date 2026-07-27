"""Durable resume-section Milvus synchronization."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob
from app.services.uploads.outbox_service import enqueue_job, register_handler

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


def _handle_resume_reindex(db: Session, job: OutboxJob) -> None:
    from app.models.resume import Resume
    from app.models.resume_section import ResumeSection
    from app.services.resume.resume_vector_service import resume_vector_service

    resume_id = job.aggregate_id
    if not resume_id:
        return

    resume_vector_service.delete_by_resume(resume_id)
    resume = db.query(Resume).filter(Resume.id == resume_id).first()
    if resume is None or resume.archived_at is not None:
        return

    sections = (
        db.query(ResumeSection)
        .filter(
            ResumeSection.resume_id == resume_id,
            ResumeSection.user_id == resume.user_id,
        )
        .order_by(ResumeSection.order_idx)
        .all()
    )
    try:
        for section in sections:
            resume_vector_service.upsert_section(section, db=db)
    except Exception:
        for section in sections:
            section.embedding_status = "failed"
        if job.attempts + 1 >= job.max_attempts:
            resume.parse_status = "failed"
            resume.parse_error = "简历向量索引多次重试仍失败，请重新上传或稍后重试。"
        db.flush()
        raise

    resume.parse_status = "ready"
    resume.parse_error = None
    db.flush()


register_handler(JOB_RESUME_REINDEX, _handle_resume_reindex)
