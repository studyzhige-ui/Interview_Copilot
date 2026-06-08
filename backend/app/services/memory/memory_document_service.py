"""Read/write service for ``memory_documents`` (user_profile / learning_strategy).

One markdown doc per ``(user, doc_type)``, patched in place via the exact-line
patch protocol. Mirrors the old single-doc services' safety properties:

* Refuses to materialise a row when no patch actually landed (LLM-hallucination
  guard).
* IntegrityError-retry once on the ``(user_id, doc_type)`` unique constraint —
  two concurrent first-writes race, one INSERTs, the loser retries through the
  update branch (``user_memory_lock`` degrades to no-op on a Redis outage, so
  the DB constraint is the real backstop).
* Optional ``idempotency_key`` — a retried job that already applied a patch is
  detected via the audit trail and skipped.

The runtime threads a ``username``; this service resolves it to the stable
``users.id`` via ``resolve_user_pk``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.memory_document import DOC_TYPES, MemoryDocument
from app.services.memory import _memory_audit
from app.services.memory._db_helpers import session_scope
from app.services.memory._doc_patch_protocol import PatchResult, apply_patches as patch_body

logger = logging.getLogger(__name__)

_ONE_LINER_MAX = 280


class UnknownUser(Exception):
    """Raised when a username has no ``users`` row."""


def _validate_doc_type(doc_type: str) -> None:
    if doc_type not in DOC_TYPES:
        raise ValueError(f"unknown memory doc_type {doc_type!r}; expected one of {DOC_TYPES}")


def _derive_one_liner(body: str) -> str:
    """Cheap preview of the body for the always-loaded universal pass: the
    first few bullet lines, comma-joined, truncated."""
    bullets = [
        ln.strip()[2:].strip()
        for ln in (body or "").splitlines()
        if ln.strip().startswith("- ")
    ]
    if not bullets:
        return ""
    preview = "; ".join(bullets[:3])
    tail = "…" if len(bullets) > 3 else ""
    out = preview + tail
    return out if len(out) <= _ONE_LINER_MAX else out[: _ONE_LINER_MAX - 1] + "…"


# ── reads ───────────────────────────────────────────────────────────────


def load(username: str, doc_type: str, *, db: Session | None = None) -> str:
    """Return the doc body (empty string when there's no row / unknown user)."""
    _validate_doc_type(doc_type)
    with session_scope(db) as session:
        user_pk = resolve_user_pk(session, username)
        if user_pk is None:
            return ""
        row = (
            session.query(MemoryDocument)
            .filter(
                MemoryDocument.user_id == user_pk,
                MemoryDocument.doc_type == doc_type,
            )
            .first()
        )
        return (row.body if row else "") or ""


def load_description(username: str, doc_type: str, *, db: Session | None = None) -> str:
    """Universal-pass one-liner (empty string when no doc yet)."""
    _validate_doc_type(doc_type)
    with session_scope(db) as session:
        user_pk = resolve_user_pk(session, username)
        if user_pk is None:
            return ""
        row = (
            session.query(MemoryDocument)
            .filter(
                MemoryDocument.user_id == user_pk,
                MemoryDocument.doc_type == doc_type,
            )
            .first()
        )
        return ((row.one_liner if row else "") or "").strip()


# ── writes ──────────────────────────────────────────────────────────────


def apply_patches(
    username: str,
    doc_type: str,
    patches: Iterable[dict[str, Any]],
    *,
    change_type: str,
    source_conversation_id: str | None = None,
    source_interview_record_id: str | None = None,
    idempotency_key: str | None = None,
    db: Session | None = None,
) -> PatchResult:
    """Apply patches to ``(user, doc_type)`` with audit. Auto-creates the row.

    ``db`` shares the caller's transaction (add-only, caller commits). Without
    it we own a session and commit, with one IntegrityError retry.
    """
    _validate_doc_type(doc_type)

    # Idempotency: a retried job already applied this patch.
    if idempotency_key and _memory_audit.already_applied(idempotency_key, db=db):
        return PatchResult(body=load(username, doc_type, db=db), applied=0)

    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        user_pk = resolve_user_pk(db, username)
        if user_pk is None:
            raise UnknownUser(username)
        result = _apply_inner(
            db=db,
            user_pk=user_pk,
            doc_type=doc_type,
            patches=patches,
            change_type=change_type,
            source_conversation_id=source_conversation_id,
            source_interview_record_id=source_interview_record_id,
            idempotency_key=idempotency_key,
        )
        if own_db:
            db.commit()
        return result
    except IntegrityError:
        if not own_db:
            raise  # caller owns the transaction
        db.rollback()
        db.close()
        db = SessionLocal()
        try:
            user_pk = resolve_user_pk(db, username)
            if user_pk is None:
                raise UnknownUser(username)
            result = _apply_inner(
                db=db,
                user_pk=user_pk,
                doc_type=doc_type,
                patches=patches,
                change_type=change_type,
                source_conversation_id=source_conversation_id,
                source_interview_record_id=source_interview_record_id,
                idempotency_key=idempotency_key,
            )
            db.commit()
            return result
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


def _apply_inner(
    *,
    db: Session,
    user_pk: int,
    doc_type: str,
    patches: Iterable[dict[str, Any]],
    change_type: str,
    source_conversation_id: str | None,
    source_interview_record_id: str | None,
    idempotency_key: str | None,
) -> PatchResult:
    row = (
        db.query(MemoryDocument)
        .filter(MemoryDocument.user_id == user_pk, MemoryDocument.doc_type == doc_type)
        .first()
    )
    was_new = row is None

    if was_new:
        result = patch_body("", patches)
        new_body = result.body
        if result.applied == 0:
            # Don't create an empty row from all-hallucinated patches.
            return result
        row = MemoryDocument(
            user_id=user_pk,
            doc_type=doc_type,
            body=new_body,
            one_liner=_derive_one_liner(new_body),
            last_discussed_at=datetime.utcnow(),
        )
        db.add(row)
        db.flush()  # surface the unique-constraint race as IntegrityError now
        before_body = ""
    else:
        before_body = row.body or ""
        result = patch_body(before_body, patches)
        new_body = result.body
        if new_body == before_body:
            return result
        row.body = new_body
        row.one_liner = _derive_one_liner(new_body)
        row.last_discussed_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        db.add(row)

    _memory_audit.record(
        user_pk=user_pk,
        change_type=change_type,
        doc_type=doc_type,
        memory_document_id=row.id,
        source_conversation_id=source_conversation_id,
        source_interview_record_id=source_interview_record_id,
        idempotency_key=idempotency_key,
        before_body=before_body,
        after_body=new_body,
        summary=f"{'created' if was_new else 'updated'} "
                f"(applied={result.applied}, dropped={result.dropped})",
        db=db,
    )
    return result


def upsert_user_edit(username: str, doc_type: str, new_body: str) -> str:
    """Persist a user-edited body verbatim. Returns the stored body."""
    _validate_doc_type(doc_type)
    db: Session = SessionLocal()
    try:
        user_pk = resolve_user_pk(db, username)
        if user_pk is None:
            raise UnknownUser(username)
        row = (
            db.query(MemoryDocument)
            .filter(MemoryDocument.user_id == user_pk, MemoryDocument.doc_type == doc_type)
            .first()
        )
        was_new = row is None
        before_body = (row.body if row else "") or ""
        body = (new_body or "").strip("\n")
        if row is None:
            row = MemoryDocument(user_id=user_pk, doc_type=doc_type)
            db.add(row)
        row.body = body
        row.one_liner = _derive_one_liner(body)
        row.updated_at = datetime.utcnow()
        db.flush()
        _memory_audit.record(
            user_pk=user_pk,
            change_type="user_edit",
            doc_type=doc_type,
            memory_document_id=row.id,
            before_body=before_body,
            after_body=body,
            summary="created via user edit" if was_new else "user edit",
            db=db,
        )
        db.commit()
        return body
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


__all__ = ["load", "load_description", "apply_patches", "upsert_user_edit", "UnknownUser"]
