"""Memory inspection + management endpoints (v3 architecture).

Surfaces the three Memory stores under ``/memory/...``:

  GET    /memory/overview                  — one-shot summary for the UI
  GET    /memory/ability-states            — list active per-topic states
  DELETE /memory/ability-states/{id}       — archive one state
  GET    /memory/user-profile              — read the user_profile doc
  PUT    /memory/user-profile              — user-edit the user_profile doc
  GET    /memory/learning-strategy         — read the learning_strategy doc
  PUT    /memory/learning-strategy         — user-edit the learning_strategy doc
  GET    /memory/audit                     — paginated audit log
  GET    /memory/audit/{entry_id}          — full before/after for one entry
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.memory_audit_logs import CHANGE_TYPES, MemoryAuditEntry
from app.models.user import User
from app.services.memory import memory_ability_state_service, memory_document_service
from app.services.memory._user_memory_lock import user_memory_lock_sync

router = APIRouter(tags=["memory"])


# ── Schemas ────────────────────────────────────────────────────────────


class DocBodyRequest(BaseModel):
    body: str = Field("", description="Full new body markdown.")


def _ability_payload(s) -> dict:
    return {
        "id": s.id,
        "topic": s.topic,
        "skill_type": s.skill_type,
        "mastery_level": s.mastery_level,
        "summary": s.summary or "",
        "last_evidence_at": s.last_evidence_at.isoformat() if s.last_evidence_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


# ── Overview ───────────────────────────────────────────────────────────


@router.get("/memory/overview")
def memory_overview(current_user: User = Depends(get_current_user)):
    """One-shot summary of all Memory stores for the UI, over one session."""
    from app.services.memory._db_helpers import session_scope

    user_id = current_user.username
    with session_scope(None) as db:
        return {
            "user_profile_body": memory_document_service.load(user_id, "user_profile", db=db),
            "learning_strategy_body": memory_document_service.load(
                user_id, "learning_strategy", db=db,
            ),
            "ability_states": [
                _ability_payload(s)
                for s in memory_ability_state_service.load_active(user_id, db=db)
            ],
        }


# ── ability states ──────────────────────────────────────────────────────


@router.get("/memory/ability-states")
def list_ability_states(current_user: User = Depends(get_current_user)):
    return {
        "ability_states": [
            _ability_payload(s)
            for s in memory_ability_state_service.load_active(current_user.username)
        ]
    }


@router.delete("/memory/ability-states/{state_id}")
def delete_ability_state(
    state_id: str,
    current_user: User = Depends(get_current_user),
):
    with user_memory_lock_sync(current_user.username):
        archived = memory_ability_state_service.archive_by_id(current_user.username, state_id)
    if not archived:
        raise HTTPException(status_code=404, detail="ability state not found")
    return {"status": "success", "id": state_id}


# ── memory documents (user_profile / learning_strategy) ─────────────────


@router.get("/memory/user-profile")
def get_user_profile(current_user: User = Depends(get_current_user)):
    return {"body": memory_document_service.load(current_user.username, "user_profile")}


@router.put("/memory/user-profile")
def edit_user_profile(
    payload: DocBodyRequest,
    current_user: User = Depends(get_current_user),
):
    with user_memory_lock_sync(current_user.username):
        body = memory_document_service.upsert_user_edit(
            current_user.username, "user_profile", payload.body,
        )
    return {"status": "success", "body": body}


@router.get("/memory/learning-strategy")
def get_learning_strategy(current_user: User = Depends(get_current_user)):
    return {"body": memory_document_service.load(current_user.username, "learning_strategy")}


@router.put("/memory/learning-strategy")
def edit_learning_strategy(
    payload: DocBodyRequest,
    current_user: User = Depends(get_current_user),
):
    with user_memory_lock_sync(current_user.username):
        body = memory_document_service.upsert_user_edit(
            current_user.username, "learning_strategy", payload.body,
        )
    return {"status": "success", "body": body}


# ── memory_audit_logs read API ──────────────────────────────────────────


_VALID_DOC_TYPES = {"user_profile", "learning_strategy"}


@router.get("/memory/audit")
def list_memory_audit(
    doc_type: str | None = Query(
        None, description="Filter to one doc_type (user_profile/learning_strategy)."
    ),
    topic: str | None = Query(None, description="Filter to one ability-state topic."),
    change_type: str | None = Query(
        None,
        description="Filter to one change_type "
                    "(patch_realtime/patch_dreaming/user_edit/user_delete).",
    ),
    since: datetime | None = Query(
        None, description="Only entries created at or after this ISO-8601 timestamp."
    ),
    limit: int = Query(50, ge=1, le=200, description="Page size."),
    offset: int = Query(0, ge=0, description="Skip this many newest entries."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Paginated reverse-chronological audit log for the current user."""
    if doc_type is not None and doc_type not in _VALID_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid doc_type: must be one of {sorted(_VALID_DOC_TYPES)}",
        )
    if change_type is not None and change_type not in CHANGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid change_type: must be one of {sorted(CHANGE_TYPES)}",
        )

    user_pk = resolve_user_pk(db, current_user.username)
    if user_pk is None:
        return {"total": 0, "limit": limit, "offset": offset, "entries": []}

    q = db.query(MemoryAuditEntry).filter(MemoryAuditEntry.user_id == user_pk)
    if doc_type:
        q = q.filter(MemoryAuditEntry.doc_type == doc_type)
    if topic:
        q = q.filter(MemoryAuditEntry.topic == topic)
    if change_type:
        q = q.filter(MemoryAuditEntry.change_type == change_type)
    if since is not None:
        q = q.filter(MemoryAuditEntry.created_at >= since)

    total = q.count()
    rows = q.order_by(MemoryAuditEntry.created_at.desc()).offset(offset).limit(limit).all()
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
                "source_conversation_id": r.source_conversation_id,
                "source_interview_record_id": r.source_interview_record_id,
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
    user_pk = resolve_user_pk(db, current_user.username)
    row = (
        db.query(MemoryAuditEntry)
        .filter(MemoryAuditEntry.id == entry_id, MemoryAuditEntry.user_id == user_pk)
        .first()
        if user_pk is not None else None
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
        "source_conversation_id": row.source_conversation_id,
        "source_interview_record_id": row.source_interview_record_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
