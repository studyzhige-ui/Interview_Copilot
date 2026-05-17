"""Resolve "should we recall past memories?" for a chat session.

Memory recall (the vector search over past ``interview_fact`` items that
gets injected into the LLM prompt) is opt-in.  Two tiers of preference:

  1. **Per-session override** — stored as ``memory_recall_enabled`` (bool)
     inside ``chat_sessions.session_state``. Set by the toggle next to
     the "agent" button in the chat header. Takes precedence whenever
     present (even when explicitly set to False).
  2. **Per-user default** — ``users.memory_recall_default`` column.
     Toggled in the 个人中心 preferences page. Used when the session-
     level value is unset.

If both are missing or unreadable (e.g. brand new session, JSON parse
error), the policy falls back to ``False`` — opt-in by design. A failed
DB lookup also returns False so a transient outage degrades safely
(skip recall, keep answering) instead of leaking memory contents.

Keep this module tiny and dependency-free so the QA pipeline can import
it without dragging in heavy retrieval/embedding modules.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.chat import ChatSession
from app.models.user import User

logger = logging.getLogger(__name__)


_STATE_KEY = "memory_recall_enabled"


def _coerce_bool(v: Any) -> bool | None:
    """Tolerant truthy/falsy decoder so the field can be set via JSON
    patch with either ``true`` / ``"true"`` / ``1`` etc. Returns None
    when the value isn't decidable (so the caller falls through to the
    next tier instead of guessing).
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "1", "yes", "on"}:
            return True
        if s in {"false", "0", "no", "off"}:
            return False
    return None


def recall_enabled_for_session(session_id: str, user_id: str) -> bool:
    """Return True iff memory recall should run for this turn.

    Resolution order (first hit wins):
      session.session_state[memory_recall_enabled] → user.memory_recall_default → False
    """
    db: Session = SessionLocal()
    try:
        # Session-level override.
        row = (
            db.query(ChatSession.session_state)
            .filter(ChatSession.id == session_id)
            .first()
        )
        if row and row[0]:
            try:
                state = json.loads(row[0])
                if isinstance(state, dict):
                    v = _coerce_bool(state.get(_STATE_KEY))
                    if v is not None:
                        return v
            except (json.JSONDecodeError, TypeError) as exc:
                # Garbled session_state JSON is non-fatal — fall through.
                logger.warning(
                    "recall_policy: malformed session_state for %s: %s",
                    session_id, exc,
                )

        # User-level default. We look up by username (the JWT subject)
        # because ``user_id`` in chat code is the username, not the
        # numeric id.
        user_default = (
            db.query(User.memory_recall_default)
            .filter(User.username == user_id)
            .first()
        )
        if user_default is not None and user_default[0] is not None:
            return bool(user_default[0])

        return False
    except Exception as exc:  # noqa: BLE001
        # Degrade safely on DB errors — never blow up the chat turn.
        logger.warning("recall_policy: lookup failed for %s/%s: %s",
                       session_id, user_id, exc)
        return False
    finally:
        db.close()


def set_session_recall(session_id: str, user_id: str, enabled: bool) -> None:
    """Persist a per-session override into ``session_state`` JSON.

    Reads the existing blob, sets ``memory_recall_enabled``, writes back.
    No-op (without raising) when the session doesn't exist or isn't owned
    by ``user_id`` — the API layer enforces ownership before calling
    this; this is the safety net.
    """
    db: Session = SessionLocal()
    try:
        row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if row is None or row.user_id != user_id:
            return
        raw = row.session_state or "{}"
        try:
            state = json.loads(raw)
            if not isinstance(state, dict):
                state = {}
        except json.JSONDecodeError:
            state = {}
        state[_STATE_KEY] = bool(enabled)
        row.session_state = json.dumps(state, ensure_ascii=False, sort_keys=True)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_user_default(user_id: str, enabled: bool) -> None:
    """Update the per-user default (``users.memory_recall_default``).

    ``user_id`` is the username (consistent with the rest of the chat
    code paths). No-op for missing users.
    """
    db: Session = SessionLocal()
    try:
        row = db.query(User).filter(User.username == user_id).first()
        if row is None:
            return
        row.memory_recall_default = bool(enabled)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


__all__ = [
    "recall_enabled_for_session",
    "set_session_recall",
    "set_user_default",
]
