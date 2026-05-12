import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
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

        interview = Interview(
            user_id=current_user.username,
            status="PENDING",
            upload_id=upload.id,
            resume_upload_id=resume_upload.id,
            jd_text=request.jd_text or None,
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

