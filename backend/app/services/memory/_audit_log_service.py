"""Thin write helper for ``memory_audit_log``.

Append-only. No update / delete API — audit logs are immutable.

Failure mode: any DB error during audit write is swallowed with a
warning. We never want a failed audit write to break the actual memory
update — the audit trail is best-effort accountability, not a
correctness primitive.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.memory_audit_log import MemoryAuditLog

logger = logging.getLogger(__name__)


_VALID_DOC_TYPES = {"user_profile", "knowledge", "strategy", "habit"}
_VALID_CHANGE_TYPES = {
    "patch_realtime",
    "patch_dreaming",
    "user_edit",
    "user_delete",
    "migration",
}


def record(
    *,
    user_id: str,
    doc_type: str,
    change_type: str,
    before_body: str = "",
    after_body: str = "",
    summary: Optional[str] = None,
    topic: Optional[str] = None,
    source_record_id: Optional[str] = None,
    source_session_id: Optional[str] = None,
    db: Optional[Session] = None,
) -> None:
    """Write one audit entry.

    Two modes:

    * ``db=None`` (own session): we open + commit + close ourselves.
      All exceptions are swallowed with a warning — audit failures
      cannot break business logic when we own the session.
    * ``db=<caller's session>`` (shared session): we ``db.add`` the row
      and let the caller's commit handle persistence. **Exceptions
      propagate** — silently swallowing here would leave a poisoned
      row queued in the caller's session and the next caller-side
      commit would fail with no traceable cause (the audit row's
      failure would surface as "your business write failed"). The
      caller's existing ``try / except / rollback`` is the right place
      to handle this.
    """
    if doc_type not in _VALID_DOC_TYPES:
        logger.warning("audit_log: invalid doc_type %r — skipping write", doc_type)
        return
    if change_type not in _VALID_CHANGE_TYPES:
        logger.warning("audit_log: invalid change_type %r — skipping write", change_type)
        return

    row = MemoryAuditLog(
        user_id=user_id,
        doc_type=doc_type,
        topic=topic,
        change_type=change_type,
        source_record_id=source_record_id,
        source_session_id=source_session_id,
        before_body=before_body or "",
        after_body=after_body or "",
        summary=(summary or "")[:500] or None,
    )

    if db is not None:
        # Shared session — propagate exceptions. The caller wraps the
        # whole transaction in try/except/rollback already.
        db.add(row)
        return

    # Own session — swallow exceptions so audit failures never break
    # business logic. The trade-off is that an unwritten audit row is
    # silently lost; that's acceptable for an accountability trail
    # (vs. a correctness primitive).
    db_own = SessionLocal()
    try:
        db_own.add(row)
        db_own.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            db_own.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "audit_log: write failed for user=%s doc=%s change=%s: %s",
            user_id, doc_type, change_type, exc,
        )
    finally:
        db_own.close()


__all__ = ["record"]
