"""Resolve "is the GLOBAL memory toggle on?" for a chat session.

Semantics: this is the **cross-session memory** switch — same scope as
Claude Code's ``isAutoMemoryEnabled``. When off:

  * The v3 memory bundle (user_profile + ability states +
    learning_strategy) is NOT injected into the LLM prompt.
  * The planner doesn't see the user's memory inventory either, so it
    can't request body loads.
  * Session-local working context (recent_turns, [Record Context] for
    debrief sessions) STILL loads — those are per-conversation context,
    not "memory".
  * User-facing UI can still read the docs directly from the DB — the
    toggle only gates LLM INJECTION, not storage.

Two tiers of preference (first non-NULL wins):

  1. **Per-session override** — ``conversations.global_memory_enabled``
     (nullable Boolean column). Set by the toggle next to the "agent"
     button in the chat header. Takes precedence whenever non-NULL
     (even when explicitly set to False).
  2. **Per-user default** — ``users.global_memory_enabled`` column.
     Toggled in the 个人中心 preferences page. Used when the session-
     level value is NULL.

If both are NULL or unreadable, the policy falls back to ``False`` —
opt-in by design. A failed DB lookup also returns False so a transient
outage degrades safely (skip injection, keep answering) instead of
accidentally leaking memory contents.

Keep this module tiny and dependency-free so the QA pipeline can import
it without dragging in heavy retrieval/embedding modules.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.chat import Conversation
from app.models.user import User

logger = logging.getLogger(__name__)


def is_global_memory_enabled_for_session(session_id: str, user_id: str) -> bool:
    """Return True iff the GLOBAL (cross-session) memory bundle should be
    injected into the LLM prompt for this turn.

    Resolution order (first non-NULL wins):
      ``conversations.global_memory_enabled`` →
      ``users.global_memory_enabled`` → ``False``.
    """
    db: Session = SessionLocal()
    try:
        session_row = (
            db.query(Conversation.global_memory_enabled)
            .filter(Conversation.id == session_id)
            .first()
        )
        if session_row is not None and session_row[0] is not None:
            return bool(session_row[0])

        user_row = (
            db.query(User.global_memory_enabled)
            .filter(User.username == user_id)
            .first()
        )
        if user_row is not None and user_row[0] is not None:
            return bool(user_row[0])

        return False
    except Exception as exc:  # noqa: BLE001 — degrade safely, never block answering
        logger.warning(
            "recall_policy: lookup failed for %s/%s: %s",
            session_id, user_id, exc,
        )
        return False
    finally:
        db.close()


def set_session_global_memory(session_id: str, user_id: str, enabled: bool) -> None:
    """Persist a per-session override into the ``global_memory_enabled`` column.

    No-op (without raising) when the session doesn't exist or isn't owned by
    ``user_id`` — the API layer enforces ownership before calling this; this is
    the safety net.
    """
    db: Session = SessionLocal()
    try:
        row = db.query(Conversation).filter(Conversation.id == session_id).first()
        if row is None or row.user_id != resolve_user_pk(db, user_id):
            return
        row.global_memory_enabled = bool(enabled)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
