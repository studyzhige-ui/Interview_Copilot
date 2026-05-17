import asyncio
import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.models.user import User
from app.services.diagnostics_report_service import generate_comprehensive_report
from app.services.interview_record_service import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    interview_record_service,
)
from app.services.storage_service import upload_file_to_owned_key
from app.services.upload_service import create_owned_upload, get_owned_upload, mark_upload_consumed
from app.worker.tasks import process_interview_analysis

try:
    from app.rag.ingestion import ingest_text
except ModuleNotFoundError:
    ingest_text = None


router = APIRouter()


class PresignedUrlRequest(BaseModel):
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None


class AnalyzeRequest(BaseModel):
    upload_id: str
    resume_upload_id: str
    jd_text: Optional[str] = None
    jd_upload_id: Optional[str] = None  # KnowledgeDocument id; if set, text is loaded server-side
    # ISO-639-1 language hint for WhisperX. ``"zh"`` / ``"en"`` force the
    # decoder, ``"auto"`` lets Whisper detect per-clip (slower, occasionally
    # picks the wrong one — only worth it for genuinely mixed audio).
    # Default matches the UI default of Simplified Chinese transcription.
    language: str = "zh"


class MemorySaveRequest(BaseModel):
    question: str
    improved_answer: str
    original_score: float
    tags: Optional[List[str]] = Field(default_factory=list)


