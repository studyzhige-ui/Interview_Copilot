"""One locked FIFO admission implementation, shared by user and automation."""

from __future__ import annotations
import json
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.types import utc_now
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.pending_submission import PendingSubmission
from app.conversation.application.attachment_ingress_service import (
    AttachmentIngressError,
)
from app.conversation.application.attachment_ingress_service import (
    attachment_ref_snapshot,
)
from app.conversation.application.attachment_ingress_service import (
    claim_attachment_drafts,
)
from app.conversation.application.attachment_ingress_service import (
    preflight_attachment_drafts,
)
from app.conversation.application.product_object_reference import (
    ProductObjectReferenceError,
)
from app.conversation.application.product_object_reference import (
    ProductObjectReferenceUnavailableError,
)
from app.conversation.application.product_object_reference import (
    ResolvedProductObjectReference,
)
from app.conversation.application.product_object_reference import UNAVAILABLE_MESSAGE
from app.conversation.application.product_object_reference import (
    preflight_product_object_references,
)


def _active_turn_locked(
    db: Session, conversation: Conversation
) -> ConversationTurn | None:
    """Return the live active turn, repairing a stale terminal pointer."""
    if not conversation.active_turn_id:
        return None
    active = db.get(ConversationTurn, conversation.active_turn_id)
    if active is not None and active.status not in {
        "completed",
        "blocked",
        "failed",
        "cancelled",
    }:
        return active
    conversation.active_turn_id = None
    return None


def _submission_matches(
    row: PendingSubmission,
    *,
    user_id: int,
    conversation_id: str,
    version: int,
    mode: str,
    execution_mode: str,
    message: str,
    question_indexes: list[int],
    attachments: list[dict],
    object_references: list[dict],
    source_client_id: str | None,
) -> bool:
    return (
        row.user_id == user_id
        and row.conversation_id == conversation_id
        and row.version == version
        and row.mode == mode
        and row.execution_mode == execution_mode
        and row.message == message
        and list(row.question_indexes_json or []) == question_indexes
        and list(row.attachments_json or []) == attachments
        and list(row.object_references_json or []) == object_references
        and row.source_client_id == source_client_id
    )


def _create_turn_from_submission_locked(
    db: Session,
    conversation: Conversation,
    submission: PendingSubmission,
    resolved_object_references: list[ResolvedProductObjectReference] | None = None,
) -> ConversationTurn:
    """Claim one pending ingress row and atomically create its history/turn."""
    if submission.status != "pending" or _active_turn_locked(db, conversation):
        raise RuntimeError("submission is not admissible")

    max_seq = (
        db.query(func.max(ConversationMessage.seq))
        .filter(ConversationMessage.conversation_id == conversation.id)
        .scalar()
    )
    user_message_seq = (max_seq or 0) + 1
    row = ConversationTurn(
        conversation_id=conversation.id,
        user_id=submission.user_id,
        submission_id=submission.id,
        mode=submission.mode,
        execution_mode=submission.execution_mode,
        message=submission.message,
        question_indexes_json=list(submission.question_indexes_json or []),
        attachments_json=[],
        object_references_json=list(submission.object_references_json or []),
        user_message_seq=user_message_seq,
        status="pending",
    )
    db.add(row)
    db.flush()
    refs = claim_attachment_drafts(
        db,
        user_pk=submission.user_id,
        conversation_id=conversation.id,
        turn_id=row.id,
        submission_id=submission.id,
        draft_ids=[
            str(item["draft_id"])
            for item in (submission.attachments_json or [])
            if isinstance(item, dict) and item.get("draft_id")
        ],
    )
    attachment_snapshots = [attachment_ref_snapshot(ref) for ref in refs]
    row.attachments_json = attachment_snapshots
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            seq=user_message_seq,
            role="User",
            content=submission.message,
            content_blocks_json=json.dumps(
                [
                    *[
                        {
                            "type": "attachment",
                            **snapshot,
                            "title": "附件",
                            "source_kind": "conversation_attachment",
                        }
                        for snapshot in attachment_snapshots
                    ],
                    *[
                        reference.history_block()
                        for reference in (resolved_object_references or ())
                    ],
                    {"type": "text", "text": submission.message},
                ],
                ensure_ascii=False,
            ),
        )
    )
    now = utc_now()
    submission.status = "claimed"
    submission.claimed_at = now
    submission.updated_at = now
    conversation.active_turn_id = row.id
    return row


