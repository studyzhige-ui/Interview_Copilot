"""Wake the same Conversation Turn after attachment parsing becomes terminal.

The parsing worker owns only the rebuildable ``KnowledgeDocument`` projection.
This service follows immutable ``ConversationAttachmentRef`` rows back to the
waiting Turn; it does not admit a new message, create a new ref, or duplicate
the attachment identity.
"""

from __future__ import annotations

import logging

from app.core.async_runtime import run_async
from app.db.database import SessionLocal
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.conversation_turn import ConversationTurn
from app.models.knowledge import KnowledgeDocument

logger = logging.getLogger(__name__)

ATTACHMENT_PARSING_WAIT_REASON = "attachment_parsing"


def _turn_parsing_is_ready(db, turn_id: str) -> bool:
    has_claimed_source = bool(
        db.query(ConversationAttachmentRef.id)
        .filter(ConversationAttachmentRef.turn_id == turn_id)
        .first()
    )
    rows = (
        db.query(ConversationAttachmentRef.id, KnowledgeDocument.status)
        .outerjoin(
            KnowledgeDocument,
            KnowledgeDocument.id == ConversationAttachmentRef.source_document_id,
        )
        .filter(
            ConversationAttachmentRef.turn_id == turn_id,
            ConversationAttachmentRef.removed_at.is_(None),
        )
        .all()
    )
    # A failed or missing source stays on the same waiting Turn so the user can
    # retry it under the frozen identity (or cancel the Turn). Resuming a failed
    # projection would immediately terminalize the Turn before retry is possible.
    return has_claimed_source and all(status == "ready" for _, status in rows)


def _reset_events(turn_id: str) -> None:
    from app.services.chat.turn_event_buffer import turn_event_buffer

    run_async(turn_event_buffer.reset(turn_id))


def _resume_candidate(db, *, turn_id: str, user_id: int) -> bool:
    if not _turn_parsing_is_ready(db, turn_id):
        return False

    from app.services.chat.turn_executor import (
        fail_pending_turn,
        resume_waiting_turn,
        schedule_turn,
    )

    generation = resume_waiting_turn(
        db,
        turn_id,
        user_id,
        expected_reason=ATTACHMENT_PARSING_WAIT_REASON,
    )
    if generation is None:
        return False
    try:
        _reset_events(turn_id)
        schedule_turn(turn_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Could not dispatch attachment-resumed Turn %s (generation %s)",
            turn_id,
            generation,
        )
        fail_pending_turn(
            db,
            turn_id,
            user_id,
            "附件解析已结束，但后台恢复队列暂时不可用。",
        )
        return False
    return True


def wake_attachment_turn_if_terminal(turn_id: str) -> bool:
    """Close the ingestion-before-wait race for one newly waiting Turn.

    ``turn_executor._wait`` calls this *after* committing the
    ``attachment_parsing`` reason. If ingestion notified just before that
    commit, this second check observes the already-terminal projection; if the
    ingestion callback wins instead, the same CAS makes this call a no-op.
    """

    normalized_turn_id = (turn_id or "").strip()
    if not normalized_turn_id:
        return False
    db = SessionLocal()
    try:
        candidate = (
            db.query(ConversationTurn.id, ConversationTurn.user_id)
            .filter(
                ConversationTurn.id == normalized_turn_id,
                ConversationTurn.status == "waiting",
                ConversationTurn.waiting_reason == ATTACHMENT_PARSING_WAIT_REASON,
            )
            .one_or_none()
        )
        if candidate is None:
            return False
        return _resume_candidate(
            db,
            turn_id=candidate.id,
            user_id=candidate.user_id,
        )
    finally:
        db.close()


def recover_terminal_attachment_turns(*, limit: int = 100) -> list[str]:
    """Retry durable ready-source wakeups after a callback/process failure.

    This is a bounded repair read over the real waiting Turn state, not another
    task model. The existing conversation/Turn CAS keeps it safe to invoke from
    the normal background-maintenance pass.
    """

    bounded_limit = max(1, min(int(limit), 1000))
    db = SessionLocal()
    resumed: list[str] = []
    try:
        candidates = (
            db.query(ConversationTurn.id, ConversationTurn.user_id)
            .filter(
                ConversationTurn.status == "waiting",
                ConversationTurn.waiting_reason == ATTACHMENT_PARSING_WAIT_REASON,
            )
            .order_by(ConversationTurn.created_at.asc())
            .limit(bounded_limit)
            .all()
        )
        for turn_id, user_id in candidates:
            if _resume_candidate(db, turn_id=turn_id, user_id=user_id):
                resumed.append(turn_id)
        return resumed
    finally:
        db.close()


def wake_attachment_turns_for_projection(document_id: str) -> list[str]:
    """Idempotently resume attachment-waiting Turns affected by a projection.

    A Turn resumes only after *all* of its frozen attachment projections are
    ready. Failed or missing projections keep the same Turn waiting while the
    typed source endpoint exposes retry/cancel handling. The existing Turn CAS
    and dispatch generation fence deduplicate notifications.
    """

    normalized_document_id = (document_id or "").strip()
    if not normalized_document_id:
        return []

    db = SessionLocal()
    resumed: list[str] = []
    try:
        candidates = (
            db.query(
                ConversationTurn.id,
                ConversationTurn.user_id,
            )
            .join(
                ConversationAttachmentRef,
                ConversationAttachmentRef.turn_id == ConversationTurn.id,
            )
            .filter(
                ConversationAttachmentRef.source_document_id == normalized_document_id,
                ConversationAttachmentRef.removed_at.is_(None),
                ConversationTurn.status == "waiting",
                ConversationTurn.waiting_reason == ATTACHMENT_PARSING_WAIT_REASON,
            )
            .distinct()
            .all()
        )
        for turn_id, user_id in candidates:
            if _resume_candidate(db, turn_id=turn_id, user_id=user_id):
                resumed.append(turn_id)
        return resumed
    finally:
        db.close()


__all__ = [
    "ATTACHMENT_PARSING_WAIT_REASON",
    "recover_terminal_attachment_turns",
    "wake_attachment_turn_if_terminal",
    "wake_attachment_turns_for_projection",
]
