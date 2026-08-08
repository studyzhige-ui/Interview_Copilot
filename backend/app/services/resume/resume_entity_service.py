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

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.types import utc_now
from app.models.resume import Resume
from app.models.user import User

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


def _lock_user(db: Session, username: str) -> int:
    """Serialize mutations that maintain per-user resume invariants."""
    user_pk = (
        db.query(User.id).filter(User.username == username).with_for_update().scalar()
    )
    if user_pk is None:
        raise ValueError(f"Unknown user: {username}")
    return user_pk


def _create_resume_locked(
    db: Session,
    *,
    user_pk: int,
    file_asset_id: str | None,
    title: str | None,
    raw_text_snapshot: str | None,
    structured_json: str | None,
    make_default: bool | None,
) -> Resume:
    active = _active_resumes(db, user_pk)
    if len(active) >= MAX_ACTIVE_RESUMES:
        raise ResumeLimitError("已有两份简历，请替换其中一份")

    should_default = len(active) == 0 or bool(make_default)
    if should_default:
        for resume in active:
            resume.is_default = False
        db.flush()

    resume = Resume(
        user_id=user_pk,
        file_asset_id=file_asset_id,
        title=title or "我的简历",
        is_default=should_default,
        raw_text_snapshot=raw_text_snapshot,
        structured_json=structured_json,
        parse_status="pending",
    )
    db.add(resume)
    db.flush()
    return resume


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
        .filter(
            Resume.id == resume_id,
            Resume.user_id == user_pk,
            Resume.archived_at.is_(None),
        )
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
    user_pk = _lock_user(db, user_id)
    resume = _create_resume_locked(
        db,
        user_pk=user_pk,
        file_asset_id=file_asset_id,
        title=title,
        raw_text_snapshot=raw_text_snapshot,
        structured_json=structured_json,
        make_default=make_default,
    )
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
    user_pk = _lock_user(db, user_id)
    old = (
        db.query(Resume)
        .filter(
            Resume.id == replaced_resume_id,
            Resume.user_id == user_pk,
            Resume.archived_at.is_(None),
        )
        .first()
    )
    if old is None:
        raise ValueError("要替换的简历不存在")
    inherit_default = bool(old.is_default)
    old.is_default = False
    old.archived_at = utc_now()
    db.add(old)
    db.flush()
    resume = _create_resume_locked(
        db,
        user_pk=user_pk,
        file_asset_id=file_asset_id,
        title=title,
        raw_text_snapshot=raw_text_snapshot,
        structured_json=structured_json,
        make_default=inherit_default,
    )
    db.commit()
    db.refresh(resume)
    return resume


def set_default_resume(db: Session, *, user_id: str, resume_id: str) -> Resume | None:
    user_pk = _lock_user(db, user_id)
    resume = (
        db.query(Resume)
        .filter(
            Resume.id == resume_id,
            Resume.user_id == user_pk,
            Resume.archived_at.is_(None),
        )
        .first()
    )
    if resume is None:
        db.rollback()
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
    user_pk = _lock_user(db, user_id)
    resume = (
        db.query(Resume)
        .filter(
            Resume.id == resume_id,
            Resume.user_id == user_pk,
            Resume.archived_at.is_(None),
        )
        .first()
    )
    if resume is None:
        db.rollback()
        return False
    was_default = resume.is_default
    resume.is_default = False
    resume.archived_at = utc_now()
    db.add(resume)
    from app.services.resume.reindex_jobs import enqueue_resume_reindex

    enqueue_resume_reindex(db, user_pk=resume.user_id, resume_id=resume.id)
    db.flush()
    if was_default:
        remaining = _active_resumes(db, resume.user_id)
        if remaining:
            remaining[0].is_default = True
    db.commit()
    return True
