"""Resume parse + section-indexing task (light queue)."""

import logging

from app.core.error_messages import humanize_error
from app.db.database import SessionLocal
from app.worker.celery_app import celery_app
from app.worker.tasks.runtime import run_async

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.process_resume_parse",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    time_limit=600,
    soft_time_limit=540,
)
def process_resume_parse(self, resume_id: str):
    """Parse a personal ``resumes`` entity into ``resume_sections`` + index them.

    Resolves the resume's text (``raw_text_snapshot``, else extracted from its
    ``file_asset``), runs the LLM sectioner, persists sections keyed by
    ``resume_id``, and vectorizes each into the resume Milvus collection. Sets
    ``resumes.parse_status`` ready/failed. Idempotent: ``extract_and_store``
    delete-then-inserts by ``resume_id``.
    """
    import os
    import tempfile

    from app.models.resume import Resume
    from app.services.resume.resume_service import resume_service
    from app.services.uploads.file_asset_service import get_file_asset

    db = SessionLocal()
    try:
        resume = db.query(Resume).filter(Resume.id == resume_id).first()
        if resume is None:
            return {"status": "missing", "resume_id": resume_id}
        text = (resume.raw_text_snapshot or "").strip()
        owner_pk = resume.user_id
        # LLM resolution is username-keyed (user_model_credentials joins on
        # users.username) — resolve it once for the sectioner (MDL-1).
        from app.models.user import User

        owner_username = db.query(User.username).filter(User.id == owner_pk).scalar()
        file_asset_id = resume.file_asset_id
    finally:
        db.close()

    # Extract text from the source file_asset when no snapshot was supplied.
    if not text and file_asset_id:
        db = SessionLocal()
        try:
            fa = get_file_asset(db, file_asset_id)
            storage_uri = fa.storage_uri if fa and fa.user_id == owner_pk else None
            object_key = fa.object_key if fa else ""
        finally:
            db.close()
        if storage_uri and storage_uri.startswith("s3://"):
            from app.core.storage import download_file_from_s3
            from app.services.voice.file_parser import extract_resume_text

            _, ext = os.path.splitext(object_key or "")
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext or ".pdf")
            os.close(tmp_fd)
            try:
                download_file_from_s3(storage_uri, tmp_path)
                text = (extract_resume_text(tmp_path) or "").strip()
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

    try:
        if text:
            run_async(
                resume_service.extract_and_store(
                    user_pk=owner_pk,
                    resume_id=resume_id,
                    resume_text=text,
                    user_id=owner_username,
                )
            )
        db = SessionLocal()
        try:
            resume = db.query(Resume).filter(Resume.id == resume_id).first()
            if resume is not None:
                if text and not (resume.raw_text_snapshot or "").strip():
                    resume.raw_text_snapshot = text[:20000]
                resume.parse_status = "ready" if text else "failed"
                resume.parse_error = None if text else "No extractable resume text"
                db.add(resume)
                db.commit()
        finally:
            db.close()
        return {"status": "ready" if text else "failed", "resume_id": resume_id}
    except Exception as exc:  # noqa: BLE001
        db = SessionLocal()
        try:
            resume = db.query(Resume).filter(Resume.id == resume_id).first()
            if resume is not None:
                resume.parse_status = "failed"
                resume.parse_error = f"解析失败：{humanize_error(exc)}"[:500]
                db.add(resume)
                db.commit()
        finally:
            db.close()
        logger.error("Resume parse failed for %s: %s", resume_id, exc)
        raise
