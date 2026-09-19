"""Exact CurrentTurnAnchor source checks shared by product Tool adapters."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.chat import ConversationMessage
from app.models.conversation_turn import ConversationTurn


class CurrentTurnSourceError(ValueError):
    """A proposed command is not sourced by this admitted user Turn."""


def require_current_turn_user_message(
    db: Session,
    *,
    user_pk: int,
    turn_id: str | None,
    conversation_id: str | None,
    message_id: int,
) -> ConversationMessage:
    if user_pk <= 0 or not turn_id or not conversation_id:
        raise CurrentTurnSourceError("current_turn_source_unavailable")
    turn = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.id == turn_id,
            ConversationTurn.user_id == user_pk,
            ConversationTurn.conversation_id == conversation_id,
        )
        .one_or_none()
    )
    if turn is None or turn.user_message_seq is None:
        raise CurrentTurnSourceError("current_turn_source_unavailable")
    message = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.id == int(message_id),
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.seq == turn.user_message_seq,
        )
        .one_or_none()
    )
    if message is None or str(message.role).casefold() != "user":
        raise CurrentTurnSourceError(
            "confirmation_message_is_not_current_turn_user_message"
        )
    return message


__all__ = ["CurrentTurnSourceError", "require_current_turn_user_message"]