@router.post("/upload/audio/direct")
async def upload_audio(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.voice.file_parser import validate_media_format

    if not validate_media_format(file.filename or ""):
        raise HTTPException(
            status_code=400,
            detail="不支持的音视频格式。支持: mp3, wav, m4a, flac, ogg, wma, aac, mp4, mkv, avi, mov, webm",
        )

    upload, _ = create_owned_upload(
        db,
        user_id=current_user.username,
        filename=file.filename,
        purpose="interview_audio",
        content_type=file.content_type,
    )
    storage_uri = upload_file_to_owned_key(file.file, upload.object_key, file.content_type)
    upload.storage_uri = storage_uri
    upload.status = "uploaded"
    db.add(upload)
    db.commit()
    return {
        "status": "success",
        "upload_id": upload.id,
        "storage_uri": upload.storage_uri,
        "filename": upload.original_filename,
    }


@router.get("/uploads/resumes")
def list_user_resumes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the user's library resumes (KnowledgeDocument with category='简历').

    Source-of-truth for "stored resumes" is the personal library, not previous
    mock-interview uploads. Returns each library doc together with the
    underlying UserUpload.id so MockSetup can pass it to /mock-interview/start
    as ``resume_upload_id`` without extra translation.
    """
    from app.models.knowledge import KnowledgeDocument
    from app.models.upload import UserUpload

    rows = (
        db.query(KnowledgeDocument, UserUpload)
        .join(UserUpload, KnowledgeDocument.upload_id == UserUpload.id)
        .filter(
            KnowledgeDocument.user_id == current_user.username,
            KnowledgeDocument.category == "简历",
        )
        .order_by(KnowledgeDocument.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "resumes": [
            {
                "upload_id": u.id,
                "filename": d.title or u.original_filename,
                "size_bytes": u.size_bytes,
                "created_at": d.created_at.isoformat() if d.created_at else "",
                "doc_id": d.id,
            }
            for (d, u) in rows
        ],
    }


@router.post("/upload/resume/direct")
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a resume file for interview analysis context."""
    from app.services.voice.file_parser import validate_resume_format

    if not validate_resume_format(file.filename or ""):
        raise HTTPException(
            status_code=400,
            detail="不支持的简历格式。支持: pdf, docx, txt, md",
        )

    upload, _ = create_owned_upload(
        db,
        user_id=current_user.username,
        filename=file.filename,
        purpose="interview_resume",
        content_type=file.content_type,
    )
    storage_uri = upload_file_to_owned_key(file.file, upload.object_key, file.content_type)
    upload.storage_uri = storage_uri
    upload.status = "uploaded"
    db.add(upload)
    db.commit()
    return {
        "status": "success",
        "upload_id": upload.id,
        "storage_uri": upload.storage_uri,
        "filename": upload.original_filename,
    }


@router.post("/upload/audio")
async def get_upload_presigned_url(
    request: PresignedUrlRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.voice.file_parser import validate_media_format

    if not validate_media_format(request.filename):
        raise HTTPException(
            status_code=400,
            detail="不支持的音视频格式。支持: mp3, wav, m4a, flac, ogg, wma, aac, mp4, mkv, avi, mov, webm",
        )

    upload, url_info = create_owned_upload(
        db=db,
        user_id=current_user.username,
        filename=request.filename,
        purpose="interview_audio",
        content_type=request.content_type,
        size_bytes=request.size_bytes,
    )
    return {
        "status": "success",
        "upload_id": upload.id,
        "upload_url": url_info["upload_url"],
        "storage_uri": upload.storage_uri,
        "filename": upload.original_filename,
    }


@router.post("/analyze")
async def analyze_interview_endpoint(
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an InterviewRecord from an uploaded audio file and dispatch the
    unified analysis orchestrator."""
    try:
        upload = get_owned_upload(
            db,
            upload_id=request.upload_id,
            user_id=current_user.username,
            purpose="interview_audio",
        )
        if upload is None:
            raise HTTPException(status_code=404, detail="Audio upload not found")
        if upload.status not in {"pending_upload", "uploaded"}:
            raise HTTPException(status_code=409, detail="Audio upload has already been consumed")

        resume_upload = get_owned_upload(
            db,
            upload_id=request.resume_upload_id,
            user_id=current_user.username,
            purpose="interview_resume",
        )
        if resume_upload is None:
            raise HTTPException(status_code=404, detail="Resume upload not found")

        jd_text = (request.jd_text or "").strip()
        if not jd_text and request.jd_upload_id:
            from app.services.knowledge_text_service import load_knowledge_text
            try:
                jd_text = load_knowledge_text(db, request.jd_upload_id, current_user.username) or ""
            except Exception:  # noqa: BLE001
                jd_text = ""

        # Extract resume text for the snapshot. Failures are non-fatal —
        # orchestrator falls back to empty context.
        resume_text = ""
        try:
            resume_text = _extract_resume_snapshot(db, resume_upload.id, current_user.username)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("Resume snapshot extraction failed: %s", exc)

        record = interview_record_service.create_for_upload(
            user_id=current_user.username,
            title=f"面试录音 {upload.original_filename or upload.id}",
            audio_upload_id=upload.id,
            resume_upload_id=resume_upload.id,
            resume_text_snapshot=resume_text,
            jd_text_snapshot=jd_text,
            db=db,
        )
        mark_upload_consumed(db, upload)
        db.commit()

        # Normalize language hint: anything other than the two we explicitly
        # support falls back to "zh". WhisperX accepts "auto" by passing
        # ``None``, which the orchestrator translates.
        language = (request.language or "zh").strip().lower()
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
        .filter(InterviewRecord.id == record_id, InterviewRecord.user_id == current_user.username)
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


def _extract_resume_snapshot(db: Session, resume_upload_id: str, user_id: str) -> str:
    """Download the resume file and return its plain text (truncated)."""
    import os
    import tempfile

    from app.models.upload import UserUpload
    from app.services.storage_service import download_file_from_s3
    from app.services.voice.file_parser import extract_resume_text

    upload = (
        db.query(UserUpload)
        .filter(UserUpload.id == resume_upload_id, UserUpload.user_id == user_id)
        .first()
    )
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
async def save_personal_memory(
    request: MemorySaveRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        ingest_fn = ingest_text
        if ingest_fn is None:
            from app.rag.ingestion import ingest_text as ingest_fn

        combined_text = (
            f"[Question]\n{request.question}\n\n"
            f"[Improved Answer]\n{request.improved_answer}"
        )
        metadata = {
            "source_type": "personal_memory",
            "original_score": request.original_score,
            "last_accessed": datetime.now().isoformat(),
        }
        if request.tags:
            metadata["tags"] = ", ".join(request.tags)

        await ingest_fn(
            text=combined_text,
            source_type="personal_memory",
            user_id=current_user.username,
            metadata=metadata,
        )
        return {
            "status": "success",
            "message": f"Saved personal memory with baseline score {request.original_score}.",
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

class InterviewRecordListItem(BaseModel):
    id: str
    source: str
    title: str
    tag: Optional[str] = None
    status: str
    created_at: str


@router.get("/interview-records", response_model=List[InterviewRecordListItem])
def list_interview_records(
    current_user: User = Depends(get_current_user),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    from app.services.interview_record_service import interview_record_service

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
    return {
        "id": record.id,
        "source": record.source,
        "title": record.title,
        "tag": record.tag,
        "status": record.status,
        "analyzed_qa_count": record.analyzed_qa_count,
        "audio_upload_id": record.audio_upload_id,
        "resume_upload_id": record.resume_upload_id,
        "jd_upload_id": record.jd_upload_id,
        "transcript": record.transcript,
        "transcript_segments": _safe_json_loads(record.transcript_segments_json),
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
    }


@router.get("/interview-records/{record_id}/summary")
def get_interview_record_summary(
    record_id: str,
    current_user: User = Depends(get_current_user),
):
    """Short analysis summary for context injection (slot 2)."""
    from app.services.interview_record_service import interview_record_service

    summary = interview_record_service.get_analysis_summary(record_id, current_user.username)
    if not summary:
        raise HTTPException(status_code=404, detail="Interview record or analysis not found")
    return {"summary": summary}


class InterviewRecordUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    tag: Optional[str] = Field(default=None, max_length=32)


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
        .filter(InterviewRecord.id == record_id, InterviewRecord.user_id == current_user.username)
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard-delete an interview record AND every trace tied to it.

    Removes, in order:

      1. **memory_items** derived from any chat_session linked to this
         interview (``source_session_id`` ∈ linked sessions). These are
         the ``type=interview_fact`` rows the system extracted from
         debrief chats — they would otherwise contaminate future
         recall.
      2. **Milvus vectors** for those memory_items (``interview_copilot_memory``
         collection, keyed by ``doc_id``). Best-effort: a Milvus failure
         logs a warning but doesn't block the DB delete.
      3. **chat_messages** for every session linked to this interview
         (the FK has no ON DELETE CASCADE, so we have to be explicit).
      4. **chat_sessions** linked to this interview (``interview_id == X``).
      5. **interview_qa** + **mock_interview_sessions** (auto via FK
         ON DELETE CASCADE on ``interview_records``).
      6. The **interview_record** row itself.

    Designed for "I want this interview gone — no leftover chat history,
    no memory that could spill into other sessions." The legacy detach
    mode (set ``interview_id = NULL``, keep the chat) was removed: in
    practice nobody used it and it produced confusing orphan sessions.
    """
    import logging

    log = logging.getLogger(__name__)
    from app.models.chat import ChatMessage, ChatSession
    from app.models.interview_record import InterviewRecord
    from app.models.memory import MemoryItem

    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == record_id, InterviewRecord.user_id == current_user.username)
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")

    try:
        # ── (1) Find every chat_session linked to this interview ──────────
        session_ids = [
            row[0]
            for row in db.query(ChatSession.id)
            .filter(ChatSession.interview_id == record_id)
            .all()
        ]

        # ── (2) memory_items derived from those sessions ─────────────────
        memory_doc_ids: list[str] = []
        if session_ids:
            memory_doc_ids = [
                row[0]
                for row in db.query(MemoryItem.id)
                .filter(MemoryItem.source_session_id.in_(session_ids))
                .all()
            ]

        # ── (3) Milvus best-effort delete of memory vectors ──────────────
        if memory_doc_ids:
            try:
                _delete_milvus_doc_ids(
                    settings.MEMORY_MILVUS_COLLECTION, memory_doc_ids,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Milvus delete failed for %d memory rows (continuing with DB delete): %s",
                    len(memory_doc_ids), exc,
                )

        # ── (4) DB deletes in safe order ─────────────────────────────────
        if memory_doc_ids:
            db.query(MemoryItem).filter(
                MemoryItem.id.in_(memory_doc_ids)
            ).delete(synchronize_session=False)
        if session_ids:
            db.query(ChatMessage).filter(
                ChatMessage.session_id.in_(session_ids)
            ).delete(synchronize_session=False)
            db.query(ChatSession).filter(
                ChatSession.id.in_(session_ids)
            ).delete(synchronize_session=False)
        # interview_qa + mock_interview_sessions auto-cleaned by their
        # ON DELETE CASCADE on interview_records.
        db.delete(record)
        db.commit()
        log.info(
            "Deleted interview_record=%s with %d session(s) and %d memory(ies)",
            record_id, len(session_ids), len(memory_doc_ids),
        )
        return {
            "status": "success",
            "id": record_id,
            "deleted_sessions": len(session_ids),
            "deleted_memories": len(memory_doc_ids),
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


def _delete_milvus_doc_ids(collection: str, doc_ids: list[str]) -> int:
    """Delete every row in a Milvus collection whose ``doc_id`` is in ``doc_ids``.

    Chunks the expression at 100 ids per call so we stay under Milvus's
    expression length limit on large purges. Skips silently when the
    collection doesn't exist (e.g. fresh install, no memory yet).
    Returns the number of rows actually matched + deleted across chunks.
    """
    if not doc_ids:
        return 0
    from pymilvus import Collection, connections, utility

    milvus_uri = (settings.MILVUS_URI or "http://localhost:19530").replace("http://", "").replace("https://", "")
    host, _, port = milvus_uri.partition(":")
    connections.connect(host=host or "localhost", port=port or "19530")
    if not utility.has_collection(collection):
        return 0
    c = Collection(collection)
    c.load()
    deleted = 0
    for i in range(0, len(doc_ids), 100):
        chunk = doc_ids[i:i + 100]
        expr = "doc_id in [" + ", ".join(f'"{d}"' for d in chunk) + "]"
        c.delete(expr)
        deleted += len(chunk)
    c.flush()
    return deleted


class QAEditRequest(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    critique: Optional[str] = None
    improved_answer: Optional[str] = None


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
            InterviewRecord.user_id == current_user.username,
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


# ── Status → progress mapping for SSE (record.status is lower-case ENUM) ──
_PROGRESS_TICK_REFERENCE = 80  # ~120s expected wall-clock for upload pipeline
_TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_FAILED}


@router.get("/interview-records/{record_id}/events")
async def interview_record_events_stream(
    record_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE progress stream for the unified analysis pipeline.

    Polls InterviewRecord.status and analyzed_qa_count. Mock-source records
    skip the transcribing/extracting prefix and go straight to analyzing.
    """
    initial = (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.id == record_id,
            InterviewRecord.user_id == current_user.username,
        )
        .first()
    )
    if not initial:
        raise HTTPException(status_code=404, detail="Interview record not found")

    POLL_INTERVAL = 1.5
    MAX_TICKS = 320

    async def event_generator():
        try:
            for tick in range(MAX_TICKS):
                db.expire_all()
                row = (
                    db.query(InterviewRecord)
                    .filter(InterviewRecord.id == record_id)
                    .first()
                )
                if row is None:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'record disappeared'})}\n\n"
                    return
                status = (row.status or "").lower()
                percent = min(95, int(tick * 100 / _PROGRESS_TICK_REFERENCE))
                yield "data: " + json.dumps(
                    {
                        "type": "progress",
                        "status": status,
                        "percent": percent,
                        "analyzed_qa_count": row.analyzed_qa_count or 0,
                    },
                    ensure_ascii=False,
                ) + "\n\n"

                if status == STATUS_COMPLETED:
                    overall = {}
                    if row.analysis_json:
                        try:
                            overall = (json.loads(row.analysis_json) or {}).get("overall", {})
                        except json.JSONDecodeError:
                            overall = {}
                    yield "data: " + json.dumps(
                        {
                            "type": "done",
                            "record_id": row.id,
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
                            "message": row.error_message or "分析失败",
                        },
                        ensure_ascii=False,
                    ) + "\n\n"
                    return
                await asyncio.sleep(POLL_INTERVAL)
            yield f"data: {json.dumps({'type': 'error', 'message': 'timeout'})}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

