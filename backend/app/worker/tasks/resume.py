"""Canonical resume Artifact parsing on the pipeline queue."""

import logging

from app.core.async_runtime import run_async
from app.core.error_messages import humanize_error
from app.db.database import SessionLocal
from app.task_queue.celery_app import celery_app

logger = logging.getLogger(__name__)


def _process_artifact_resume(resume_id: str) -> dict[str, str]:
    """Extract one canonical Artifact version and create Profile candidates."""

    import os

    from app.core.runtime_files import create_runtime_temp_file
    from app.models.user import User
    from app.services.resume import resume_artifact_service
    from app.services.uploads.file_asset_service import get_file_asset

    with SessionLocal() as db:
        owner_pk = _artifact_owner_pk(db, resume_id)
        if owner_pk is None:
            # A broker may still contain a pre-cut-over task id. Retire it
            # explicitly; never fall back to mutating the legacy resumes table.
            return {"status": "retired_legacy_resume", "resume_id": resume_id}
        record = resume_artifact_service.claim_resume_parse(
            db,
            user_pk=owner_pk,
            resume_id=resume_id,
        )
        if record is None:
            return {"status": "skipped", "resume_id": resume_id}
        source_version_id = record.current_version.id
        owner_username = db.query(User.username).filter(User.id == owner_pk).scalar()
        text = (record.current_version.content_text or "").strip()
        file_asset_id = record.current_version.file_asset_id
        db.commit()

    try:
        if not text and file_asset_id:
            with SessionLocal() as db:
                asset = get_file_asset(db, file_asset_id)
                storage_uri = (
                    asset.storage_uri
                    if asset is not None and asset.user_id == owner_pk
                    else None
                )
                object_key = asset.object_key if asset is not None else ""
            if storage_uri and storage_uri.startswith("s3://"):
                from app.core.storage import download_file_from_s3
                from app.services.interview.document_text import extract_document_text

                _, ext = os.path.splitext(object_key or "")
                tmp_path = create_runtime_temp_file(suffix=ext or ".pdf")
                try:
                    download_file_from_s3(storage_uri, tmp_path)
                    text = (extract_document_text(tmp_path) or "").strip()
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

        if not text:
            with SessionLocal() as db:
                resume_artifact_service.mark_parse_state(
                    db,
                    user_pk=owner_pk,
                    resume_id=resume_id,
                    status="failed",
                    error="No extractable resume text",
                    source_version_id=source_version_id,
                )
                db.commit()
            return {"status": "failed", "resume_id": resume_id}

        candidates = run_async(
            resume_artifact_service.extract_profile_candidates(
                text, user_id=owner_username
            )
        )
        with SessionLocal() as db:
            resume_artifact_service.persist_extracted_resume(
                db,
                user_pk=owner_pk,
                resume_id=resume_id,
                source_version_id=source_version_id,
                text=text,
                candidates=candidates,
            )
            db.commit()
        return {"status": "ready", "resume_id": resume_id}
    except resume_artifact_service.ResumeArtifactStaleVersionError:
        logger.info(
            "Ignored stale Resume Artifact parse %s/%s",
            resume_id,
            source_version_id,
        )
        return {"status": "stale", "resume_id": resume_id}
    except Exception as exc:
        with SessionLocal() as db:
            try:
                resume_artifact_service.mark_parse_state(
                    db,
                    user_pk=owner_pk,
                    resume_id=resume_id,
                    status="failed",
                    error=f"解析失败：{humanize_error(exc)}"[:500],
                    source_version_id=source_version_id,
                )
                db.commit()
            except resume_artifact_service.ResumeArtifactStaleVersionError:
                db.rollback()
        raise


def _artifact_owner_pk(db, resume_id: str) -> int | None:
    from app.models.artifact import Artifact, ArtifactResumeState

    owner_pk = (
        db.query(Artifact.user_id)
        .join(ArtifactResumeState, ArtifactResumeState.artifact_id == Artifact.id)
        .filter(Artifact.id == resume_id, Artifact.kind == "resume")
        .scalar()
    )
    return int(owner_pk) if owner_pk is not None else None


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
    """Parse one canonical ``Artifact(kind='resume')`` current version.

    The task name and argument shape remain stable for already-published broker
    messages. Unknown or retired legacy Resume identities terminate without a
    write; ArtifactVersion and ArtifactResumeState are the only live owners.
    """
    try:
        return _process_artifact_resume(resume_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Resume Artifact parse failed for %s: %s", resume_id, exc)
        raise
