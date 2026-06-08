"""Read/write service for ``memory_ability_states`` (per-topic mastery).

One *active* state per ``(user, topic, skill_type)`` — upsert updates the live
row in place, ``archive`` retires it (keeping history). Postgres is the fact
source; ``search_text`` is the normalised copy the Milvus ability collection
indexes (wired in MEM-JOBS-MILVUS).

Same safety properties as ``memory_document_service``: stable-id resolution,
IntegrityError-retry on the active-uniqueness race, optional ``idempotency_key``
for retried jobs, and audit on every mutation.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.memory_ability_state import (
    MASTERY_LEVELS,
    SKILL_TYPES,
    MemoryAbilityState,
)
from app.services.memory import _memory_audit
from app.services.memory._db_helpers import session_scope

logger = logging.getLogger(__name__)


class UnknownUser(Exception):
    """Raised when a username has no ``users`` row."""


def build_search_text(topic: str, summary: str | None) -> str:
    """Normalised text for the Milvus ability collection: topic + summary."""
    parts = [p.strip() for p in (topic or "", summary or "") if p and p.strip()]
    return "\n".join(parts)


def _validate(skill_type: str, mastery_level: str) -> None:
    if skill_type not in SKILL_TYPES:
        raise ValueError(f"unknown skill_type {skill_type!r}; expected one of {SKILL_TYPES}")
    if mastery_level not in MASTERY_LEVELS:
        raise ValueError(
            f"unknown mastery_level {mastery_level!r}; expected one of {MASTERY_LEVELS}"
        )


# ── reads ───────────────────────────────────────────────────────────────


def load_active(username: str, *, db: Session | None = None) -> list[MemoryAbilityState]:
    """All of the user's active (non-archived) ability states, newest first."""
    with session_scope(db) as session:
        user_pk = resolve_user_pk(session, username)
        if user_pk is None:
            return []
        return (
            session.query(MemoryAbilityState)
            .filter(
                MemoryAbilityState.user_id == user_pk,
                MemoryAbilityState.archived_at.is_(None),
            )
            .order_by(MemoryAbilityState.updated_at.desc())
            .all()
        )


def list_by_mastery(
    username: str, levels: tuple[str, ...], *, db: Session | None = None,
) -> list[MemoryAbilityState]:
    """Active states filtered to the given mastery levels (e.g. weak topics for
    diagnostics)."""
    with session_scope(db) as session:
        user_pk = resolve_user_pk(session, username)
        if user_pk is None:
            return []
        return (
            session.query(MemoryAbilityState)
            .filter(
                MemoryAbilityState.user_id == user_pk,
                MemoryAbilityState.archived_at.is_(None),
                MemoryAbilityState.mastery_level.in_(levels),
            )
            .order_by(MemoryAbilityState.updated_at.desc())
            .all()
        )


# ── writes ──────────────────────────────────────────────────────────────


def upsert(
    username: str,
    *,
    topic: str,
    skill_type: str,
    mastery_level: str,
    summary: str | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    last_evidence_at: datetime | None = None,
    change_type: str,
    source_conversation_id: str | None = None,
    source_interview_record_id: str | None = None,
    idempotency_key: str | None = None,
    db: Session | None = None,
) -> MemoryAbilityState | None:
    """Create or update the active state for ``(user, topic, skill_type)``.

    Returns the persisted row, or ``None`` if an idempotency key indicates the
    write was already applied.
    """
    _validate(skill_type, mastery_level)

    if idempotency_key and _memory_audit.already_applied(idempotency_key, db=db):
        return None

    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        row = _upsert_inner(
            db=db, username=username, topic=topic, skill_type=skill_type,
            mastery_level=mastery_level, summary=summary, evidence_refs=evidence_refs,
            last_evidence_at=last_evidence_at, change_type=change_type,
            source_conversation_id=source_conversation_id,
            source_interview_record_id=source_interview_record_id,
            idempotency_key=idempotency_key,
        )
        if own_db:
            db.commit()
            db.refresh(row)
        return row
    except IntegrityError:
        if not own_db:
            raise
        db.rollback()
        db.close()
        db = SessionLocal()
        try:
            row = _upsert_inner(
                db=db, username=username, topic=topic, skill_type=skill_type,
                mastery_level=mastery_level, summary=summary, evidence_refs=evidence_refs,
                last_evidence_at=last_evidence_at, change_type=change_type,
                source_conversation_id=source_conversation_id,
                source_interview_record_id=source_interview_record_id,
                idempotency_key=idempotency_key,
            )
            db.commit()
            db.refresh(row)
            return row
        except Exception:
            db.rollback()
            raise
    except Exception:
        if own_db:
            db.rollback()
        raise
    finally:
        if own_db and db is not None:
            db.close()


