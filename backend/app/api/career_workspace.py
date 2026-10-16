"""Authenticated workspace commands; ownership and transactions stay server-side."""

from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.orm import Session
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.career.application import workspace, documents, artifacts
from app.career.application.process import CareerProcessError
from app.api.career_process import _run_domain
from app.api.artifacts import _raise_artifact_http
from app.schemas.career_workspace import (
    JobCreate,
    JobEdit,
    StageChange,
    DocumentCreate,
    DraftSave,
    DocumentPublish,
    Stage,
)

router = APIRouter(prefix="/career-workspace", tags=["career-workspace"])


@router.post("/import")
def import_jobs(
    body: list[JobCreate] = Body(max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: [workspace.create_job(db, user.id, item) for item in body],
        commit=True,
    )


@router.post("/jobs", status_code=201)
def create_job(
    body: JobCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(db, lambda: workspace.create_job(db, user.id, body), commit=True)


@router.get("/jobs")
def list_jobs(
    q: str = Query("", max_length=300),
    stage: Stage | None = None,
    closed: bool = False,
    hidden: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return workspace.list_jobs(db, user.id, q, stage, closed, hidden, offset, limit)


@router.get("/jobs/{job_id}")
def job_detail(
    job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return _run_domain(db, lambda: workspace.detail(db, user.id, job_id))


@router.patch("/jobs/{job_id}")
def edit_job(
    job_id: str,
    body: JobEdit,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db, lambda: workspace.edit_job(db, user.id, job_id, body), commit=True
    )


@router.post("/jobs/{job_id}/stage")
def change_stage(
    job_id: str,
    body: StageChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: _document_command(
            db, lambda: workspace.change_stage(db, user.id, job_id, body)
        ),
        commit=True,
    )


def _document_command(db, operation, commit=False):
    try:
        result = operation()
        if commit:
            db.commit()
        return result
    except artifacts.ArtifactDomainError as exc:
        db.rollback()
        _raise_artifact_http(exc)
    except CareerProcessError:
        db.rollback()
        raise


@router.post("/documents", status_code=201)
def create_document(
    body: DocumentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: _document_command(
            db, lambda: documents.create_document(db, user.id, body), True
        ),
    )


@router.get("/documents/{artifact_id}/draft")
def get_draft(
    artifact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _document_command(db, lambda: documents.get_draft(db, user.id, artifact_id))


@router.put("/documents/{artifact_id}/draft")
def save_draft(
    artifact_id: str,
    body: DraftSave,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _document_command(
        db, lambda: documents.save_draft(db, user.id, artifact_id, body), True
    )


@router.post("/documents/{artifact_id}/publish")
def publish(
    artifact_id: str,
    body: DocumentPublish,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _document_command(
        db, lambda: documents.publish(db, user.id, artifact_id, body), True
    )
