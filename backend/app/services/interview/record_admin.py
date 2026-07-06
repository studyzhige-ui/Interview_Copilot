"""Owned-record access + maintenance operations for interview records.

The API routers call these instead of writing ORM queries inline: ownership
lookups, field updates, analysis cancellation, the full cascade delete, and
the SSE poll snapshot. All functions are synchronous; the SSE caller wraps
them in ``asyncio.to_thread``.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.services.interview.interview_record_service import STATUS_FAILED

logger = logging.getLogger(__name__)


def get_owned_record(db: Session, record_id: str, username: str) -> InterviewRecord | None:
    """The record iff it exists and belongs to *username* (else None)."""
    return (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.id == record_id,
            InterviewRecord.user_id == resolve_user_pk(db, username),
        )
        .first()
    )


def get_owned_qa(db: Session, *, user_pk, record_id: str, qa_id: str) -> InterviewQA | None:
    """A QA row iff it belongs to *record_id* and that record to *user_pk*."""
    return (
        db.query(InterviewQA)
        .join(InterviewRecord, InterviewQA.record_id == InterviewRecord.id)
        .filter(
            InterviewQA.id == qa_id,
            InterviewQA.record_id == record_id,
            InterviewRecord.user_id == user_pk,
        )
        .first()
    )


def cancel_analysis(db: Session, record: InterviewRecord) -> bool:
    """Revoke the record's running Celery task and mark it cancelled.

    Returns True iff a task revoke was actually issued.
    """
    revoked = False
    if record.celery_task_id:
        try:
            from app.worker.celery_app import celery_app
            celery_app.control.revoke(record.celery_task_id, terminate=True, signal="SIGTERM")
            revoked = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to revoke celery task %s: %s", record.celery_task_id, exc,
            )
    record.status = STATUS_FAILED
    record.error_message = "cancelled"
    db.add(record)
    db.commit()
    return revoked


def update_record_fields(
    db: Session,
    record: InterviewRecord,
    *,
    title: str | None,
    tag: str | None,
) -> bool:
    """Apply the PATCHable fields. Returns False when nothing was given."""
    changed = False
    if title is not None:
        record.title = title.strip()
        changed = True
    if tag is not None:
        record.tag = tag.strip() or None
        changed = True
    if not changed:
        return False
    db.add(record)
    db.commit()
    db.refresh(record)
    return True


def _enqueue_record_asset_deletes(db: Session, record: InterviewRecord) -> None:
    """Queue blob deletes + drop the file_asset rows a record exclusively
    owns: its audio recording and the ad-hoc JD / resume files uploaded just
    for this analysis. Personal resumes (``resume_id``) are a separate
    entity and are never touched."""
    from app.models.file_asset import FileAsset
    from app.services.uploads.file_asset_service import enqueue_asset_blob_delete

    asset_ids = {
        aid
        for aid in (
            record.audio_file_asset_id,
            record.jd_file_asset_id,
            record.resume_file_asset_id,
        )
        if aid
    }
    if not asset_ids:
        return
    assets = (
        db.query(FileAsset)
        .filter(FileAsset.id.in_(asset_ids), FileAsset.user_id == record.user_id)
        .all()
    )
    for asset in assets:
        enqueue_asset_blob_delete(db, asset)
        db.delete(asset)


def delete_record_cascade(
    db: Session,
    record: InterviewRecord,
    *,
    cascade_knowledge: bool = False,
) -> dict:
    """Hard-delete an interview record AND every trace tied to it.

    Removes, in order:

      1. **conversation_messages** for every session linked to this interview
         (the FK has no ON DELETE CASCADE, so we have to be explicit).
      2. **conversations** bound to this interview (``subject_id == X``).
      3. **mock_interview_runtime** (explicit — SQLite doesn't enforce the FK
         cascade) and **interview_qa** (auto via ON DELETE CASCADE on
         ``interview_records``).
      4. The **interview_record** row itself.

    Designed for "I want this interview gone — no leftover chat history."

    **v3 memory survives.** Knowledge / strategy / habit / user_profile
    docs accumulate across ALL of a user's interviews — they're
    personal memory, not record artefacts. Deleting a record does NOT
    touch them. If the user wants to wipe specific memory entries,
    they use the ``/memory/*`` endpoints. (The legacy v2 cascade —
    ``memory_items WHERE source_session_id IN sessions`` + Milvus row
    deletes — is gone with the ``memory_items`` table itself.)

    With ``cascade_knowledge`` the improved_qa knowledge documents this
    interview's QAs published are removed too (RFC §10.3 — user opt-in).

    Returns ``{"deleted_sessions": N, "deleted_knowledge_docs": N}``.
    Raises on failure after rolling back.
    """
    from app.models.chat import ConversationMessage, Conversation
    from app.models.mock_interview_runtime import MockInterviewRuntime

    record_id = record.id

    removed_docs = 0
    if cascade_knowledge:
        from app.services.knowledge.qa_publish_service import (
            delete_saved_qa_docs_for_record,
        )
        removed_docs = delete_saved_qa_docs_for_record(
            db, user_pk=record.user_id, record_id=record_id,
        )

    try:
        # ── (1) Find every conversation linked to this interview ──────────
        session_ids = [
            row[0]
            for row in db.query(Conversation.id)
            .filter(Conversation.subject_id == record_id)
            .all()
        ]

        # ── (1b) Storage blobs (UP-2) — queue object deletes BEFORE the
        # referencing rows disappear. Mock voice clips hang off the
        # conversations' messages; the audio / ad-hoc JD / ad-hoc resume
        # uploads hang off the record row. Blob deletion rides the outbox so
        # a MinIO blip can't fail the user-facing delete.
        from app.services.interview.mock_flow import delete_mock_audio_assets

        for sid in session_ids:
            delete_mock_audio_assets(db, sid, record.user_id)
        _enqueue_record_asset_deletes(db, record)

        # ── (2) DB deletes in safe order ─────────────────────────────────
        if session_ids:
            db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id.in_(session_ids)
            ).delete(synchronize_session=False)
            db.query(Conversation).filter(
                Conversation.id.in_(session_ids)
            ).delete(synchronize_session=False)
        # mock_interview_runtime has ON DELETE CASCADE on interview_records, but
        # SQLite (tests) doesn't enforce FK cascades — delete it explicitly so
        # behavior is uniform across Postgres and SQLite (no orphan runtime).
        db.query(MockInterviewRuntime).filter(
            MockInterviewRuntime.interview_record_id == record_id
        ).delete(synchronize_session=False)
        # interview_qa auto-cleaned by ON DELETE CASCADE on interview_records.
        db.delete(record)
        db.commit()
        logger.info(
            "Deleted interview_record=%s with %d session(s)",
            record_id, len(session_ids),
        )
        return {
            "deleted_sessions": len(session_ids),
            "deleted_knowledge_docs": removed_docs,
        }
    except Exception:
        db.rollback()
        raise


def poll_record_snapshot(record_id: str) -> dict | None:
    """One-shot DB read for the SSE poll loop.

    Each call opens its own short-lived ``SessionLocal()`` and closes
    it immediately. Returns a plain dict — the ORM row is NOT
    returned outside the session scope (that would trigger
    DetachedInstanceError on any lazy-loaded attribute). Returns
    ``None`` if the row disappeared between polls.

    Designed to run inside ``asyncio.to_thread`` so the sync DB
    round-trip doesn't block the event loop. Without this, 20
    concurrent SSE viewers each holding a request-scoped session
    for up to 8 minutes (320 ticks × 1.5s) would exhaust the
    DB_POOL_SIZE=20 pool and the loop would stall on every query.
    """
    with SessionLocal() as db:
        row = (
            db.query(InterviewRecord)
            .filter(InterviewRecord.id == record_id)
            .first()
        )
        if row is None:
            return None
        # Denominator for the analyzing-stage progress interpolation: the
        # QA shells are persisted before the analyzing status flips, so by
        # the time the FE needs a percent this is stable.
        qa_total = (
            db.query(InterviewQA)
            .filter(InterviewQA.record_id == record_id)
            .count()
        )
        return {
            "id": row.id,
            "status": (row.status or "").lower(),
            "analyzed_qa_count": row.analyzed_qa_count or 0,
            "qa_total": qa_total,
            "analysis_json": row.analysis_json,
            "error_message": row.error_message,
        }


def record_exists_for_user(record_id: str, username: str) -> bool:
    """Short owner check with its own session (for long-lived SSE requests)."""
    with SessionLocal() as db:
        return (
            db.query(InterviewRecord.id)
            .filter(
                InterviewRecord.id == record_id,
                InterviewRecord.user_id == resolve_user_pk(db, username),
            )
            .first()
            is not None
        )
