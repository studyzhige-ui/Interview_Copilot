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
from datetime import datetime, timedelta
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
from app.services.memory import _memory_audit, _metrics
from app.services.memory._db_helpers import session_scope

logger = logging.getLogger(__name__)


class UnknownUser(Exception):
    """Raised when a username has no ``users`` row."""


def build_search_text(topic: str, summary: str | None) -> str:
    """Normalised text for the Milvus ability collection: topic + summary."""
    parts = [p.strip() for p in (topic or "", summary or "") if p and p.strip()]
    return "\n".join(parts)


def _enqueue_index_upsert(db: Session, *, user_pk: int, row) -> None:
    """Queue a durable Milvus re-index for this ability state, in the caller's
    transaction. ``payload.user_id`` is the stable users.id pk — the same value
    the ability collection's node metadata and search filter key on (CLEANUP #2)."""
    from app.services.uploads.outbox_service import enqueue_job

    enqueue_job(
        db,
        user_pk=user_pk,
        job_type="upsert_memory_ability_index",
        aggregate_type="memory_ability_state",
        aggregate_id=row.id,
        payload={
            "state_id": row.id,
            "user_id": user_pk,
            "search_text": row.search_text or "",
            "topic": row.topic,
            "skill_type": row.skill_type,
            "mastery_level": row.mastery_level,
            "summary": row.summary or "",
        },
    )


def _enqueue_index_delete(db: Session, *, user_pk: int, state_id: str) -> None:
    from app.services.uploads.outbox_service import enqueue_job

    enqueue_job(
        db,
        user_pk=user_pk,
        job_type="delete_memory_ability_index",
        aggregate_type="memory_ability_state",
        aggregate_id=state_id,
        payload={"state_id": state_id},
    )


def _validate(skill_type: str, mastery_level: str) -> None:
    if skill_type not in SKILL_TYPES:
        raise ValueError(
            f"unknown skill_type {skill_type!r}; expected one of {SKILL_TYPES}"
        )
    if mastery_level not in MASTERY_LEVELS:
        raise ValueError(
            f"unknown mastery_level {mastery_level!r}; expected one of {MASTERY_LEVELS}"
        )


# ── reads ───────────────────────────────────────────────────────────────


def load_active(
    username: str, *, db: Session | None = None
) -> list[MemoryAbilityState]:
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
    username: str,
    levels: tuple[str, ...],
    *,
    db: Session | None = None,
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


# ── Mastery upgrade discipline (MEM-4) ─────────────────────────────────
# The prompt asks the LLM to be conservative, but prompts are advice —
# these rules are mechanism. Realtime extraction (one conversation's worth
# of signal, including plain self-reporting like "我精通K8s") can move a
# level at most one step up per pass and can NEVER write ``strong``
# without concrete evidence refs. Dreaming (cross-session synthesis over
# real interview records) and user edits are unrestricted.

# How long a user-archived (topic, skill_type) blocks automatic re-creation
# (MEM-2): the user's delete is a veto, not a suggestion.
_TOMBSTONE_WINDOW = timedelta(days=30)

_MASTERY_ORDER = {"weak": 0, "improving": 1, "stable": 2, "strong": 3}


def _disciplined_mastery(
    *,
    requested: str,
    current: str | None,
    change_type: str,
    has_evidence: bool,
) -> tuple[str, str | None]:
    """Return ``(effective_level, clamp_reason)`` for the realtime channel.

    Rationale (MEM-4): prompts asking the LLM to "be conservative" are
    advice; these rules are mechanism. Realtime = one conversation's worth
    of signal, so per pass it may move a level at most one step up (two
    steps from nothing when concrete evidence rides along — a demonstrated
    first observation may land at improving), and an UPGRADE to strong
    always requires evidence refs. Re-affirming an existing level is never
    a demotion (a summary refresh without an evidence array must not knock
    strong down). Downgrades are always allowed — forgetting is real.
    Dreaming (cross-session synthesis) and user edits are unrestricted.
    """
    if change_type != "patch_realtime":
        return requested, None
    req = _MASTERY_ORDER.get(requested, 0)
    cur = _MASTERY_ORDER.get(current, -1) if current else -1
    if req <= cur:
        return requested, None  # same level or downgrade — always allowed

    effective = req
    reason = None
    step_cap = cur + (2 if (cur < 0 and has_evidence) else 1)
    if req > step_cap:
        effective = step_cap
        reason = "realtime_step_limit"
    if effective >= _MASTERY_ORDER["strong"] and not has_evidence:
        effective = _MASTERY_ORDER["stable"]
        reason = "strong_requires_evidence"
    if effective == req:
        return requested, None
    level = next(k for k, v in _MASTERY_ORDER.items() if v == effective)
    return level, reason


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
            db=db,
            username=username,
            topic=topic,
            skill_type=skill_type,
            mastery_level=mastery_level,
            summary=summary,
            evidence_refs=evidence_refs,
            last_evidence_at=last_evidence_at,
            change_type=change_type,
            source_conversation_id=source_conversation_id,
            source_interview_record_id=source_interview_record_id,
            idempotency_key=idempotency_key,
        )
        if own_db:
            db.commit()
            if row is not None:
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
                db=db,
                username=username,
                topic=topic,
                skill_type=skill_type,
                mastery_level=mastery_level,
                summary=summary,
                evidence_refs=evidence_refs,
                last_evidence_at=last_evidence_at,
                change_type=change_type,
                source_conversation_id=source_conversation_id,
                source_interview_record_id=source_interview_record_id,
                idempotency_key=idempotency_key,
            )
            db.commit()
            if row is not None:
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


