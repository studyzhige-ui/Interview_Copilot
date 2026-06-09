"""Write helper for ``memory_audit_logs`` (the v3 audit trail).

Append-only; no update/delete. Mirrors the old ``_audit_log_service`` session
contract:

* ``db=None`` (own session): we open + commit + close, swallowing errors — an
  audit failure must never break the memory write it's recording.
* ``db=<caller's session>`` (shared): we ``add`` only and let the caller's
  commit persist it; exceptions propagate so the caller's transaction handler
  sees them rather than a silently poisoned session.

Adds ``already_applied`` so a retried extraction job can detect it has already
applied (and audited) a given patch and skip both the re-apply and the
duplicate audit row.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.memory_audit_logs import CHANGE_TYPES, MemoryAuditEntry

logger = logging.getLogger(__name__)


def already_applied(idempotency_key: str, *, db: Session | None = None) -> bool:
    """True if an audit entry with this idempotency key already exists.

    Used by retried memory jobs to avoid re-applying / re-auditing a patch.
    An empty/None key is never considered applied.
    """
    if not idempotency_key:
        return False
    from app.services.memory._db_helpers import session_scope

    with session_scope(db) as session:
        return (
            session.query(MemoryAuditEntry.id)
            .filter(MemoryAuditEntry.idempotency_key == idempotency_key)
            .first()
            is not None
        )


def record(
    *,
    user_pk: int,
    change_type: str,
    doc_type: str | None = None,
    topic: str | None = None,
    memory_document_id: str | None = None,
    memory_ability_state_id: str | None = None,
    source_conversation_id: str | None = None,
    source_interview_record_id: str | None = None,
    source_message_range_json: str | None = None,
    idempotency_key: str | None = None,
    before_body: str = "",
    after_body: str = "",
    summary: str | None = None,
    db: Session | None = None,
) -> None:
    """Write one audit entry (see module docstring for the session contract)."""
    if change_type not in CHANGE_TYPES:
        logger.warning("memory_audit: invalid change_type %r — skipping write", change_type)
        return

    row = MemoryAuditEntry(
        user_id=user_pk,
        change_type=change_type,
        doc_type=doc_type,
        topic=topic,
        memory_document_id=memory_document_id,
        memory_ability_state_id=memory_ability_state_id,
        source_conversation_id=source_conversation_id,
        source_interview_record_id=source_interview_record_id,
        source_message_range_json=source_message_range_json,
        idempotency_key=idempotency_key or None,
        before_body=before_body or "",
        after_body=after_body or "",
        summary=(summary or "")[:500] or None,
    )

    if db is not None:
        # Shared session — propagate; the caller owns commit/rollback.
        db.add(row)
        return

    # Own session — swallow so a lost audit row never breaks business logic.
    own = SessionLocal()
    try:
        own.add(row)
        own.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            own.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "memory_audit: write failed for user=%s change=%s: %s",
            user_pk, change_type, exc,
        )
    finally:
        own.close()


__all__ = ["record", "already_applied"]
