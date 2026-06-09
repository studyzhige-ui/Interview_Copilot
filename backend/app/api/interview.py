import asyncio
import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_EXPENSIVE, limiter
from app.core.security import get_current_user
from app.db.database import SessionLocal, get_db
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.models.user import User
from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
from app.services.interview.interview_record_service import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    interview_record_service,
)
from app.core.user_identity import resolve_user_pk
from app.services.uploads.file_asset_service import (
    get_owned_file_asset,
    mark_file_asset_consumed,
)
from app.worker.tasks import process_interview_analysis

try:
    from app.rag.ingestion import ingest_text
except ModuleNotFoundError:
    ingest_text = None


router = APIRouter()


# Pydantic schemas now live in app/schemas/interview.py.
from app.schemas.interview import (  # noqa: E402, F401
    AnalyzeRequest,
    InterviewRecordListItem,
    InterviewRecordUpdateRequest,
    MemorySaveRequest,
    QAEditRequest,
    SaveQARequest,
)


@router.get("/uploads/resumes")
def list_user_resumes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the user's personal resumes — the first-class ``resumes`` entity.

    MockSetup / analyze setup pass the returned ``resume_id`` to start a mock or
    dispatch an analysis. Resumes are a personal-profile asset and are NOT
    knowledge documents.
    """
    from app.services.resume import resume_entity_service

    resumes = resume_entity_service.list_resumes(db, user_id=current_user.username)
    return {
        "resumes": [
            {
                "resume_id": r.id,
                "title": r.title,
                "is_default": bool(r.is_default),
                "parse_status": r.parse_status,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in resumes
        ],
    }


@router.post("/analyze")
@limiter.limit(RATE_EXPENSIVE)
async def analyze_interview_endpoint(
    request: Request,
    response: Response,
    body: AnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an InterviewRecord from an uploaded audio file and dispatch the
    unified analysis orchestrator."""
    try:
        upload = get_owned_file_asset(
            db,
            file_asset_id=body.upload_id,
            user_id=current_user.username,
            purpose="interview_audio",
        )
        if upload is None:
            raise HTTPException(status_code=404, detail="Audio upload not found")
        if upload.upload_status not in {"pending_upload", "uploaded"}:
            raise HTTPException(status_code=409, detail="Audio upload has already been consumed")

        # Resume context: a personal resume entity (resume_id) OR an ad-hoc file
        # uploaded just for this interview (resume_file_asset_id). Both snapshot
        # their text onto the record so history never re-reads them. Optional.
        resume_id: Optional[str] = None
        resume_file_asset_id: Optional[str] = None
        resume_source = "none"
        resume_title_snapshot: Optional[str] = None
        resume_text = ""
        if body.resume_id:
            from app.services.resume import resume_entity_service

            resume = resume_entity_service.get_owned_resume(
                db, resume_id=body.resume_id, user_id=current_user.username,
            )
            if resume is None:
                raise HTTPException(status_code=404, detail="Resume not found")
            resume_id = resume.id
            resume_source = "personal_resume"
            resume_title_snapshot = resume.title
            resume_text = resume.raw_text_snapshot or ""
        elif body.resume_file_asset_id:
            resume_upload = get_owned_file_asset(
                db, file_asset_id=body.resume_file_asset_id,
                user_id=current_user.username, purpose="resume",
            )
            if resume_upload is None:
                raise HTTPException(status_code=404, detail="Resume upload not found")
            resume_file_asset_id = resume_upload.id
            resume_source = "context_upload"
            # _extract_resume_snapshot downloads + parses (sync I/O + CPU);
            # offload so the endpoint doesn't pin the event loop. Non-fatal.
            try:
                resume_text = await asyncio.to_thread(
                    _extract_resume_snapshot, db, resume_upload.id, current_user.username,
                )
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning("Resume snapshot extraction failed: %s", exc)

        # JD context: direct text wins; else extract from a jd file_asset. JD is
        # never a knowledge document — it only lives as a snapshot on the record.
        jd_text = (body.jd_text or "").strip()
        jd_file_asset_id: Optional[str] = None
        if not jd_text and body.jd_file_asset_id:
            jd_upload = get_owned_file_asset(
                db, file_asset_id=body.jd_file_asset_id,
                user_id=current_user.username, purpose="jd",
            )
            if jd_upload is not None:
                jd_file_asset_id = jd_upload.id
                try:
                    jd_text = await asyncio.to_thread(
                        _extract_resume_snapshot, db, jd_upload.id, current_user.username,
                    ) or ""
                except Exception:  # noqa: BLE001
                    jd_text = ""

        record = interview_record_service.create_for_upload(
            user_id=current_user.username,
            title=f"面试录音 {upload.original_filename or upload.id}",
            audio_file_asset_id=upload.id,
            resume_id=resume_id,
            resume_file_asset_id=resume_file_asset_id,
            resume_source=resume_source,
            resume_title_snapshot=resume_title_snapshot,
            jd_file_asset_id=jd_file_asset_id,
            resume_text_snapshot=resume_text,
            jd_text_snapshot=jd_text,
            db=db,
        )
        mark_file_asset_consumed(db, upload)
        db.commit()

        # Normalize language hint: anything other than the two we explicitly
        # support falls back to "zh". WhisperX accepts "auto" by passing
        # ``None``, which the orchestrator translates.
        language = (body.language or "zh").strip().lower()
        if language not in {"zh", "en", "auto"}:
            language = "zh"
        task = process_interview_analysis.delay(record.id, language=language)
        interview_record_service.set_status(record.id, "pending", celery_task_id=task.id)

        return {
            "status": "processing",
            "message": "Task dispatched to background workers successfully.",
            "record_id": record.id,
            "task_id": task.id,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/analyze/{record_id}/cancel")
async def cancel_analysis(
    record_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke a running analysis task. Used when the user discards the draft
    or deletes the in-flight record before completion."""
    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == record_id, InterviewRecord.user_id == resolve_user_pk(db, current_user.username))
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Interview record not found")
    revoked = False
    if record.celery_task_id:
        try:
            from app.worker.celery_app import celery_app
            celery_app.control.revoke(record.celery_task_id, terminate=True, signal="SIGTERM")
            revoked = True
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "Failed to revoke celery task %s: %s", record.celery_task_id, exc,
            )
    record.status = STATUS_FAILED
    record.error_message = "cancelled"
    db.add(record)
    db.commit()
    return {"status": "cancelled", "revoked": revoked, "record_id": record_id}


def _extract_resume_snapshot(db: Session, file_asset_id: str, user_id: str) -> str:
    """Download a resume/JD file asset and return its plain text (truncated)."""
    import os
    import tempfile

    from app.services.storage_service import download_file_from_s3
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


@router.post("/memory/save")
@limiter.limit(RATE_EXPENSIVE)
async def save_personal_memory(
    request: Request,
    response: Response,
    body: MemorySaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        ingest_fn = ingest_text
        if ingest_fn is None:
            from app.rag.ingestion import ingest_text as ingest_fn

        combined_text = (
            f"[Question]\n{body.question}\n\n"
            f"[Improved Answer]\n{body.improved_answer}"
        )
        metadata = {
            "source_kind": "personal_memory",
            "original_score": body.original_score,
            "last_accessed": datetime.now().isoformat(),
        }
        if body.tags:
            metadata["tags"] = ", ".join(body.tags)

        await ingest_fn(
            text=combined_text,
            source_kind="personal_memory",
            user_id=resolve_user_pk(db, current_user.username),
            metadata=metadata,
        )
        return {
            "status": "success",
            "message": f"Saved personal memory with baseline score {body.original_score}.",
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/analytics/report")
async def get_analytics_report(
    limit: int = Query(20, description="Max personal memory items to scan."),
    current_user: User = Depends(get_current_user),
):
    try:
        return await generate_comprehensive_report(limit, user_id=current_user.username)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {exc}") from exc


# ── InterviewRecord endpoints ─────────────────────────────────────────


@router.get("/interview-records", response_model=List[InterviewRecordListItem])
def list_interview_records(
    current_user: User = Depends(get_current_user),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    from app.services.interview.interview_record_service import interview_record_service

    records = interview_record_service.list_by_user(
        current_user.username, offset=offset, limit=limit,
    )
    return [
        InterviewRecordListItem(
            id=r.id,
            source=r.source,
            title=r.title or "",
            tag=r.tag,
            status=r.status,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in records
    ]


@router.get("/interview-records/{record_id}")
def get_interview_record(
    record_id: str,
    current_user: User = Depends(get_current_user),
):
    record = interview_record_service.get(record_id, current_user.username)
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")
    analysis = None
    if record.analysis_json:
        try:
            analysis = json.loads(record.analysis_json)
        except json.JSONDecodeError:
            analysis = None
    qa_rows = interview_record_service.list_qa(record_id)
    transcript = interview_record_service.get_transcript_payload(record_id)
    return {
        "id": record.id,
        "source": record.source,
        "title": record.title,
        "tag": record.tag,
        "category": record.category,
        "status": record.status,
        "analyzed_qa_count": record.analyzed_qa_count,
        "audio_file_asset_id": record.audio_file_asset_id,
        "resume_id": record.resume_id,
        "resume_file_asset_id": record.resume_file_asset_id,
        "resume_source": record.resume_source,
        "jd_file_asset_id": record.jd_file_asset_id,
        "transcript": transcript["text"],
        "transcript_segments": _safe_json_loads(transcript["segments_json"]),
        "interview_plan": _safe_json_loads(record.interview_plan),
        "analysis": analysis,
        "qa": [_serialize_qa(qa) for qa in qa_rows],
        "error_message": record.error_message,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


def _safe_json_loads(value: Optional[str]) -> Optional[object]:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _serialize_qa(qa: InterviewQA) -> dict:
    return {
        "id": qa.id,
        "order_idx": qa.order_idx,
        "phase": qa.phase,
        "phase_label": qa.phase_label,
        "question": qa.question,
        "answer": qa.answer,
        "question_summary": qa.question_summary,
        "is_follow_up": qa.is_follow_up,
        "follow_up_depth": qa.follow_up_depth,
        "grounding_refs": _safe_json_loads(qa.grounding_refs_json) or [],
        "score": qa.score,
        "critique": qa.critique,
        "improved_answer": qa.improved_answer,
        "key_points": _safe_json_loads(qa.key_points_json) or [],
        "answer_input_mode": qa.answer_input_mode,
        "question_audio_url": qa.question_audio_url,
        "answer_audio_url": qa.answer_audio_url,
        "source_segment_start": qa.source_segment_start,
        "source_segment_end": qa.source_segment_end,
        "analyzed_at": qa.analyzed_at.isoformat() if qa.analyzed_at else None,
        "saved_document_id": qa.saved_document_id,
    }


@router.get("/interview-records/{record_id}/summary")
def get_interview_record_summary(
    record_id: str,
    current_user: User = Depends(get_current_user),
):
    """Short analysis summary for context injection (slot 2)."""
    from app.services.interview.interview_record_service import interview_record_service

    summary = interview_record_service.get_analysis_summary(record_id, current_user.username)
    if not summary:
        raise HTTPException(status_code=404, detail="Interview record or analysis not found")
    return {"summary": summary}


@router.patch("/interview-records/{record_id}")
def update_interview_record(
    record_id: str,
    payload: InterviewRecordUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.interview_record import InterviewRecord

    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == record_id, InterviewRecord.user_id == resolve_user_pk(db, current_user.username))
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")
    changed = False
    if payload.title is not None:
        record.title = payload.title.strip()
        changed = True
    if payload.tag is not None:
        record.tag = payload.tag.strip() or None
        changed = True
    if not changed:
        raise HTTPException(status_code=400, detail="No field to update")
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"status": "success", "id": record.id, "title": record.title, "tag": record.tag}


@router.delete("/interview-records/{record_id}")
def delete_interview_record(
    record_id: str,
    cascade_knowledge: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard-delete an interview record AND every trace tied to it.

    Removes, in order:

      1. **conversation_messages** for every session linked to this interview
         (the FK has no ON DELETE CASCADE, so we have to be explicit).
      2. **conversations** linked to this interview (``interview_id == X``).
      3. **interview_qa** + **mock_interview_sessions** (auto via FK
         ON DELETE CASCADE on ``interview_records``).
      4. The **interview_record** row itself.

    Designed for "I want this interview gone — no leftover chat history."

    **v3 memory survives.** Knowledge / strategy / habit / user_profile
    docs accumulate across ALL of a user's interviews — they're
    personal memory, not record artefacts. Deleting a record does NOT
    touch them. If the user wants to wipe specific memory entries,
    they use the ``/memory/*`` endpoints. (The legacy v2 cascade —
    ``memory_items WHERE source_session_id IN sessions`` + Milvus row
    deletes — is gone with the ``memory_items`` table itself.)

    The legacy detach mode (set ``interview_id = NULL``, keep the chat)
    was removed: in practice nobody used it and it produced confusing
    orphan sessions.
    """
    import logging

    log = logging.getLogger(__name__)
    from app.models.chat import ConversationMessage, Conversation
    from app.models.interview_record import InterviewRecord

    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == record_id, InterviewRecord.user_id == resolve_user_pk(db, current_user.username))
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")

    # ── Optional cascade: also remove the improved_qa knowledge documents this
    # interview's QAs published (RFC §10.3 — the user may opt in). ────────────
    removed_docs = 0
    if cascade_knowledge:
        from app.services.knowledge.qa_publish_service import (
            delete_saved_qa_docs_for_record,
        )
        removed_docs = delete_saved_qa_docs_for_record(
            db, user_pk=record.user_id, record_id=record_id,
        )

    try:
        # ── (1) Find every chat_session linked to this interview ──────────
        session_ids = [
            row[0]
            for row in db.query(Conversation.id)
            .filter(Conversation.interview_id == record_id)
            .all()
        ]

        # ── (2) v3 memory is user-scoped, not record-scoped ───────────────
        # Knowledge / strategy / habit docs accumulate across all records
        # for a user — they're personal memory, not record artefacts. We
        # intentionally do NOT cascade-delete them when a record is
        # removed. If the user wants to wipe a specific memory entry,
        # they use the /memory/* endpoints. The legacy
        # ``memory_items WHERE source_session_id IN sessions`` cascade
        # is gone in v3.

        # ── (3) DB deletes in safe order ─────────────────────────────────
        if session_ids:
            db.query(ConversationMessage).filter(
                ConversationMessage.session_id.in_(session_ids)
            ).delete(synchronize_session=False)
            db.query(Conversation).filter(
                Conversation.id.in_(session_ids)
            ).delete(synchronize_session=False)
        # interview_qa + mock_interview_sessions auto-cleaned by their
        # ON DELETE CASCADE on interview_records.
        db.delete(record)
        db.commit()
        log.info(
            "Deleted interview_record=%s with %d session(s)",
            record_id, len(session_ids),
        )
        return {
            "status": "success",
            "id": record_id,
            "deleted_sessions": len(session_ids),
            "deleted_knowledge_docs": removed_docs,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception(
            "delete_interview_record failed for record_id=%s user=%s: %s",
            record_id, current_user.username, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"删除失败: {type(exc).__name__}: {exc}",
        ) from exc


@router.patch("/interview-records/{record_id}/qa/{qa_id}")
def edit_interview_qa(
    record_id: str,
    qa_id: str,
    payload: QAEditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a single InterviewQA row by id."""
    qa = (
        db.query(InterviewQA)
        .join(InterviewRecord, InterviewQA.record_id == InterviewRecord.id)
        .filter(
            InterviewQA.id == qa_id,
            InterviewQA.record_id == record_id,
            InterviewRecord.user_id == resolve_user_pk(db, current_user.username),
        )
        .first()
    )
    if qa is None:
        raise HTTPException(status_code=404, detail="QA row not found")

    if payload.question is not None:
        qa.question = payload.question
    if payload.answer is not None:
        qa.answer = payload.answer
    if payload.critique is not None:
        qa.critique = payload.critique
    if payload.improved_answer is not None:
        qa.improved_answer = payload.improved_answer
    db.add(qa)
    db.commit()
    db.refresh(qa)
    return {"status": "success", "qa": _serialize_qa(qa)}


@router.post("/interview-records/{record_id}/qa/{qa_id}/save-to-knowledge")
@limiter.limit(RATE_EXPENSIVE)
async def save_qa_to_knowledge_endpoint(
    request: Request,
    response: Response,
    record_id: str,
    qa_id: str,
    body: SaveQARequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Publish a QA's improved answer to the knowledge base (RFC §6.9).

    Creates/refreshes a ``knowledge_documents(source_kind='improved_qa')`` from
    question + improved_answer, indexes it, and backfills ``saved_document_id``.
    """
    user_pk = resolve_user_pk(db, current_user.username)
    qa = (
        db.query(InterviewQA)
        .join(InterviewRecord, InterviewQA.record_id == InterviewRecord.id)
        .filter(
            InterviewQA.id == qa_id,
            InterviewQA.record_id == record_id,
            InterviewRecord.user_id == user_pk,
        )
        .first()
    )
    if qa is None:
        raise HTTPException(status_code=404, detail="QA row not found")
    if not (qa.improved_answer or "").strip():
        raise HTTPException(status_code=400, detail="该题暂无改进回答，无法保存到知识库")
    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == record_id, InterviewRecord.user_id == user_pk)
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")
    from app.services.knowledge.qa_publish_service import (
        DEFAULT_CATEGORY,
        save_qa_to_knowledge,
    )
    try:
        doc = await save_qa_to_knowledge(
            db, user_pk=user_pk, qa=qa, record=record,
            category=(body.category or "").strip() or DEFAULT_CATEGORY,
        )
    except Exception as exc:  # noqa: BLE001
        from app.core.error_messages import humanize_error
        raise HTTPException(
            status_code=500, detail=f"保存到知识库失败：{humanize_error(exc)}",
        ) from exc
    return {
        "status": "success",
        "document_id": doc.id,
        "saved_document_id": qa.saved_document_id,
    }


@router.delete("/interview-records/{record_id}/qa/{qa_id}/save-to-knowledge")
def unsave_qa_from_knowledge_endpoint(
    record_id: str,
    qa_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove the knowledge document previously saved from this QA."""
    user_pk = resolve_user_pk(db, current_user.username)
    qa = (
        db.query(InterviewQA)
        .join(InterviewRecord, InterviewQA.record_id == InterviewRecord.id)
        .filter(
            InterviewQA.id == qa_id,
            InterviewQA.record_id == record_id,
            InterviewRecord.user_id == user_pk,
        )
        .first()
    )
    if qa is None:
        raise HTTPException(status_code=404, detail="QA row not found")
    from app.services.knowledge.qa_publish_service import unsave_qa_from_knowledge
    removed = unsave_qa_from_knowledge(db, user_pk=user_pk, qa=qa)
    return {"status": "success", "removed": removed}


# ── Status → progress mapping for SSE (record.status is lower-case ENUM) ──
_PROGRESS_TICK_REFERENCE = 80  # ~120s expected wall-clock for upload pipeline
_TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_FAILED}


def _poll_record_snapshot(record_id: str) -> dict | None:
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
        return {
            "id": row.id,
            "status": (row.status or "").lower(),
            "analyzed_qa_count": row.analyzed_qa_count or 0,
            "analysis_json": row.analysis_json,
            "error_message": row.error_message,
        }


@router.get("/interview-records/{record_id}/events")
async def interview_record_events_stream(
    record_id: str,
    current_user: User = Depends(get_current_user),
):
    """SSE progress stream for the unified analysis pipeline.

    Polls InterviewRecord.status and analyzed_qa_count. Mock-source records
    skip the transcribing/extracting prefix and go straight to analyzing.

    Each poll opens its own short-lived DB session (via
    ``_poll_record_snapshot`` + ``asyncio.to_thread``) so 20+
    concurrent viewers don't pin the connection pool for 8 minutes
    apiece. The owner check at the top of the request does one
    short read; the long-running generator opens its own sessions
    so the request-scoped ``get_db`` isn't held for the lifetime
    of the stream.
    """
    def _initial_check_sync() -> bool:
        with SessionLocal() as db:
            return (
                db.query(InterviewRecord.id)
                .filter(
                    InterviewRecord.id == record_id,
                    InterviewRecord.user_id == resolve_user_pk(db, current_user.username),
                )
                .first()
                is not None
            )

    if not await asyncio.to_thread(_initial_check_sync):
        raise HTTPException(status_code=404, detail="Interview record not found")

    POLL_INTERVAL = 1.5
    MAX_TICKS = 320

    async def event_generator():
        try:
            for tick in range(MAX_TICKS):
                snap = await asyncio.to_thread(_poll_record_snapshot, record_id)
                if snap is None:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'record disappeared'})}\n\n"
                    return
                status = snap["status"]
                percent = min(95, int(tick * 100 / _PROGRESS_TICK_REFERENCE))
                yield "data: " + json.dumps(
                    {
                        "type": "progress",
                        "status": status,
                        "percent": percent,
                        "analyzed_qa_count": snap["analyzed_qa_count"],
                    },
                    ensure_ascii=False,
                ) + "\n\n"

                if status == STATUS_COMPLETED:
                    overall = {}
                    if snap["analysis_json"]:
                        try:
                            overall = (json.loads(snap["analysis_json"]) or {}).get("overall", {})
                        except json.JSONDecodeError:
                            overall = {}
                    yield "data: " + json.dumps(
                        {
                            "type": "done",
                            "record_id": snap["id"],
                            "status": status,
                            "percent": 100,
                            "analysis": {
                                "score": overall.get("score"),
                                "summary": overall.get("summary") or overall.get("feedback") or "",
                            },
                        },
                        ensure_ascii=False,
                    ) + "\n\n"
                    return
                if status == STATUS_FAILED:
                    yield "data: " + json.dumps(
                        {
                            "type": "error",
                            "status": status,
                            "message": snap["error_message"] or "分析失败",
                        },
                        ensure_ascii=False,
                    ) + "\n\n"
                    return
                await asyncio.sleep(POLL_INTERVAL)
            yield f"data: {json.dumps({'type': 'error', 'message': 'timeout'})}\n\n"
        except asyncio.CancelledError:
            # Client disconnect — every SessionLocal() opened inside
            # the loop was already ``with``-closed on its iteration,
            # so there's nothing to release here.
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