def _blocked_by_tombstone(
    db: Session,
    *,
    user_pk: int,
    topic: str,
    skill_type: str,
) -> bool:
    """An archived twin younger than the tombstone window exists."""
    return (
        db.query(MemoryAbilityState.id)
        .filter(
            MemoryAbilityState.user_id == user_pk,
            MemoryAbilityState.topic == topic,
            MemoryAbilityState.skill_type == skill_type,
            MemoryAbilityState.archived_at.isnot(None),
            MemoryAbilityState.archived_at > datetime.utcnow() - _TOMBSTONE_WINDOW,
        )
        .first()
        is not None
    )


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
) -> MemoryAbilityState | None:
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

    # ── Tombstone (MEM-2): an archive is a veto ─────────────────────
    # A user-archived state used to be silently recreated by the next
    # extraction pass over the same topic — the deleted hallucination
    # resurrecting days later is the single most trust-destroying
    # behaviour a memory system can have. Automatic channels are blocked
    # from re-creating the pair for 30 days. Deliberately provenance-blind:
    # a dreaming retirement also damps churn for the window (both archive
    # kinds are in the audit trail if this ever needs distinguishing).
    # The user's own edits still work immediately.
    if was_new and change_type in ("patch_realtime", "patch_dreaming"):
        if _blocked_by_tombstone(
            db, user_pk=user_pk, topic=topic, skill_type=skill_type
        ):
            _metrics.incr(
                "memory.patch_dropped",
                reason="tombstone",
                target="ability_state",
                change_type=change_type,
            )
            logger.info(
                "ability upsert blocked by tombstone user=%s topic=%s/%s",
                username,
                topic,
                skill_type,
            )
            return None

    # ── Mastery discipline (MEM-4) ──────────────────────────────────
    effective_level, clamp_reason = _disciplined_mastery(
        requested=mastery_level,
        current=None if was_new else row.mastery_level,
        change_type=change_type,
        has_evidence=bool(evidence_refs),
    )
    if clamp_reason:
        _metrics.incr(
            "memory.mastery_clamped",
            reason=clamp_reason,
            requested=mastery_level,
            clamped_to=effective_level,
            change_type=change_type,
        )
    mastery_level = effective_level

    # Audit bodies carry the mastery value, not just the summary — the
    # "before" level used to be unrecoverable from the trail (MEM-10).
    before = "" if was_new else f"[{row.mastery_level}] {row.summary or ''}"
    evidence_json = (
        json.dumps(evidence_refs, ensure_ascii=False) if evidence_refs else None
    )
    search_text = build_search_text(topic, summary)

    if was_new:
        row = MemoryAbilityState(
            user_id=user_pk,
            topic=topic,
            skill_type=skill_type,
            mastery_level=mastery_level,
            summary=summary,
            evidence_refs_json=evidence_json,
            search_text=search_text,
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
        # Every upsert from the extraction channels IS fresh evidence —
        # default-bump so the field actually "drives staleness" as the
        # model docstring promises (callers never pass it explicitly,
        # which used to freeze it at row-creation time forever).
        row.last_evidence_at = last_evidence_at or datetime.utcnow()
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
        after_body=f"[{mastery_level}] {summary or ''}",
        summary=f"{'created' if was_new else 'updated'} ability "
        f"{topic}/{skill_type} → {mastery_level}",
        db=db,
    )
    _enqueue_index_upsert(db, user_pk=user_pk, row=row)
    return row


def archive(
    username: str,
    *,
    topic: str,
    skill_type: str,
    db: Session | None = None,
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


def archive_by_key(
    username: str,
    *,
    topic: str,
    skill_type: str,
    change_type: str,
    source_interview_record_id: str | None = None,
    db: Session | None = None,
) -> bool:
    """Archive the active (topic, skill_type) state — the dreaming
    retirement path (MEM-9): the ability ledger can now shrink, not just
    grow. Returns False when no active row matches."""
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
        return _archive_row(
            db,
            user_pk,
            row,
            own_db,
            change_type=change_type,
            source_interview_record_id=source_interview_record_id,
        )
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


def _archive_row(
    db: Session,
    user_pk: int,
    row,
    own_db: bool,
    *,
    change_type: str = "user_delete",
    source_interview_record_id: str | None = None,
) -> bool:
    """Shared archive core for all three entry points (by key / by id /
    user veto). Audits with the mastery-tagged before body — the user-veto
    deletes are exactly the ones most likely to need reverting."""
    if row is None:
        return False
    before = f"[{row.mastery_level}] {row.summary or ''}"
    row.archived_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    db.add(row)
    _memory_audit.record(
        user_pk=user_pk,
        change_type=change_type,
        topic=row.topic,
        memory_ability_state_id=row.id,
        source_interview_record_id=source_interview_record_id,
        before_body=before,
        after_body="",
        summary=f"archived ability {row.topic}/{row.skill_type}",
        db=db,
    )
    _enqueue_index_delete(db, user_pk=user_pk, state_id=row.id)
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
    "archive_by_key",
    "UnknownUser",
]
