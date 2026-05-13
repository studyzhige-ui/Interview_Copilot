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
from app.models.interview import Interview
from app.models.user import User
from app.services.diagnostics_report_service import generate_comprehensive_report
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
    try:
        # Validate audio upload
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

        # Validate resume upload
        resume_upload = get_owned_upload(
            db,
            upload_id=request.resume_upload_id,
            user_id=current_user.username,
            purpose="interview_resume",
        )
        if resume_upload is None:
            raise HTTPException(status_code=404, detail="Resume upload not found")

        # Resolve JD text — prefer explicit jd_text, otherwise load from KnowledgeDocument.
        jd_text = request.jd_text or None
        if not jd_text and request.jd_upload_id:
            from app.services.knowledge_text_service import load_knowledge_text
            loaded = load_knowledge_text(db, request.jd_upload_id, current_user.username)
            jd_text = loaded or None

        interview = Interview(
            user_id=current_user.username,
            status="PENDING",
            upload_id=upload.id,
            resume_upload_id=resume_upload.id,
            jd_text=jd_text,
            file_url=upload.storage_uri,
        )
        db.add(interview)
        mark_upload_consumed(db, upload)
        db.commit()
        db.refresh(interview)

        task = process_interview_analysis.delay(interview.id)
        interview.task_id = task.id
        db.commit()
        return {
            "status": "processing",
            "message": "Task dispatched to background workers successfully.",
            "interview_id": interview.id,
            "task_id": task.id,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/analyze/{interview_id}/status")
async def check_analysis_status(
    interview_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview or interview.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Interview not found")

    payload = {
        "interview_id": interview.id,
        "status": interview.status,
    }
    if interview.status == "COMPLETED" and interview.analysis:
        payload["analysis"] = {
            "score": interview.analysis.score,
            "feedback": interview.analysis.feedback,
            "per_question": json.loads(interview.analysis.improved_answer),
        }
    return payload


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
    from app.services.interview_record_service import interview_record_service

    record = interview_record_service.get(record_id, current_user.username)
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")
    analysis = None
    if record.analysis_json:
        try:
            analysis = json.loads(record.analysis_json)
        except json.JSONDecodeError:
            analysis = None
    return {
        "id": record.id,
        "source": record.source,
        "title": record.title,
        "tag": record.tag,
        "status": record.status,
        "audio_upload_id": record.audio_upload_id,
        "resume_upload_id": record.resume_upload_id,
        "jd_upload_id": record.jd_upload_id,
        "transcript": record.transcript,
        "analysis": analysis,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
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
    cascade_chats: bool = Query(False, description="If true, also delete linked debrief chat sessions"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an interview record.

    By default chat sessions tied to this record are detached (interview_id
    set to NULL), preserving their history. Pass `cascade_chats=true` to
    delete them too.
    """
    import logging

    log = logging.getLogger(__name__)
    from app.models.chat import ChatMessage, ChatSession
    from app.models.interview_record import InterviewRecord

    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == record_id, InterviewRecord.user_id == current_user.username)
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")

    try:
        if cascade_chats:
            # Find tied sessions, then cascade-delete their messages first
            # because ChatMessage has no ON DELETE CASCADE on its FK.
            session_ids = [
                row[0]
                for row in db.query(ChatSession.id)
                .filter(ChatSession.interview_id == record_id)
                .all()
            ]
            if session_ids:
                db.query(ChatMessage).filter(
                    ChatMessage.session_id.in_(session_ids)
                ).delete(synchronize_session=False)
                db.query(ChatSession).filter(
                    ChatSession.id.in_(session_ids)
                ).delete(synchronize_session=False)
        else:
            # Detach: clear FK on linked chat sessions before deleting the record.
            db.query(ChatSession).filter(
                ChatSession.interview_id == record_id
            ).update(
                {ChatSession.interview_id: None}, synchronize_session=False
            )
            db.flush()

        db.delete(record)
        db.commit()
        return {"status": "success", "id": record_id, "cascade_chats": cascade_chats}
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


class QAEditRequest(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    suggestion: Optional[str] = None


@router.patch("/interview-records/{record_id}/qa/{qa_index}")
def edit_interview_qa(
    record_id: str,
    qa_index: int,
    payload: QAEditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a single Q/A entry inside the record's analysis_json.

    The analysis JSON is expected to contain a ``per_question`` array. Falls
    back to ``qa_history`` if present (mock-interview shape).
    """
    from app.models.interview_record import InterviewRecord

    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == record_id, InterviewRecord.user_id == current_user.username)
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")
    if not record.analysis_json:
        raise HTTPException(status_code=400, detail="该记录尚无结构化 QA")

    try:
        analysis = json.loads(record.analysis_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="analysis_json 解析失败") from exc

    key = "per_question" if isinstance(analysis.get("per_question"), list) else (
        "qa_history" if isinstance(analysis.get("qa_history"), list) else None
    )
    if key is None:
        raise HTTPException(status_code=400, detail="该记录格式不含 per_question / qa_history 数组")

    arr = analysis[key]
    if qa_index < 0 or qa_index >= len(arr):
        raise HTTPException(status_code=400, detail="qa_index 越界")

    item = dict(arr[qa_index]) if isinstance(arr[qa_index], dict) else {}
    if payload.question is not None:
        item["question"] = payload.question
    if payload.answer is not None:
        item["answer"] = payload.answer
    if payload.suggestion is not None:
        item["suggestion"] = payload.suggestion
    arr[qa_index] = item
    analysis[key] = arr

    record.analysis_json = json.dumps(analysis, ensure_ascii=False)
    record.updated_at = datetime.utcnow()
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"status": "success", "qa": item}


@router.get("/analyze/{interview_id}/events")
async def analyze_events_stream(
    interview_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE progress stream for an interview analysis task.

    Emits ``progress`` events on each poll and a single terminal ``done``
    event once the worker marks the row COMPLETED (or ``error`` on failure).

    Internally still backed by the existing Interview.status column updated by
    Celery; we just translate the poll loop into a push stream so the client
    can drop its own setInterval.
    """
    # Authorize once up front
    initial = db.query(Interview).filter(Interview.id == interview_id).first()
    if not initial or initial.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Whisper + 3-stage analysis on a multi-minute clip can take 2-4 minutes.
    # Budget = MAX_TICKS * POLL_INTERVAL. Whole-pipeline expected ~120s, so we
    # cap at 8 minutes to leave generous headroom.
    POLL_INTERVAL = 1.5  # seconds
    MAX_TICKS = 320
    PERCENT_REFERENCE_TICKS = 80  # ~120s wall-clock for the "expected" full run

    async def event_generator():
        try:
            for tick in range(MAX_TICKS):
                # CRITICAL: drop the identity-map cache so we observe the
                # COMPLETED transition written by the Celery worker. Without
                # this, the API session returns the stale row forever.
                db.expire_all()
                row = (
                    db.query(Interview).filter(Interview.id == interview_id).first()
                )
                if row is None:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'record disappeared'})}\n\n"
                    return
                status = (row.status or "").upper()
                percent = min(95, int(tick * 100 / PERCENT_REFERENCE_TICKS))
                payload: dict = {
                    "type": "progress",
                    "status": status,
                    "percent": percent,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if status == "COMPLETED":
                    done: dict = {
                        "type": "done",
                        "interview_id": row.id,
                        "status": status,
                        "percent": 100,
                    }
                    if row.analysis:
                        done["analysis"] = {
                            "score": row.analysis.score,
                            "feedback": row.analysis.feedback,
                        }
                    yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
                    return
                if status in {"FAILED", "ERROR"}:
                    yield f"data: {json.dumps({'type': 'error', 'status': status})}\n\n"
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

