"""Business rules for the first-class ``resumes`` entity.

Product constraints (RFC §6.10):
  * at most TWO active resumes per user;
  * while any active resume exists, exactly ONE is the default;
  * deleting the default auto-promotes the other active resume;
  * a third upload must replace one of the two.

``user_id`` is the caller's username, resolved once to the stable ``users.id``
(``resolve_user_pk``). The "at most one default" invariant is also backstopped
by a partial unique index on the table.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.models.resume import Resume

MAX_ACTIVE_RESUMES = 2


class ResumeLimitError(ValueError):
    """Raised when a create would exceed the two-active-resumes limit."""


def _active_resumes(db: Session, user_pk: int) -> list[Resume]:
    return (
        db.query(Resume)
        .filter(Resume.user_id == user_pk, Resume.archived_at.is_(None))
        .order_by(Resume.created_at.asc())
        .all()
    )


def list_resumes(db: Session, *, user_id: str) -> list[Resume]:
    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        return []
    return _active_resumes(db, user_pk)


def get_owned_resume(db: Session, *, resume_id: str, user_id: str) -> Resume | None:
    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        return None
    return (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == user_pk)
        .first()
    )


def create_resume(
    db: Session,
    *,
    user_id: str,
    file_asset_id: str | None = None,
    title: str | None = None,
    raw_text_snapshot: str | None = None,
    structured_json: str | None = None,
    make_default: bool | None = None,
) -> Resume:
    """Create a resume, enforcing the two-active limit + default rule.

    0 active -> becomes default; 1 active -> added as non-default (keep the
    existing default) unless ``make_default``; 2 active -> ``ResumeLimitError``
    (the caller must replace one via :func:`replace_resume`).
    """
    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        raise ValueError(f"Unknown user: {user_id}")

    active = _active_resumes(db, user_pk)
    if len(active) >= MAX_ACTIVE_RESUMES:
        raise ResumeLimitError(
            "已有两份简历，请替换其中一份",
        )

    should_default = len(active) == 0 or bool(make_default)
    if should_default:
        for r in active:
            r.is_default = False
        db.flush()

    resume = Resume(
        user_id=user_pk,
        file_asset_id=file_asset_id,
        title=title or "我的简历",
        is_default=should_default,
        raw_text_snapshot=raw_text_snapshot,
        structured_json=structured_json,
        parse_status="ready" if raw_text_snapshot else "pending",
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


def replace_resume(
    db: Session,
    *,
    user_id: str,
    replaced_resume_id: str,
    file_asset_id: str | None = None,
    title: str | None = None,
    raw_text_snapshot: str | None = None,
    structured_json: str | None = None,
) -> Resume:
    """Archive ``replaced_resume_id`` and create a new resume in its place.

    The new resume inherits default-ness from the one it replaces, so the
    user's default doesn't silently move.
    """
    old = get_owned_resume(db, resume_id=replaced_resume_id, user_id=user_id)
    if old is None or old.archived_at is not None:
        raise ValueError("要替换的简历不存在")
    inherit_default = bool(old.is_default)
    old.is_default = False
    old.archived_at = datetime.utcnow()
    db.add(old)
    db.flush()
    return create_resume(
        db,
        user_id=user_id,
        file_asset_id=file_asset_id,
        title=title,
        raw_text_snapshot=raw_text_snapshot,
        structured_json=structured_json,
        make_default=inherit_default,
    )


def set_default_resume(db: Session, *, user_id: str, resume_id: str) -> Resume | None:
    resume = get_owned_resume(db, resume_id=resume_id, user_id=user_id)
    if resume is None or resume.archived_at is not None:
        return None
    # Clear all defaults first (flush), THEN set the target — never two
    # defaults transiently, which the partial unique index would reject.
    for r in _active_resumes(db, resume.user_id):
        r.is_default = False
    db.flush()
    resume.is_default = True
    db.commit()
    db.refresh(resume)
    return resume


def delete_resume(db: Session, *, user_id: str, resume_id: str) -> bool:
    """Soft-delete (archive). If it was the default, auto-promote the other
    active resume so an active set always has exactly one default."""
    resume = get_owned_resume(db, resume_id=resume_id, user_id=user_id)
    if resume is None or resume.archived_at is not None:
        return False
    was_default = resume.is_default
    resume.is_default = False
    resume.archived_at = datetime.utcnow()
    db.add(resume)
    db.flush()
    if was_default:
        remaining = _active_resumes(db, resume.user_id)
        if remaining:
            remaining[0].is_default = True
    db.commit()
    return True
