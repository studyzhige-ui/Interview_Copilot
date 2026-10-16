"""Checkpoint + transcript-tail replay with conversation and dispatch fencing."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4
from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.chat import Conversation
from app.models.context_checkpoint import ContextCheckpoint
from app.models.conversation_turn import ConversationTurn
from app.conversation.context_window import persistent_history


_FORMAT_VERSION = 2


def load(conversation_id: str, *, scope: str = "") -> dict | None:
    with SessionLocal() as db:
        row = db.get(ContextCheckpoint, (conversation_id, scope))
        if row is None:
            return None
        state = deepcopy(row.state)
        compatible = state.get("format_version") == _FORMAT_VERSION
        # Old summaries may contain revoked memory/guidance. Filtering their
        # visible slots cannot remove paraphrases; replay the canonical history
        # instead, preserving the CAS version so stale writers still lose.
        return {
            "version": row.version,
            "through_seq": row.through_seq if compatible else 0,
            "window_id": row.window_id,
            "state": state if compatible else {"messages": [], "covered_call_ids": []},
        }


def save(
    conversation_id: str,
    *,
    expected_version: int,
    through_seq: int,
    state: dict,
    scope: str = "",
    turn_id: str | None = None,
    dispatch_generation: int = 0,
    replace: bool = False,
) -> dict | None:
    """Short transaction only after generation; stale writers cannot advance."""
    with SessionLocal() as db:
        # Match ordinary turn admission's conversation lock. No network under lock.
        conversation = db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .with_for_update()
        ).scalar_one_or_none()
        if conversation is None:
            return None
        if turn_id:
            turn = db.get(ConversationTurn, turn_id, with_for_update=True)
            if (
                turn is None
                or turn.conversation_id != conversation_id
                or turn.user_id != conversation.user_id
                or turn.status != "running"
                or turn.cancel_requested
                or turn.dispatch_generation != dispatch_generation
                or conversation.active_turn_id not in {None, turn_id}
            ):
                return None
        elif conversation.active_turn_id:
            return None
        row = db.get(ContextCheckpoint, (conversation_id, scope))
        if (row.version if row else 0) != expected_version:
            return None
        if row and through_seq < row.through_seq:
            return None
        previous = row.window_id if row else None
        if row is None:
            row = ContextCheckpoint(conversation_id=conversation_id, scope=scope)
            db.add(row)
        row.version = expected_version + 1
        row.through_seq = through_seq
        row.dispatch_generation = dispatch_generation
        if previous is None or replace:
            row.previous_window_id = previous
            row.window_id = str(uuid4())
        row.state = {
            **deepcopy(state),
            "messages": deepcopy(persistent_history(state.get("messages", []))),
            "format_version": _FORMAT_VERSION,
        }
        row.updated_at = utc_now()
        result = {
            "version": row.version,
            "through_seq": through_seq,
            "window_id": row.window_id,
            "state": deepcopy(row.state),
        }
        db.commit()
        return result
