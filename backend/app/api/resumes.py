"""Personal resume API: the first-class ``resumes`` entity.

CRUD over the user's (at most two) personal resumes, enforcing the
default / max-two / auto-promote rules in the service layer. Resumes are a
personal-profile asset — they never enter the knowledge base.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_DEFAULT, limiter
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.resume import Resume
from app.models.user import User
from app.services.resume import resume_entity_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _dispatch_resume_parse(resume: Resume) -> None:
    """Best-effort: parse the resume into ``resume_sections`` + index them
    (RFC §6.5). The entity is already persisted; a dispatch failure just
    leaves ``parse_status`` for a later retry."""
    if not (resume.file_asset_id or (resume.raw_text_snapshot or "").strip()):
        return
    try:
        from app.worker.tasks import process_resume_parse

        process_resume_parse.delay(resume.id)
    except Exception:  # noqa: BLE001
        logger.warning("resume parse dispatch failed for %s", resume.id)


class ResumeCreateRequest(BaseModel):
    file_asset_id: str | None = None
    title: str | None = Field(default=None, max_length=200)
    raw_text_snapshot: str | None = None
    make_default: bool | None = None


class ResumeResponse(BaseModel):
    id: str
    title: str
    is_default: bool
    parse_status: str
    file_asset_id: str | None
    has_text: bool
    created_at: str
    updated_at: str


def _serialize(r: Resume) -> ResumeResponse:
    return ResumeResponse(
        id=r.id,
        title=r.title,
        is_default=bool(r.is_default),
        parse_status=r.parse_status,
        file_asset_id=r.file_asset_id,
        has_text=bool(r.raw_text_snapshot),
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


@router.get("/resumes", response_model=list[ResumeResponse])
def list_resumes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [_serialize(r) for r in resume_entity_service.list_resumes(db, user_id=current_user.username)]


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
        resume = resume_entity_service.create_resume(
            db,
            user_id=current_user.username,
            file_asset_id=body.file_asset_id,
            title=body.title,
            raw_text_snapshot=body.raw_text_snapshot,
            make_default=body.make_default,
        )
    except resume_entity_service.ResumeLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _dispatch_resume_parse(resume)
    return _serialize(resume)


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
        resume = resume_entity_service.replace_resume(
            db,
            user_id=current_user.username,
            replaced_resume_id=resume_id,
            file_asset_id=body.file_asset_id,
            title=body.title,
            raw_text_snapshot=body.raw_text_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    _dispatch_resume_parse(resume)
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
    resume = resume_entity_service.set_default_resume(
        db, user_id=current_user.username, resume_id=resume_id,
    )
    if resume is None:
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
    ok = resume_entity_service.delete_resume(
        db, user_id=current_user.username, resume_id=resume_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="简历不存在")
    return {"status": "deleted"}
