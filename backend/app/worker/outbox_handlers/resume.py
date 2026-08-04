"""Worker handler for durable resume-index synchronization."""

from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob
from app.services.outbox import register_handler
from app.services.resume.reindex_jobs import JOB_RESUME_REINDEX


def handle_resume_reindex(db: Session, job: OutboxJob) -> None:
    from app.models.resume import Resume
    from app.models.resume_section import ResumeSection
    from app.services.resume.resume_vector_service import resume_vector_service

    resume_id = job.aggregate_id
    if not resume_id:
        raise ValueError(f"{JOB_RESUME_REINDEX}: job {job.id} has no resume id")
    resume = db.query(Resume).filter(Resume.id == resume_id).first()
    if resume is not None and resume.user_id != job.user_id:
        raise PermissionError("resume-index job owner does not match resume owner")
    resume_vector_service.delete_by_resume(resume_id)
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


register_handler(JOB_RESUME_REINDEX, handle_resume_reindex)

__all__ = ["handle_resume_reindex"]
