"""Memory inspection + management endpoints (v3 architecture).

Exposes the four v3 doc types via a uniform ``/memory/...`` surface:

  GET  /memory/overview              — index for all 4 doc types
  GET  /memory/knowledge/topics       — list every knowledge_doc topic
  GET  /memory/knowledge/topics/{t}   — read one topic's body
  PUT  /memory/knowledge/topics/{t}   — user-edit a topic's body
  DELETE /memory/knowledge/topics/{t} — drop a topic
  GET  /memory/strategy               — read strategy_doc
  PUT  /memory/strategy               — user-edit strategy_doc
  GET  /memory/habit                  — read habit_doc
  PUT  /memory/habit                  — user-edit habit_doc
  GET  /memory/user-profile           — read user_profile_doc (raw text)

Legacy ``/memory/items*`` endpoints (per-row interview_fact CRUD) are
removed; the underlying ``memory_items`` table was dropped by alembic
0003.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.memory_audit_log import MemoryAuditLog
from app.models.user import User
from app.services.memory import (
    habit_doc_service,
    knowledge_doc_service,
    strategy_doc_service,
    user_profile_doc_service,
)
from app.services.memory._user_memory_lock import user_memory_lock_sync

router = APIRouter(tags=["memory"])


# ── Schemas ────────────────────────────────────────────────────────────


class TopicBodyRequest(BaseModel):
    body: str = Field("", description="Full new body markdown.")
    one_liner: str | None = None
    mastery_level: str | None = Field(
        None,
        description="One of: weak | progressing | strong | unknown",
    )


class DocBodyRequest(BaseModel):
    body: str = Field("", description="Full new body markdown.")


# ── Overview ───────────────────────────────────────────────────────────


@router.get("/memory/overview")
def memory_overview(current_user: User = Depends(get_current_user)):
    """One-shot summary of all four memory artifacts for the UI.

    Opens ONE database session and threads it through all four
    doc-service reads — pre-fix each opened its own ``SessionLocal``
    (4 connections per page load). Same pattern P1-F applied to
    ``load_universal`` for the agent path; this endpoint is the
    user-facing equivalent.

    The knowledge-topics ORM row attributes (``topic``, ``one_liner``,
    etc.) are read INSIDE the ``with`` block via the list comprehension
    — they must be touched before the session closes (per the
    ``knowledge_doc_service.load_all`` docstring contract).
    """
    from app.services.memory._db_helpers import session_scope

    user_id = current_user.username
    with session_scope(None) as db:
        return {
            "user_profile_body": user_profile_doc_service.load(user_id, db=db),
            "knowledge_topics": [
                {
                    "topic": d.topic,
                    "one_liner": d.one_liner,
                    "mastery_level": d.mastery_level,
                    "fact_count": d.fact_count,
                    "last_discussed_at": (
                        d.last_discussed_at.isoformat() if d.last_discussed_at else None
                    ),
                    "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                }
                for d in knowledge_doc_service.load_all(user_id, db=db)
            ],
            "strategy_body": strategy_doc_service.load(user_id, db=db),
            "habit_body": habit_doc_service.load(user_id, db=db),
        }


# ── knowledge_doc ──────────────────────────────────────────────────────


@router.get("/memory/knowledge/topics")
def list_knowledge_topics(current_user: User = Depends(get_current_user)):
    user_id = current_user.username
    return {
        "topics": [
            {
                "topic": d.topic,
                "one_liner": d.one_liner,
                "mastery_level": d.mastery_level,
                "fact_count": d.fact_count,
                "last_discussed_at": (
                    d.last_discussed_at.isoformat() if d.last_discussed_at else None
                ),
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in knowledge_doc_service.load_all(user_id)
        ]
    }


@router.get("/memory/knowledge/topics/{topic}")
def get_knowledge_topic(
    topic: str,
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.username
    doc = knowledge_doc_service.load(user_id, topic)
    if doc is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {
        "topic": doc.topic,
        "body": doc.body,
        "one_liner": doc.one_liner,
        "mastery_level": doc.mastery_level,
        "fact_count": doc.fact_count,
        "last_discussed_at": (
            doc.last_discussed_at.isoformat() if doc.last_discussed_at else None
        ),
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


@router.put("/memory/knowledge/topics/{topic}")
def edit_knowledge_topic(
    topic: str,
    payload: TopicBodyRequest,
    current_user: User = Depends(get_current_user),
):
    # Hold the per-user memory lock for the duration of the user edit so
    # we serialise with realtime extraction + dreaming writers on the
    # same docs.
    with user_memory_lock_sync(current_user.username):
        try:
            doc = knowledge_doc_service.upsert_user_edit(
                user_id=current_user.username,
                topic=topic,
                new_body=payload.body,
                new_one_liner=payload.one_liner,
                new_mastery_level=payload.mastery_level,
            )
        except ValueError as exc:
            # _sanitize_topic returned an empty string — the path param
            # was all forbidden chars. Surface as 422 rather than 500.
            raise HTTPException(status_code=422, detail=f"invalid topic: {exc}") from exc
    return {"status": "success", "topic": doc.topic, "fact_count": doc.fact_count}


@router.delete("/memory/knowledge/topics/{topic}")
def delete_knowledge_topic(
    topic: str,
    current_user: User = Depends(get_current_user),
):
    with user_memory_lock_sync(current_user.username):
        deleted = knowledge_doc_service.delete_topic(current_user.username, topic)
    if not deleted:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"status": "success", "topic": topic}


# ── strategy_doc + habit_doc ───────────────────────────────────────────


@router.get("/memory/strategy")
def get_strategy_doc(current_user: User = Depends(get_current_user)):
    return {"body": strategy_doc_service.load(current_user.username)}


@router.put("/memory/strategy")
def edit_strategy_doc(
    payload: DocBodyRequest,
    current_user: User = Depends(get_current_user),
):
    with user_memory_lock_sync(current_user.username):
        body = strategy_doc_service.upsert_user_edit(current_user.username, payload.body)
    return {"status": "success", "body": body}


@router.get("/memory/habit")
def get_habit_doc(current_user: User = Depends(get_current_user)):
    return {"body": habit_doc_service.load(current_user.username)}


@router.put("/memory/habit")
def edit_habit_doc(
    payload: DocBodyRequest,
    current_user: User = Depends(get_current_user),
):
    with user_memory_lock_sync(current_user.username):
        body = habit_doc_service.upsert_user_edit(current_user.username, payload.body)
    return {"status": "success", "body": body}


# ── user_profile_doc ───────────────────────────────────────────────────


@router.get("/memory/user-profile")
def get_user_profile_doc(current_user: User = Depends(get_current_user)):
    return {"body": user_profile_doc_service.load(current_user.username)}


# ── memory_audit_log read API (Checkpoint 3, F9b) ─────────────────────


_VALID_DOC_TYPES = {"user_profile", "knowledge", "strategy", "habit"}
_VALID_CHANGE_TYPES = {
    "patch_realtime",
    "patch_dreaming",
    "user_edit",
    "user_delete",
    "migration",
}


@router.get("/memory/audit")
def list_memory_audit(
    doc_type: str | None = Query(
        None, description="Filter to one doc_type (user_profile/knowledge/strategy/habit)."
    ),
    topic: str | None = Query(
        None, description="Filter to one knowledge topic (only meaningful with doc_type=knowledge)."
    ),
    change_type: str | None = Query(
        None, description="Filter to one change_type (patch_realtime/patch_dreaming/user_edit/user_delete/migration)."
    ),
    since: datetime | None = Query(
        None, description="Only entries created at or after this ISO-8601 timestamp."
    ),
    limit: int = Query(50, ge=1, le=200, description="Page size."),
    offset: int = Query(0, ge=0, description="Skip this many newest entries."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Paginated reverse-chronological audit log for the current user.

    Drives the "browse my memory history" UI and lets operators answer
    *"why does my user profile look weird?"* by joining ``source_record_id``
    or ``source_session_id`` to the live chat / interview data. Always
    user-scoped — there is no cross-user lookup path.
    """
    if doc_type is not None and doc_type not in _VALID_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid doc_type: must be one of {sorted(_VALID_DOC_TYPES)}",
        )
    if change_type is not None and change_type not in _VALID_CHANGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid change_type: must be one of {sorted(_VALID_CHANGE_TYPES)}",
        )

    q = (
        db.query(MemoryAuditLog)
        .filter(MemoryAuditLog.user_id == current_user.username)
    )
    if doc_type:
        q = q.filter(MemoryAuditLog.doc_type == doc_type)
    if topic:
        q = q.filter(MemoryAuditLog.topic == topic)
    if change_type:
        q = q.filter(MemoryAuditLog.change_type == change_type)
    if since is not None:
        q = q.filter(MemoryAuditLog.created_at >= since)

    total = q.count()
    rows = (
        q.order_by(MemoryAuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "entries": [
            {
                "id": r.id,
                "doc_type": r.doc_type,
                "topic": r.topic,
                "change_type": r.change_type,
                "summary": r.summary,
                "source_record_id": r.source_record_id,
                "source_session_id": r.source_session_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/memory/audit/{entry_id}")
def get_memory_audit_entry(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Full before/after bodies for one audit entry. Use to render diffs."""
    row = (
        db.query(MemoryAuditLog)
        .filter(
            MemoryAuditLog.id == entry_id,
            MemoryAuditLog.user_id == current_user.username,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="audit entry not found")
    return {
        "id": row.id,
        "doc_type": row.doc_type,
        "topic": row.topic,
        "change_type": row.change_type,
        "summary": row.summary,
        "before_body": row.before_body or "",
        "after_body": row.after_body or "",
        "source_record_id": row.source_record_id,
        "source_session_id": row.source_session_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
