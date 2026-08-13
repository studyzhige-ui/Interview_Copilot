"""Destructive Conversation lifecycle with preview, fence, and reconciliation.

This is the single Application Service used by ordinary Conversation and
PersistentTask deletion.  It does not create a generic lifecycle registry:
owner-specific callers remain responsible for their own aggregate (for
example a PersistentTask first fences its scheduler definition).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_attachment import (
    ConversationAttachmentDraft,
    ConversationAttachmentRef,
)
from app.models.conversation_deletion_receipt import ConversationDeletionReceipt
from app.services.chat.conversation_deletion_resource_service import (
    receipt_resource_identities_for_call,
)
from app.models.conversation_turn import ConversationTurn
from app.models.interview_source import InterviewSourceRef
from app.models.model_dispatch import AgentModelDispatch
from app.models.pending_submission import PendingSubmission
from app.schemas.conversation_lifecycle import (
    ConversationDeleteResult,
    ConversationDeletionImpact,
)


class ConversationDeletionError(ValueError):
    """Base lifecycle command error."""


class ConversationDeletionNotFoundError(ConversationDeletionError):
    """The Conversation is missing or belongs to another user."""


class ConversationDeletionConflictError(ConversationDeletionError):
    """The preview or aggregate owner changed before confirmation."""


@dataclass(frozen=True)
class ConversationDeletionExecution:
    result: ConversationDeleteResult
    ingestion_task_ids: tuple[str, ...]
    cancelled_turn_id: str | None


_RECONCILE_EFFECTS = frozenset({"external_write", "client_action", "unknown"})
_UNRESOLVED_STATUSES = frozenset({"running", "unknown", "partial"})
_CORRELATION_KEYS = frozenset(
    {
        "receipt_id",
        "provider_receipt_id",
        "request_id",
        "operation_id",
        "external_id",
        "resource_id",
        "idempotency_key",
        "provider",
        "status",
    }
)
_CORRELATION_CONTAINERS = frozenset({"receipt", "provider_receipt", "read_back"})


def preview_conversation_deletion(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    allow_persistent_task: bool = False,
) -> ConversationDeletionImpact:
    conversation = _owned_conversation(
        db,
        user_pk=user_pk,
        conversation_id=conversation_id,
        for_update=False,
    )
    if conversation.type == "persistent_task" and not allow_persistent_task:
        raise ConversationDeletionConflictError(
            "Delete the PersistentTask that owns this Conversation"
        )
    return _impact(db, conversation)


def delete_conversation(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    confirmation_token: str,
    confirm_conversation_id: str,
    allow_persistent_task: bool = False,
) -> ConversationDeletionExecution:
    """Fence execution, preserve unresolved receipt correlation, then delete.

    The caller commits.  Only after commit should it request cancellation of
    the in-process worker and revoke ingestion jobs returned by this command.
    """

    conversation = _owned_conversation(
        db,
        user_pk=user_pk,
        conversation_id=conversation_id,
        for_update=True,
    )
    if conversation.type == "persistent_task" and not allow_persistent_task:
        raise ConversationDeletionConflictError(
            "Delete the PersistentTask that owns this Conversation"
        )
    if confirm_conversation_id.strip() != conversation.id:
        raise ConversationDeletionConflictError("conversation confirmation mismatch")
    current_impact = _impact(db, conversation)
    if not _constant_time_equal(confirmation_token, current_impact.confirmation_token):
        raise ConversationDeletionConflictError(
            "Conversation changed after deletion preview; review the impact again"
        )

    now = utc_now()
    # archived_at is the existing user-visibility gate.  The row is removed in
    # this same transaction; setting it first documents and fences the command
    # without adding a second Conversation lifecycle state.
    conversation.archived_at = conversation.archived_at or now
    db.add(conversation)

    turns = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.conversation_id == conversation.id,
            ConversationTurn.user_id == user_pk,
        )
        .with_for_update()
        .all()
    )
    turn_ids = [turn.id for turn in turns]
    calls = (
        db.query(AgentToolCall)
        .filter(
            AgentToolCall.session_id == conversation.id,
            AgentToolCall.user_id == user_pk,
        )
        .with_for_update()
        .all()
    )
    cancelled_turn_id: str | None = None
    active = next(
        (turn for turn in turns if turn.id == conversation.active_turn_id),
        None,
    )
    if active is not None and active.status in {"pending", "running", "waiting"}:
        cancelled_turn_id = active.id
        active.dispatch_generation = int(active.dispatch_generation or 1) + 1
        active.status = "cancelled"
        active.waiting_reason = None
        active.interrupt_submission_id = None
        active.interrupt_submission_version = None
        active.error = "conversation_deleted_by_user"
        active.owner_id = None
        active.heartbeat_at = None
        active.completed_at = now
        from app.services.chat.agent_task_service import (
            freeze_agent_task_for_terminal_turn,
        )

        freeze_agent_task_for_terminal_turn(db, turn_id=active.id)
        db.add(active)
    conversation.active_turn_id = None

    if turn_ids:
        model_dispatches = (
            db.query(AgentModelDispatch)
            .filter(
                AgentModelDispatch.turn_id.in_(turn_ids),
                AgentModelDispatch.status == "running",
            )
            .with_for_update()
            .all()
        )
        for dispatch in model_dispatches:
            dispatch.status = "cancelled"
            dispatch.error_code = "conversation_deleted"
            dispatch.completed_at = now
            dispatch.updated_at = now
            db.add(dispatch)

    tombstone_count = 0
    for call in calls:
        prior_correlation = _minimal_correlation(call.result_json)
        if call.status == "running":
            if call.effect in _RECONCILE_EFFECTS:
                call.status = "unknown"
                call.result_json = {
                    "error": "tool_outcome_unknown",
                    "reason": "conversation_deleted_requires_reconcile",
                }
                call.error = "tool_outcome_unknown"
            else:
                call.status = "cancelled"
                call.result_json = {
                    "error": "tool_cancelled",
                    "reason": "conversation_deleted",
                }
                call.error = "tool_cancelled"
            call.completed_at = now
            db.add(call)
        if _requires_receipt_tombstone(call):
            _upsert_receipt_tombstone(
                db,
                call,
                now=now,
                correlation=prior_correlation,
            )
            tombstone_count += 1

    from app.services.chat.attachment_source_service import (
        cleanup_conversation_attachment_scope,
    )

    cleanup = cleanup_conversation_attachment_scope(
        db,
        user_pk=user_pk,
        conversation_id=conversation.id,
    )
    from app.services.agent_memory_service import invalidate_sources_for_conversation

    invalidate_sources_for_conversation(
        db,
        user_pk=user_pk,
        conversation_id=conversation.id,
    )

    # Mirror the PostgreSQL cascade in SQLite tests.  Removing canonical Tool
    # rows is also important for the late ``_finish`` path: it must settle the
    # minimal receipt tombstone, never reconstruct deleted Tool History.
    db.query(AgentToolCall).filter(AgentToolCall.session_id == conversation.id).delete(
        synchronize_session="fetch"
    )
    if turn_ids:
        db.query(AgentModelDispatch).filter(
            AgentModelDispatch.turn_id.in_(turn_ids)
        ).delete(synchronize_session="fetch")
        db.query(ConversationTurn).filter(ConversationTurn.id.in_(turn_ids)).delete(
            synchronize_session="fetch"
        )
    db.query(ConversationMessage).filter(
        ConversationMessage.conversation_id == conversation.id
    ).delete(synchronize_session=False)
    deleted_id = conversation.id
    db.delete(conversation)
    db.flush()
    return ConversationDeletionExecution(
        result=ConversationDeleteResult(
            conversation_id=deleted_id,
            cancelled_turn_id=cancelled_turn_id,
            deleted_pending_submissions=cleanup.pending_submissions,
            deleted_attachment_refs=cleanup.attachment_refs,
            deleted_file_assets=cleanup.deleted_file_assets,
            preserved_debrief_sources=cleanup.preserved_promoted_projections,
            receipt_tombstones=tombstone_count,
        ),
        ingestion_task_ids=cleanup.ingestion_task_ids,
        cancelled_turn_id=cancelled_turn_id,
    )


def settle_deleted_conversation_receipt(
    db: Session,
    *,
    user_pk: int,
    deleted_conversation_id: str,
    turn_id: str,
    call_id: str,
    status: str,
    correlation: dict[str, Any] | None = None,
) -> bool:
    """Provider reconciler terminalizes a tombstone without restoring History."""

    if status not in {"completed", "failed", "cancelled"}:
        raise ConversationDeletionConflictError("receipt status is not terminal")
    row = (
        db.query(ConversationDeletionReceipt)
        .filter(
            ConversationDeletionReceipt.user_id == user_pk,
            ConversationDeletionReceipt.deleted_conversation_id
            == deleted_conversation_id,
            ConversationDeletionReceipt.turn_id == turn_id,
            ConversationDeletionReceipt.call_id == call_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        return False
    row.status = status
    row.correlation_json = _minimal_correlation(correlation or row.correlation_json)
    row.resolved_at = utc_now()
    # The ordinary retention cleanup may now remove the row.  No Conversation,
    # prompt, or Tool History is reconstructed.
    row.retain_until = row.resolved_at
    db.add(row)
    db.flush()
    return True


def purge_expired_conversation_deletion_receipts(
    db: Session,
    *,
    due_at=None,
    limit: int = 500,
) -> int:
    """Boundedly purge only receipt tombstones whose retention has expired.

    This is deliberately owner-specific lifecycle maintenance, not a generic
    tombstone registry.  Unknown receipts remain for their bounded safety
    window; resolved receipts become eligible immediately via ``retain_until``.
    """

    cutoff = due_at or utc_now()
    bounded_limit = min(max(int(limit), 1), 1_000)
    rows = (
        db.query(ConversationDeletionReceipt)
        .filter(
            ConversationDeletionReceipt.retain_until <= cutoff,
        )
        .order_by(
            ConversationDeletionReceipt.retain_until.asc(),
            ConversationDeletionReceipt.id.asc(),
        )
        .limit(bounded_limit)
        .with_for_update()
        .all()
    )
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)


def _impact(db: Session, conversation: Conversation) -> ConversationDeletionImpact:
    turns = (
        db.query(ConversationTurn)
        .filter(ConversationTurn.conversation_id == conversation.id)
        .all()
    )
    active = next(
        (turn for turn in turns if turn.id == conversation.active_turn_id),
        None,
    )
    calls = (
        db.query(AgentToolCall)
        .filter(AgentToolCall.session_id == conversation.id)
        .all()
    )
    drafts = (
        db.query(ConversationAttachmentDraft)
        .filter(ConversationAttachmentDraft.conversation_id == conversation.id)
        .all()
    )
    refs = (
        db.query(ConversationAttachmentRef)
        .filter(ConversationAttachmentRef.conversation_id == conversation.id)
        .all()
    )
    asset_ids = {row.file_asset_id for row in [*drafts, *refs]}
    promoted = (
        db.query(InterviewSourceRef)
        .filter(
            InterviewSourceRef.user_id == conversation.user_id,
            InterviewSourceRef.origin_conversation_id == conversation.id,
            InterviewSourceRef.removed_at.is_(None),
        )
        .all()
    )
    promoted_asset_ids = {row.file_asset_id for row in promoted}
    unresolved = [call for call in calls if _requires_receipt_tombstone(call)]
    completed_external = [
        call
        for call in calls
        if call.effect in _RECONCILE_EFFECTS and call.status == "completed"
    ]
    pending_count = (
        db.query(PendingSubmission)
        .filter(PendingSubmission.conversation_id == conversation.id)
        .count()
    )
    message_count = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation.id)
        .count()
    )
    fingerprint_payload = {
        "conversation_id": conversation.id,
        "updated_at": conversation.updated_at.isoformat()
        if conversation.updated_at
        else None,
        "active_turn": [
            active.id if active else None,
            active.status if active else None,
            int(active.dispatch_generation or 1) if active else None,
        ],
        "turns": sorted(
            (
                turn.id,
                turn.status,
                int(turn.dispatch_generation or 1),
            )
            for turn in turns
        ),
        "pending": pending_count,
        "messages": message_count,
        "drafts": sorted(row.id for row in drafts),
        "refs": sorted((row.id, row.removed_at is not None) for row in refs),
        "promoted": sorted(row.id for row in promoted),
        "unresolved": sorted(
            (row.turn_id, row.call_id, row.status) for row in unresolved
        ),
        "calls": sorted(
            (
                row.turn_id,
                row.call_id,
                row.effect,
                row.status,
                int(row.dispatch_generation or 1),
            )
            for row in calls
        ),
    }
    token = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    disclosures = [
        f"将撤回并删除 {pending_count} 条待发送输入及其草稿引用。",
        f"将删除 {message_count} 条消息和该对话的局部 Interaction Records。",
        "未晋升附件会失去本对话 scope；只由本对话持有的文件与解析投影会清理。",
        f"已晋升的本次复盘资料保留 {len(promoted)} 项，不随原对话删除。",
        "已经发生的外部动作不会回滚。",
    ]
    if unresolved:
        disclosures.append(
            f"仍有 {len(unresolved)} 个外部调用未结算；仅保留脱敏 receipt correlation tombstone 直到 reconcile。"
        )
    return ConversationDeletionImpact(
        conversation_id=conversation.id,
        conversation_type=conversation.type,
        title=conversation.title or "该对话",
        active_turn_id=active.id if active else None,
        active_turn_status=active.status if active else None,
        pending_submission_count=pending_count,
        message_count=message_count,
        local_attachment_count=len(drafts) + len(refs),
        unpromoted_file_count=len(asset_ids.difference(promoted_asset_ids)),
        preserved_debrief_source_count=len(promoted),
        unresolved_external_call_count=len(unresolved),
        completed_external_action_count=len(completed_external),
        confirmation_token=token,
        disclosures=disclosures,
    )


def _owned_conversation(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    for_update: bool,
) -> Conversation:
    query = db.query(Conversation).filter(
        Conversation.id == conversation_id.strip(),
        Conversation.user_id == user_pk,
    )
    if for_update:
        query = query.with_for_update().populate_existing()
    conversation = query.one_or_none()
    if conversation is None:
        raise ConversationDeletionNotFoundError(conversation_id)
    return conversation


def _requires_receipt_tombstone(call: AgentToolCall) -> bool:
    if call.effect not in _RECONCILE_EFFECTS:
        return False
    if call.status in _UNRESOLVED_STATUSES:
        return True
    result = call.result_json if isinstance(call.result_json, dict) else {}
    return bool(result.get("requires_reconcile"))


def _upsert_receipt_tombstone(
    db: Session,
    call: AgentToolCall,
    *,
    now,
    correlation: dict[str, Any] | None = None,
) -> ConversationDeletionReceipt:
    row = (
        db.query(ConversationDeletionReceipt)
        .filter(
            ConversationDeletionReceipt.deleted_conversation_id == call.session_id,
            ConversationDeletionReceipt.turn_id == call.turn_id,
            ConversationDeletionReceipt.call_id == call.call_id,
        )
        .one_or_none()
    )
    safe_correlation = correlation or _minimal_correlation(call.result_json)
    if row is None:
        row = ConversationDeletionReceipt(
            resource_identities_json=receipt_resource_identities_for_call(call),
            user_id=call.user_id,
            deleted_conversation_id=call.session_id,
            turn_id=call.turn_id,
            call_id=call.call_id,
            tool_name=call.tool_name,
            effect=call.effect,
            dispatch_generation=int(call.dispatch_generation or 1),
            status="unknown",
            correlation_json=safe_correlation,
            reason="conversation_deleted",
            # A bounded safety window; provider-specific reconciliation may
            # resolve earlier, after which normal cleanup can remove it.
            retain_until=now + timedelta(days=30),
        )
    elif safe_correlation:
        row.correlation_json = safe_correlation
    db.add(row)
    db.flush()
    return row


def _minimal_correlation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).lower()
        if normalized in _CORRELATION_KEYS and isinstance(
            item, (str, int, float, bool)
        ):
            result[normalized] = str(item)[:256]
        elif normalized in _CORRELATION_CONTAINERS and isinstance(item, dict):
            nested = _minimal_correlation(item)
            if nested:
                result[normalized] = nested
    return result


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest((left or "").strip(), right)


__all__ = [
    "ConversationDeletionConflictError",
    "ConversationDeletionError",
    "ConversationDeletionExecution",
    "ConversationDeletionNotFoundError",
    "delete_conversation",
    "purge_expired_conversation_deletion_receipts",
    "preview_conversation_deletion",
    "settle_deleted_conversation_receipt",
]
