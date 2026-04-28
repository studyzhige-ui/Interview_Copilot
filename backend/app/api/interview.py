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
from app.services.analytics_service import generate_comprehensive_report
from app.services.storage_service import generate_presigned_upload_url, upload_file_to_s3
from app.worker.tasks import process_interview_analysis

try:
    from app.rag.ingestion import ingest_text
except ModuleNotFoundError:
    ingest_text = None


router = APIRouter()


class PresignedUrlRequest(BaseModel):
    filename: str


class AnalyzeRequest(BaseModel):
    file_path: str


class MemorySaveRequest(BaseModel):
    question: str
    improved_answer: str
    original_score: float
    tags: Optional[List[str]] = Field(default_factory=list)


@router.post("/upload/audio/direct")
async def upload_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    file_path = upload_file_to_s3(file.file, file.filename)
    return {"status": "success", "file_path": file_path}


@router.post("/upload/audio")
async def get_upload_presigned_url(
    request: PresignedUrlRequest,
    current_user: User = Depends(get_current_user),
):
    url_info = generate_presigned_upload_url(request.filename)
    return {
        "status": "success",
        "upload_url": url_info["upload_url"],
        "file_path": url_info["file_path"],
    }


@router.post("/analyze")
async def analyze_interview_endpoint(
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        interview = Interview(
            user_id=current_user.username,
            status="PENDING",
            file_url=request.file_path,
        )
        db.add(interview)
        db.commit()
        db.refresh(interview)

        task = process_interview_analysis.delay(interview.id, request.file_path)
        interview.task_id = task.id
        db.commit()
        return {
            "status": "processing",
            "message": "Task dispatched to background workers successfully.",
            "interview_id": interview.id,
            "task_id": task.id,
        }
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
            "improved_answer": json.loads(interview.analysis.improved_answer),
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