def _upsert_inner(
    *,
    db: Session,
    username: str,
    topic: str,
    skill_type: str,
    mastery_level: str,
    summary: str | None,
    evidence_refs: list[dict[str, Any]] | None,
    last_evidence_at: datetime | None,
    change_type: str,
    source_conversation_id: str | None,
    source_interview_record_id: str | None,
    idempotency_key: str | None,
) -> MemoryAbilityState:
    user_pk = resolve_user_pk(db, username)
    if user_pk is None:
        raise UnknownUser(username)

    row = (
        db.query(MemoryAbilityState)
        .filter(
            MemoryAbilityState.user_id == user_pk,
            MemoryAbilityState.topic == topic,
            MemoryAbilityState.skill_type == skill_type,
            MemoryAbilityState.archived_at.is_(None),
        )
        .first()
    )
    was_new = row is None
    before = "" if was_new else (row.summary or "")
    evidence_json = json.dumps(evidence_refs, ensure_ascii=False) if evidence_refs else None
    search_text = build_search_text(topic, summary)

    if was_new:
        row = MemoryAbilityState(
            user_id=user_pk, topic=topic, skill_type=skill_type,
            mastery_level=mastery_level, summary=summary,
            evidence_refs_json=evidence_json, search_text=search_text,
            last_evidence_at=last_evidence_at or datetime.utcnow(),
        )
        db.add(row)
        db.flush()  # surface the active-uniqueness race now
    else:
        row.mastery_level = mastery_level
        row.summary = summary
        if evidence_json is not None:
            row.evidence_refs_json = evidence_json
        row.search_text = search_text
        if last_evidence_at is not None:
            row.last_evidence_at = last_evidence_at
        row.updated_at = datetime.utcnow()
        db.add(row)

    _memory_audit.record(
        user_pk=user_pk,
        change_type=change_type,
        topic=topic,
        memory_ability_state_id=row.id,
        source_conversation_id=source_conversation_id,
        source_interview_record_id=source_interview_record_id,
        idempotency_key=idempotency_key,
        before_body=before,
        after_body=summary or "",
        summary=f"{'created' if was_new else 'updated'} ability "
                f"{topic}/{skill_type} → {mastery_level}",
        db=db,
    )
    return row


def archive(
    username: str, *, topic: str, skill_type: str, db: Session | None = None,
) -> bool:
    """Retire the active state for ``(user, topic, skill_type)``. Returns True
    if a row was archived."""
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        user_pk = resolve_user_pk(db, username)
        if user_pk is None:
            return False
        row = (
            db.query(MemoryAbilityState)
            .filter(
                MemoryAbilityState.user_id == user_pk,
                MemoryAbilityState.topic == topic,
                MemoryAbilityState.skill_type == skill_type,
                MemoryAbilityState.archived_at.is_(None),
            )
            .first()
        )
        return _archive_row(db, user_pk, row, own_db)
    except Exception:
        if own_db:
            db.rollback()
        raise
    finally:
        if own_db and db is not None:
            db.close()


def archive_by_id(username: str, state_id: str, *, db: Session | None = None) -> bool:
    """Retire one active state by its id (user-scoped). Returns True if archived."""
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        user_pk = resolve_user_pk(db, username)
        if user_pk is None:
            return False
        row = (
            db.query(MemoryAbilityState)
            .filter(
                MemoryAbilityState.id == state_id,
                MemoryAbilityState.user_id == user_pk,
                MemoryAbilityState.archived_at.is_(None),
            )
            .first()
        )
        return _archive_row(db, user_pk, row, own_db)
    except Exception:
        if own_db:
            db.rollback()
        raise
    finally:
        if own_db and db is not None:
            db.close()


def _archive_row(db: Session, user_pk: int, row, own_db: bool) -> bool:
    if row is None:
        return False
    row.archived_at = datetime.utcnow()
    db.add(row)
    _memory_audit.record(
        user_pk=user_pk, change_type="user_delete", topic=row.topic,
        memory_ability_state_id=row.id,
        summary=f"archived ability {row.topic}/{row.skill_type}", db=db,
    )
    if own_db:
        db.commit()
    return True


__all__ = [
    "build_search_text",
    "load_active",
    "list_by_mastery",
    "upsert",
    "archive",
    "archive_by_id",
    "UnknownUser",
]
