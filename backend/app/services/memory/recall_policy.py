"""Resolve "is the GLOBAL memory toggle on?" for a chat session.

Semantics (Stage-H clarification): this is the **cross-session memory**
switch — same scope as Claude Code's ``isAutoMemoryEnabled``. When off:

  * The v3 memory bundle (user_profile + knowledge / strategy / habit
    docs) is NOT injected into the LLM prompt.
  * The planner doesn't see the user's memory inventory either, so it
    can't request body loads.
  * Session-local context (recent_turns, session_state, [Record Context]
    for debrief sessions) STILL loads — those are per-conversation
    working context, not "memory".
  * User-facing UI can still read the docs directly from the DB — the
    toggle only gates LLM INJECTION, not storage.

Two tiers of preference:

  1. **Per-session override** — stored as ``global_memory_enabled``
     (bool) inside ``chat_sessions.session_state``. Set by the toggle
     next to the "agent" button in the chat header. Takes precedence
     whenever present (even when explicitly set to False).
  2. **Per-user default** — ``users.global_memory_enabled`` column.
     Toggled in the 个人中心 preferences page. Used when the session-
     level value is unset.

If both are missing or unreadable, the policy falls back to ``False``
— opt-in by design. A failed DB lookup also returns False so a
transient outage degrades safely (skip injection, keep answering)
instead of accidentally leaking memory contents.

Back-compat read shim: rows persisted before Stage-H carry the legacy
JSON key ``memory_recall_enabled`` in their session_state. We read
either key; new writes always use the new key. The DB column was
renamed by alembic 0007 (``memory_recall_default`` →
``global_memory_enabled``).

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


# Canonical key used by new writes. Old rows may still carry the
# legacy ``memory_recall_enabled`` key — the read path falls back to
# it so we don't need a JSON migration for in-flight sessions.
_STATE_KEY = "global_memory_enabled"
_LEGACY_STATE_KEY = "memory_recall_enabled"


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


def is_global_memory_enabled_for_session(session_id: str, user_id: str) -> bool:
    """Return True iff the GLOBAL (cross-session) memory bundle should
    be injected into the LLM prompt for this turn.

    Resolution order (first hit wins):
      session.session_state[global_memory_enabled or memory_recall_enabled]
      → user.global_memory_enabled → False
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
                    # Prefer the canonical key; fall back to the legacy
                    # one so pre-Stage-H sessions still honour their
                    # stored choice.
                    raw = state.get(_STATE_KEY)
                    if raw is None:
                        raw = state.get(_LEGACY_STATE_KEY)
                    v = _coerce_bool(raw)
                    if v is not None:
                        return v
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning(
                    "recall_policy: malformed session_state for %s: %s",
                    session_id, exc,
                )

        # User-level default.
        user_default = (
            db.query(User.global_memory_enabled)
            .filter(User.username == user_id)
            .first()
        )
        if user_default is not None and user_default[0] is not None:
            return bool(user_default[0])

        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "recall_policy: lookup failed for %s/%s: %s",
            session_id, user_id, exc,
        )
        return False
    finally:
        db.close()


def set_session_global_memory(session_id: str, user_id: str, enabled: bool) -> None:
    """Persist a per-session override into ``session_state`` JSON.

    Reads the existing blob, sets ``global_memory_enabled``, writes back.
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
        # Tidy: drop the legacy key when we own the write — no point
        # carrying both.
        state.pop(_LEGACY_STATE_KEY, None)
        row.session_state = json.dumps(state, ensure_ascii=False, sort_keys=True)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# NB: a ``set_user_global_memory_default`` helper used to live here as a
# wrapper around ``users.global_memory_enabled``, but every caller (just
# ``PATCH /auth/me``) writes the column directly via SQLAlchemy on the
# already-loaded ``current_user`` row — going through a fresh DB session
# in a wrapper was pure indirection. Deleted in the Phase-H audit
# cleanup; if a future caller actually needs the policy module to own the
# write (symmetric with ``set_session_global_memory``), reintroduce it.


__all__ = [
    "is_global_memory_enabled_for_session",
    "set_session_global_memory",
]
