"""Compatibility routes for canonical ``Artifact(kind=resume)`` aggregates.

The URL remains stable for existing clients, but every production command now
writes the Artifact aggregate. The retired ``resumes`` table is never mutated.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_DEFAULT, limiter
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.resumes import ResumeCreateRequest, ResumeResponse
from app.services.resume import resume_artifact_service
from app.services.resume.resume_dispatch_service import dispatch_parse_after_commit

router = APIRouter()


def _dispatch_resume_parse(db: Session, record) -> None:
    """Stable local alias retained for route-level call sites."""
    dispatch_parse_after_commit(db, record)


def _serialize(record) -> ResumeResponse:
    artifact = record.artifact
    version = record.current_version
    state = record.state
    return ResumeResponse(
        id=artifact.id,
        artifact_id=artifact.id,
        current_version_id=version.id,
        title=version.title,
        is_default=bool(state.is_default),
        parse_status=state.parse_status,
        parse_error=state.parse_error,
        file_asset_id=version.file_asset_id,
        has_text=bool(version.content_text),
        pending_profile_draft_id=record.pending_draft_id,
        legacy_resume_id=state.legacy_resume_id,
        created_at=artifact.created_at.isoformat() if artifact.created_at else "",
        updated_at=artifact.updated_at.isoformat() if artifact.updated_at else "",
    )


@router.get("/resumes", response_model=list[ResumeResponse])
def list_resumes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [
        _serialize(r)
        for r in resume_artifact_service.list_resume_artifacts(
            db, user_pk=current_user.id
        )
    ]


@router.post("/resumes", response_model=ResumeResponse)
@limiter.limit(RATE_DEFAULT)
def create_resume(
    request: Request,
    response: Response,
    body: ResumeCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        resume = resume_artifact_service.create_resume_artifact(
            db,
            user_pk=current_user.id,
            operation_key=body.operation_key
            or resume_artifact_service.new_operation_key("resume_import"),
            file_asset_id=body.file_asset_id,
            title=body.title or "我的简历",
            raw_text=body.raw_text_snapshot,
            make_default=body.make_default,
        )
        db.commit()
    except resume_artifact_service.ResumeArtifactLimitError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except resume_artifact_service.ResumeArtifactError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    _dispatch_resume_parse(db, resume)
    return _serialize(resume)


@router.post("/resumes/{resume_id}/parse", response_model=ResumeResponse)
@limiter.limit(RATE_DEFAULT)
def retry_resume_parse(
    request: Request,
    response: Response,
    resume_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly retry extraction for the exact current ArtifactVersion."""

    try:
        current = resume_artifact_service.resolve_owned_resume(
            db,
            user_pk=current_user.id,
            resume_id=resume_id,
        )
        resume = resume_artifact_service.mark_parse_state(
            db,
            user_pk=current_user.id,
            resume_id=resume_id,
            status="pending",
            source_version_id=current.current_version.id,
        )
        db.commit()
    except resume_artifact_service.ResumeArtifactNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except resume_artifact_service.ResumeArtifactError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _dispatch_resume_parse(db, resume)
    return _serialize(
        resume_artifact_service.resolve_owned_resume(
            db,
            user_pk=current_user.id,
            resume_id=resume_id,
        )
    )


@router.post("/resumes/{resume_id}/replace", response_model=ResumeResponse)
@limiter.limit(RATE_DEFAULT)
def replace_resume(
    request: Request,
    response: Response,
    resume_id: str,
    body: ResumeCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        resume = resume_artifact_service.add_resume_version(
            db,
            user_pk=current_user.id,
            resume_id=resume_id,
            operation_key=body.operation_key
            or resume_artifact_service.new_operation_key("resume_version"),
            file_asset_id=body.file_asset_id,
            title=body.title or "我的简历",
            raw_text=body.raw_text_snapshot,
        )
        db.commit()
    except resume_artifact_service.ResumeArtifactNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except resume_artifact_service.ResumeArtifactError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    _dispatch_resume_parse(db, resume)
    return _serialize(resume)


@router.post("/resumes/{resume_id}/set-default", response_model=ResumeResponse)
@limiter.limit(RATE_DEFAULT)
def set_default(
    request: Request,
    response: Response,
    resume_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        resume = resume_artifact_service.set_default_resume_artifact(
            db, user_pk=current_user.id, resume_id=resume_id
        )
        db.commit()
    except resume_artifact_service.ResumeArtifactNotFoundError:
        db.rollback()
        raise HTTPException(status_code=404, detail="简历不存在")
    return _serialize(resume)


@router.delete("/resumes/{resume_id}", response_model=dict)
@limiter.limit(RATE_DEFAULT)
def delete_resume(
    request: Request,
    response: Response,
    resume_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        resume_artifact_service.archive_resume_artifact(
            db, user_pk=current_user.id, resume_id=resume_id
        )
        db.commit()
    except resume_artifact_service.ResumeArtifactNotFoundError:
        db.rollback()
        raise HTTPException(status_code=404, detail="简历不存在")
    return {"status": "deleted"}
