"""Intake orchestration for the upload-analysis flow (POST /analyze).

Resolves the optional resume / JD context onto text snapshots, creates the
InterviewRecord, consumes the audio upload, and dispatches the Celery
analysis task. The API layer keeps only HTTP concerns (auth, status-code
mapping); everything here is plain domain logic.

Error contract: resolution helpers raise the domain errors below; the API
maps them to 404s. Snapshot extraction failures are non-fatal (the record
is still created without the snapshot) — the caller decides how loudly to
log them.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.services.interview.interview_record_service import (
    STATUS_FAILED,
    STATUS_PENDING,
    interview_record_service,
)
from app.services.uploads.file_asset_service import (
    get_owned_file_asset,
    mark_file_asset_consumed,
)
from app.worker.tasks import process_interview_analysis

logger = logging.getLogger(__name__)


class ResumeNotFound(Exception):
    """The referenced personal resume does not exist / isn't owned by the user."""


class ResumeUploadNotFound(Exception):
    """The referenced ad-hoc resume file_asset does not exist / isn't owned."""


@dataclass
class ResumeContext:
    resume_id: Optional[str] = None
    resume_file_asset_id: Optional[str] = None
    resume_source: str = "none"
    resume_title_snapshot: Optional[str] = None
    resume_text: str = ""


def extract_text_snapshot(db: Session, file_asset_id: str, user_id: str) -> str:
    """Download a resume/JD file asset and return its plain text (truncated)."""
    import os
    import tempfile

    from app.core.storage import download_file_from_s3
    from app.services.voice.file_parser import extract_resume_text

    upload = get_owned_file_asset(db, file_asset_id=file_asset_id, user_id=user_id)
    if upload is None or not upload.storage_uri:
        return ""
    if not upload.storage_uri.startswith("s3://"):
        return ""

    _, ext = os.path.splitext(upload.object_key or "")
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext or ".pdf")
    os.close(tmp_fd)
    try:
        download_file_from_s3(upload.storage_uri, tmp_path)
        return (extract_resume_text(tmp_path) or "")[:12000]
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def resolve_resume_context(
    db: Session,
    *,
    user_id: str,
    resume_id: Optional[str],
    resume_file_asset_id: Optional[str],
) -> ResumeContext:
    """Resolve the analyze request's resume input onto a text snapshot.

    A personal resume entity (``resume_id``) wins over an ad-hoc file
    uploaded just for this interview (``resume_file_asset_id``). Both
    snapshot their text onto the record so history never re-reads them.
    """
    ctx = ResumeContext()
    if resume_id:
        from app.services.resume import resume_entity_service

        resume = resume_entity_service.get_owned_resume(
            db, resume_id=resume_id, user_id=user_id,
        )
        if resume is None:
            raise ResumeNotFound(resume_id)
        ctx.resume_id = resume.id
        ctx.resume_source = "personal_resume"
        ctx.resume_title_snapshot = resume.title
        ctx.resume_text = resume.raw_text_snapshot or ""
    elif resume_file_asset_id:
        resume_upload = get_owned_file_asset(
            db, file_asset_id=resume_file_asset_id,
            user_id=user_id, purpose="resume",
        )
        if resume_upload is None:
            raise ResumeUploadNotFound(resume_file_asset_id)
        ctx.resume_file_asset_id = resume_upload.id
        ctx.resume_source = "context_upload"
        # extract_text_snapshot downloads + parses (sync I/O + CPU);
        # offload so the caller's event loop isn't pinned. Non-fatal.
        try:
            ctx.resume_text = await asyncio.to_thread(
                extract_text_snapshot, db, resume_upload.id, user_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Resume snapshot extraction failed: %s", exc)
    return ctx


async def resolve_jd_context(
    db: Session,
    *,
    user_id: str,
    jd_text: Optional[str],
    jd_file_asset_id: Optional[str],
) -> tuple[str, Optional[str]]:
    """Resolve the JD input: direct text wins; else extract from a jd file_asset.

    JD is never a knowledge document — it only lives as a snapshot on the
    record. Returns ``(jd_text, jd_file_asset_id_used)``.
    """
    text = (jd_text or "").strip()
    used_asset_id: Optional[str] = None
    if not text and jd_file_asset_id:
        jd_upload = get_owned_file_asset(
            db, file_asset_id=jd_file_asset_id,
            user_id=user_id, purpose="jd",
        )
        if jd_upload is not None:
            used_asset_id = jd_upload.id
            try:
                text = await asyncio.to_thread(
                    extract_text_snapshot, db, jd_upload.id, user_id,
                ) or ""
            except Exception:  # noqa: BLE001
                text = ""
    return text, used_asset_id


def normalize_language(language: Optional[str]) -> str:
    """Anything other than the hints we support falls back to "zh".

    WhisperX accepts "auto" by passing ``None``, which the orchestrator
    translates.
    """
    lang = (language or "zh").strip().lower()
    return lang if lang in {"zh", "en", "auto"} else "zh"


def create_record_and_dispatch(
    db: Session,
    *,
    user_id: str,
    upload,
    resume_ctx: ResumeContext,
    jd_text: str,
    jd_file_asset_id: Optional[str],
    language: Optional[str],
):
    """Create the InterviewRecord, consume the upload, dispatch the analysis.

    Returns ``(record, celery_task)``.
    """
    record = interview_record_service.create_for_upload(
        user_id=user_id,
        title=f"面试录音 {upload.original_filename or upload.id}",
        audio_file_asset_id=upload.id,
        resume_id=resume_ctx.resume_id,
        resume_file_asset_id=resume_ctx.resume_file_asset_id,
        resume_source=resume_ctx.resume_source,
        resume_title_snapshot=resume_ctx.resume_title_snapshot,
        jd_file_asset_id=jd_file_asset_id,
        resume_text_snapshot=resume_ctx.resume_text,
        jd_text_snapshot=jd_text,
        db=db,
    )
    mark_file_asset_consumed(db, upload)
    db.commit()

    try:
        task = process_interview_analysis.delay(
            record.id, language=normalize_language(language),
        )
    except Exception as exc:  # noqa: BLE001 — broker down / misconfigured
        # The record + consumed upload are already committed. Without this
        # catch a broker blip left a zombie forever-pending record that no
        # worker would ever pick up. Park it in a terminal, user-visible
        # state instead (recovery today = delete the record and re-upload;
        # there is no reanalyze endpoint for upload records).
        logger.error("analysis dispatch failed for record %s: %s", record.id, exc)
        interview_record_service.set_status(
            record.id, STATUS_FAILED,
            error_message="分析任务派发失败（任务队列暂不可用），请稍后重试。",
        )
        raise
    interview_record_service.set_status(record.id, STATUS_PENDING, celery_task_id=task.id)
    return record, task