def _claim_failure_message(exc: Exception) -> str:
    """Return a stable user-facing admission failure without leaking internals."""
    if isinstance(exc, AttachmentIngressError):
        return "附件已不可用或发生变化，请编辑该消息后重试"
    if isinstance(exc, ProductObjectReferenceUnavailableError):
        return UNAVAILABLE_MESSAGE
    return "该消息暂时无法接纳，请编辑后重试"


def _claim_submission_locked(
    db: Session,
    conversation: Conversation,
    submission: PendingSubmission,
) -> ConversationTurn | None:
    """Claim exactly one row, retaining an explicit failed row on rejection.

    Attachment/version validation runs before any Turn or Interaction Record
    is written.  The locked preflight and the real claim share this transaction,
    so a rejected row can become the durable admission hold without creating
    data that would need a savepoint rollback.  Unexpected storage/runtime
    failures still propagate and roll back the caller's whole transaction.
    """
    submission.status = "pending"
    submission.error = None
    try:
        preflight_attachment_drafts(
            db,
            user_pk=submission.user_id,
            conversation_id=conversation.id,
            submission_id=submission.id,
            draft_ids=[
                str(item["draft_id"])
                for item in (submission.attachments_json or [])
                if isinstance(item, dict) and item.get("draft_id")
            ],
        )
        resolved_object_references = preflight_product_object_references(
            db,
            user_pk=submission.user_id,
            references=submission.object_references_json,
        )
    except (AttachmentIngressError, ProductObjectReferenceError) as exc:
        submission.status = "failed"
        submission.error = _claim_failure_message(exc)
        submission.updated_at = utc_now()
        return None
    return _create_turn_from_submission_locked(
        db,
        conversation,
        submission,
        resolved_object_references,
    )


def _has_retained_submission_locked(db: Session, conversation_id: str) -> bool:
    return (
        db.query(PendingSubmission.id)
        .filter(
            PendingSubmission.conversation_id == conversation_id,
            PendingSubmission.status.in_(("pending", "failed")),
        )
        .first()
        is not None
    )


def _claim_next_submission_locked(
    db: Session,
    conversation: Conversation,
) -> ConversationTurn | None:
    if _active_turn_locked(db, conversation):
        return None
    # A failed retained row is the admission hold.  It is deliberately not a
    # second object/state machine: the failed row itself is the visible gate.
    if (
        db.query(PendingSubmission.id)
        .filter(
            PendingSubmission.conversation_id == conversation.id,
            PendingSubmission.status == "failed",
        )
        .first()
        is not None
    ):
        return None
    submission = (
        db.query(PendingSubmission)
        .filter(
            PendingSubmission.conversation_id == conversation.id,
            PendingSubmission.status == "pending",
        )
        .order_by(PendingSubmission.position, PendingSubmission.id)
        .with_for_update()
        .first()
    )
    if submission is None:
        return None
    return _claim_submission_locked(db, conversation, submission)


def _claim_selected_submission_locked(
    db: Session,
    conversation: Conversation,
    *,
    submission_id: str,
    expected_version: int,
) -> ConversationTurn | None:
    """One-shot FIFO exception used only by explicit retry/interrupt."""
    if _active_turn_locked(db, conversation):
        return None
    submission = (
        db.query(PendingSubmission)
        .filter(
            PendingSubmission.id == submission_id,
            PendingSubmission.conversation_id == conversation.id,
            PendingSubmission.version == expected_version,
            PendingSubmission.status.in_(("pending", "failed")),
        )
        .with_for_update()
        .one_or_none()
    )
    if submission is None:
        return None
    return _claim_submission_locked(db, conversation, submission)
