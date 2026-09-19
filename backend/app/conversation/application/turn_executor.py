from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.conversation.events import HarnessEvent
from app.conversation.runtime_profile import runtime_profile_for_type
from app.core.config import settings
from app.core.error_messages import humanize_error
from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.pending_submission import PendingSubmission
from app.models.user import User
from app.conversation.application.chat_history_service import transcript_service
from app.conversation.application.product_object_reference import (
    ProductObjectReferenceError,
)
from app.conversation.application.product_object_reference import (
    ProductObjectReferenceUnavailableError,
)
from app.conversation.application.product_object_reference import UNAVAILABLE_MESSAGE
from app.conversation.application.product_object_reference import (
    build_product_object_context,
)
from app.conversation.application.product_object_reference import (
    normalize_product_object_references,
)
from app.conversation.application.turn_event_buffer import turn_event_buffer

from app.conversation.application.turn_admission import (
    _active_turn_locked as _active_turn_locked,
)
from app.conversation.application.turn_admission import (
    _claim_failure_message as _claim_failure_message,
)
from app.conversation.application.turn_admission import (
    _claim_next_submission_locked as _claim_next_submission_locked,
)
from app.conversation.application.turn_admission import (
    _claim_selected_submission_locked as _claim_selected_submission_locked,
)
from app.conversation.application.turn_admission import (
    _claim_submission_locked as _claim_submission_locked,
)
from app.conversation.application.turn_admission import (
    _create_turn_from_submission_locked as _create_turn_from_submission_locked,
)
from app.conversation.application.turn_admission import (
    _has_retained_submission_locked as _has_retained_submission_locked,
)
from app.conversation.application.turn_admission import (
    _submission_matches as _submission_matches,
)

logger = logging.getLogger(__name__)
_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class TurnExecution:
    id: str
    conversation_id: str
    username: str
    mode: str
    message: str
    user_pk: int = 0
    execution_mode: str = "standard"
    dispatch_generation: int = 1
    question_indexes: tuple[int, ...] = ()
    attachments: tuple[dict, ...] = ()
    object_references: tuple[dict, ...] = ()
    automation_task_id: str | None = None
    automation_user_id: int | None = None
    automation_definition_version: int | None = None
    automation_tool_names: tuple[str, ...] = ()
    automation_skill_refs: tuple[dict[str, object], ...] = ()
    automation_validation_error: str | None = None


@dataclass(frozen=True)
class AdmissionResult:
    submission_id: str
    version: int
    status: str
    turn_id: str | None
    queue_position: int | None
    should_dispatch: bool = False
    dispatch_turn_id: str | None = None
    error: str | None = None


class SubmissionConflictError(ValueError):
    pass


def admit_submission(
    db: Session,
    conversation: Conversation,
    *,
    submission_id: str,
    version: int,
    user_id: int,
    requested_mode: str | None,
    message: str,
    requested_execution_mode: str | None = None,
    question_indexes: list[int] | None = None,
    attachment_draft_ids: list[str] | None = None,
    object_references: list[dict] | None = None,
    source_client_id: str | None = None,
) -> AdmissionResult:
    """Idempotently admit or queue one ordinary Composer submission."""
    locked = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation.id,
            Conversation.user_id == user_id,
        )
        .with_for_update()
        # ``conversation`` was normally loaded earlier by the API, so it is
        # already present in this Session's identity map. Force the locked
        # SELECT to refresh it; otherwise concurrent waiters can keep seeing
        # the pre-lock ``active_turn_id=None`` snapshot and all create a turn.
        .populate_existing()
        .one()
    )
    mode = runtime_profile_for_type(locked.type).resolve_mode(
        locked.mode, requested_mode
    )
    if requested_execution_mode is not None and requested_execution_mode not in {
        "standard",
        "auto",
    }:
        raise SubmissionConflictError("unsupported execution mode")
    normalized_indexes = list(dict.fromkeys(question_indexes or []))
    attachment_snapshots = [
        {"draft_id": draft_id} for draft_id in dict.fromkeys(attachment_draft_ids or [])
    ]
    try:
        normalized_object_references = normalize_product_object_references(
            object_references
        )
    except ProductObjectReferenceError as exc:
        raise SubmissionConflictError(str(exc)) from exc
    existing = db.get(PendingSubmission, submission_id)
    # Conversation is authoritative for a new admission. The request field is
    # accepted for wire compatibility only; a stale device cannot overwrite or
    # select a stale policy snapshot. An idempotent retry keeps the snapshot
    # already stored on its PendingSubmission even if the Conversation changed.
    execution_mode = (
        existing.execution_mode
        if existing is not None
        else (locked.execution_mode or "standard")
    )
    if existing is not None:
        if not _submission_matches(
            existing,
            user_id=user_id,
            conversation_id=locked.id,
            version=version,
            mode=mode,
            execution_mode=execution_mode,
            message=message,
            question_indexes=normalized_indexes,
            attachments=attachment_snapshots,
            object_references=normalized_object_references,
            source_client_id=source_client_id,
        ):
            db.rollback()
            raise SubmissionConflictError(
                "submission identity or version was reused for different input"
            )
        if existing.status == "claimed":
            turn_id = (
                db.query(ConversationTurn.id)
                .filter(ConversationTurn.submission_id == existing.id)
                .scalar()
            )
            result = AdmissionResult(
                submission_id=existing.id,
                version=existing.version,
                status="admitted",
                turn_id=turn_id,
                queue_position=None,
            )
            db.commit()
            return result
        if existing.status == "failed":
            result = AdmissionResult(
                submission_id=existing.id,
                version=existing.version,
                status="failed",
                turn_id=None,
                queue_position=existing.position,
                error=existing.error,
            )
            db.commit()
            return result
        result = AdmissionResult(
            submission_id=existing.id,
            version=existing.version,
            status="queued",
            turn_id=None,
            queue_position=existing.position,
        )
        db.commit()
        return result

    locked.mode = mode
    next_position = (
        db.query(func.max(PendingSubmission.position))
        .filter(PendingSubmission.conversation_id == locked.id)
        .scalar()
        or 0
    ) + 1
    had_retained_submission = _has_retained_submission_locked(db, locked.id)
    submission = PendingSubmission(
        id=submission_id,
        conversation_id=locked.id,
        user_id=user_id,
        version=version,
        position=next_position,
        status="pending",
        message=message,
        mode=mode,
        execution_mode=execution_mode,
        question_indexes_json=normalized_indexes,
        attachments_json=attachment_snapshots,
        object_references_json=normalized_object_references,
        source_client_id=source_client_id,
    )
    db.add(submission)
    db.flush()

    turn = None
    if _active_turn_locked(db, locked) is None and not had_retained_submission:
        # Direct admission is legal only when the Conversation was idle and
        # the retained queue was empty before this command.
        turn = _claim_submission_locked(db, locked, submission)
    db.commit()
    if turn is not None and turn.submission_id == submission.id:
        return AdmissionResult(
            submission_id=submission.id,
            version=submission.version,
            status="admitted",
            turn_id=turn.id,
            queue_position=None,
            should_dispatch=True,
            dispatch_turn_id=turn.id,
        )
    if submission.status == "failed":
        return AdmissionResult(
            submission_id=submission.id,
            version=submission.version,
            status="failed",
            turn_id=None,
            queue_position=submission.position,
            error=submission.error,
        )
    return AdmissionResult(
        submission_id=submission.id,
        version=submission.version,
        status="queued",
        turn_id=None,
        queue_position=submission.position,
        should_dispatch=False,
        dispatch_turn_id=None,
    )


def update_pending_submission(
    db: Session,
    conversation_id: str,
    user_id: int,
    submission_id: str,
    *,
    expected_version: int,
    message: str,
    mode: str,
    question_indexes: list[int],
    attachment_draft_ids: list[str],
    object_references: list[dict] | None = None,
    execution_mode: str = "standard",
) -> PendingSubmission:
    """CAS-edit a retained row without admitting it or changing FIFO order."""
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .with_for_update()
        .one_or_none()
    )
    row = (
        db.query(PendingSubmission)
        .filter(
            PendingSubmission.id == submission_id,
            PendingSubmission.conversation_id == conversation_id,
            PendingSubmission.user_id == user_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if (
        conversation is None
        or row is None
        or row.status not in {"pending", "failed"}
        or int(row.version) != expected_version
    ):
        raise SubmissionConflictError("submission is no longer editable")

    normalized_mode = runtime_profile_for_type(conversation.type).resolve_mode(
        conversation.mode, mode
    )
    if execution_mode not in {"standard", "auto"}:
        raise SubmissionConflictError("unsupported execution mode")
    next_attachments = [
        {"draft_id": draft_id} for draft_id in dict.fromkeys(attachment_draft_ids)
    ]
    try:
        next_object_references = normalize_product_object_references(object_references)
    except ProductObjectReferenceError as exc:
        raise SubmissionConflictError(str(exc)) from exc
    previous_ids = {
        str(item["draft_id"])
        for item in (row.attachments_json or [])
        if isinstance(item, dict) and item.get("draft_id")
    }
    next_ids = {str(item["draft_id"]) for item in next_attachments}
    if previous_ids - next_ids:
        from app.conversation.application.attachment_ingress_service import (
            remove_attachment_draft,
        )

        for draft_id in sorted(previous_ids - next_ids):
            remove_attachment_draft(
                db,
                user_pk=user_id,
                conversation_id=conversation_id,
                draft_id=draft_id,
            )
    row.message = message
    row.mode = normalized_mode
    row.execution_mode = execution_mode
    row.question_indexes_json = list(dict.fromkeys(question_indexes))
    row.attachments_json = next_attachments
    row.object_references_json = next_object_references
    row.version = expected_version + 1
    row.status = "pending"
    row.error = None
    row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return row


def retry_pending_submission(
    db: Session,
    conversation_id: str,
    user_id: int,
    submission_id: str,
    *,
    expected_version: int,
) -> AdmissionResult:
    """Explicitly retry/select one retained row without reordering the rest."""
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    row = (
        db.query(PendingSubmission)
        .filter(
            PendingSubmission.id == submission_id,
            PendingSubmission.conversation_id == conversation_id,
            PendingSubmission.user_id == user_id,
            PendingSubmission.version == expected_version,
            PendingSubmission.status.in_(("pending", "failed")),
        )
        .with_for_update()
        .one_or_none()
    )
    if conversation is None or row is None:
        raise SubmissionConflictError("submission is no longer retryable")
    failed_hold_exists = (
        db.query(PendingSubmission.id)
        .filter(
            PendingSubmission.conversation_id == conversation_id,
            PendingSubmission.status == "failed",
        )
        .first()
        is not None
    )
    if row.status != "failed" and not failed_hold_exists:
        raise SubmissionConflictError("submission must wait for FIFO admission")
    if _active_turn_locked(db, conversation) is not None:
        row.status = "pending"
        row.error = None
        row.updated_at = utc_now()
        db.commit()
        return AdmissionResult(
            submission_id=row.id,
            version=row.version,
            status="queued",
            turn_id=None,
            queue_position=row.position,
        )
    turn = _claim_selected_submission_locked(
        db,
        conversation,
        submission_id=row.id,
        expected_version=expected_version,
    )
    db.commit()
    if turn is None:
        return AdmissionResult(
            submission_id=row.id,
            version=row.version,
            status="failed",
            turn_id=None,
            queue_position=row.position,
            error=row.error,
        )
    return AdmissionResult(
        submission_id=row.id,
        version=row.version,
        status="admitted",
        turn_id=turn.id,
        queue_position=None,
        should_dispatch=True,
        dispatch_turn_id=turn.id,
    )


def withdraw_pending_submission(
    db: Session,
    conversation_id: str,
    user_id: int,
    submission_id: str,
    *,
    expected_version: int,
) -> str | None:
    """Withdraw one unclaimed row and release its draft references."""
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    row = (
        db.query(PendingSubmission)
        .filter(
            PendingSubmission.id == submission_id,
            PendingSubmission.conversation_id == conversation_id,
            PendingSubmission.user_id == user_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if (
        conversation is None
        or row is None
        or row.status not in {"pending", "failed"}
        or int(row.version) != expected_version
    ):
        raise SubmissionConflictError("submission is no longer withdrawable")
    from app.conversation.application.attachment_ingress_service import (
        remove_attachment_draft,
    )

    for item in row.attachments_json or []:
        if isinstance(item, dict) and item.get("draft_id"):
            remove_attachment_draft(
                db,
                user_pk=user_id,
                conversation_id=conversation_id,
                draft_id=str(item["draft_id"]),
            )
    row.status = "withdrawn"
    row.error = None
    row.updated_at = utc_now()
    next_turn = None
    if _active_turn_locked(db, conversation) is None:
        next_turn = _claim_next_submission_locked(db, conversation)
    db.commit()
    return next_turn.id if next_turn is not None else None


def request_turn_interrupt(
    db: Session,
    conversation_id: str,
    turn_id: str,
    user_id: int,
    submission_id: str,
    *,
    expected_version: int,
) -> tuple[str, int]:
    """Persist a one-shot interrupt target and close the current dispatch gate."""
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    turn = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.id == turn_id,
            ConversationTurn.conversation_id == conversation_id,
            ConversationTurn.user_id == user_id,
        )
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    target = (
        db.query(PendingSubmission)
        .filter(
            PendingSubmission.id == submission_id,
            PendingSubmission.conversation_id == conversation_id,
            PendingSubmission.user_id == user_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if (
        conversation is None
        or turn is None
        or target is None
        or conversation.active_turn_id != turn.id
        or turn.status not in {"pending", "running", "waiting"}
        or target.status not in {"pending", "failed"}
        or int(target.version) != expected_version
    ):
        raise SubmissionConflictError("interrupt target is stale")
    if turn.interrupt_submission_id is not None:
        if (
            turn.interrupt_submission_id == target.id
            and turn.interrupt_submission_version == expected_version
        ):
            return turn.status, int(turn.dispatch_generation or 1)
        raise SubmissionConflictError("another interrupt is already in progress")

    turn.interrupt_submission_id = target.id
    turn.interrupt_submission_version = expected_version
    turn.dispatch_generation = int(turn.dispatch_generation or 1) + 1
    target.status = "pending"
    target.error = None
    target.updated_at = utc_now()

    # Close already-registered calls before cancelling the worker.  Read calls
    # are safely cancelled; a side-effecting/unknown call remains explicitly
    # unknown until its provider-specific reconcile path resolves it.
    registered_calls = (
        db.query(AgentToolCall)
        .filter(
            AgentToolCall.turn_id == turn.id,
            AgentToolCall.status.in_(("running", "waiting", "deferred")),
        )
        .with_for_update()
        .all()
    )
    # Local import avoids bootstrapping the Agent tool package while this
    # service is still defining the Turn ownership primitives it consumes.
    from app.agent_runtime.tool_call_executor import record_tool_call_interrupt

    for call in registered_calls:
        if call.status in {"waiting", "deferred"}:
            status = "cancelled"
            result = {
                "error": "tool_not_dispatched",
                "reason": "user_interrupt",
            }
            error = "tool_not_dispatched"
        elif call.effect == "read":
            status = "cancelled"
            result = {"error": "tool_cancelled", "reason": "user_interrupt"}
            error = "tool_cancelled"
        else:
            status = "unknown"
            result = {
                "error": "tool_outcome_unknown",
                "reason": "user_interrupt_requires_reconcile",
            }
            error = "tool_outcome_unknown"
        record_tool_call_interrupt(
            db,
            row=call,
            status=status,
            result=result,
            error=error,
        )
    db.commit()
    return turn.status, int(turn.dispatch_generation)


def _terminalize(
    db: Session,
    turn_id: str,
    *,
    allowed_statuses: set[str],
    status: str,
    error: str | None,
    user_id: int | None = None,
    owner_id: str | None = None,
    stale_before: datetime | None = None,
    expected_generation: int | None = None,
) -> tuple[bool, str | None]:
    """Terminalize and claim at most one FIFO successor under one lock."""
    hint = db.get(ConversationTurn, turn_id)
    if hint is None:
        return False, None
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == hint.conversation_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if conversation is None:
        return False, None
    row = (
        db.query(ConversationTurn)
        .filter(ConversationTurn.id == turn_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    heartbeat = (
        (
            (row.dispatch_requested_at or row.created_at)
            if row.status == "pending"
            else (row.heartbeat_at or row.started_at or row.created_at)
        )
        if row
        else None
    )
    if (
        row is None
        or row.status not in allowed_statuses
        or (user_id is not None and row.user_id != user_id)
        or (owner_id is not None and row.owner_id != owner_id)
        or (
            expected_generation is not None
            and row.dispatch_generation != expected_generation
        )
        or (
            stale_before is not None
            and heartbeat is not None
            and heartbeat >= stale_before
        )
    ):
        return False, None
    row.status = status
    row.waiting_reason = None
    row.error = error
    row.owner_id = None
    row.heartbeat_at = None
    row.completed_at = utc_now()
    from app.conversation.application.agent_task_service import (
        freeze_agent_task_for_terminal_turn,
    )

    freeze_agent_task_for_terminal_turn(db, turn_id=row.id)
    interrupt_submission_id = row.interrupt_submission_id
    interrupt_submission_version = row.interrupt_submission_version
    next_turn = None
    if conversation.active_turn_id == row.id:
        conversation.active_turn_id = None
        if interrupt_submission_id is not None:
            # Explicit interrupt is the only FIFO extraction exception.  A
            # stale/failed selected item intentionally produces no fallback.
            next_turn = _claim_selected_submission_locked(
                db,
                conversation,
                submission_id=interrupt_submission_id,
                expected_version=int(interrupt_submission_version or 0),
            )
        else:
            next_turn = _claim_next_submission_locked(db, conversation)
    row.interrupt_submission_id = None
    row.interrupt_submission_version = None
    completed_was_automation = _turn_has_automation_trigger(db, row.id)
    db.commit()
    next_turn_id = next_turn.id if next_turn is not None else None
    if next_turn_id is None and not completed_was_automation:
        next_turn_id = _admit_persistent_task_after_user_terminal(
            db,
            conversation_id=conversation.id,
        )
    return True, next_turn_id


def _turn_has_automation_trigger(db: Session, turn_id: str) -> bool:
    from app.models.persistent_task import PersistentTaskTrigger

    return (
        db.query(PersistentTaskTrigger.id)
        .filter(PersistentTaskTrigger.admitted_turn_id == turn_id)
        .first()
        is not None
    )


def _admit_persistent_task_after_user_terminal(
    db: Session,
    *,
    conversation_id: str,
) -> str | None:
    """Admit retained automation only after ordinary user FIFO is empty."""

    from app.agent_runtime.turn_tool_catalog import (
        cloud_sustainable_automation_tool_names,
    )
    from app.models.persistent_task import PersistentTask
    from app.automation.application.tasks import PersistentTaskError
    from app.automation.application.tasks import admit_pending_persistent_task_triggers

    task = (
        db.query(PersistentTask)
        .filter(PersistentTask.conversation_id == conversation_id)
        .one_or_none()
    )
    if task is None:
        return None
    try:
        admission = admit_pending_persistent_task_triggers(
            db,
            user_pk=task.user_id,
            task_id=task.id,
            cloud_sustainable_tool_names=cloud_sustainable_automation_tool_names(),
        )
        db.commit()
    except PersistentTaskError:
        db.rollback()
        logger.exception(
            "PersistentTask successor admission failed after user Turn: %s",
            task.id,
        )
        return None
    return (
        admission.run_request.turn_id
        if admission.should_dispatch and admission.run_request is not None
        else None
    )


def _fail_dispatched_turn_without_handoff(turn_id: str, error: str) -> None:
    """Close an admitted turn whose queue dispatch failed, without cascading."""
    db = SessionLocal()
    try:
        hint = db.get(ConversationTurn, turn_id)
        if hint is None:
            return
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == hint.conversation_id)
            .with_for_update()
            .one_or_none()
        )
        row = (
            db.query(ConversationTurn)
            .filter(ConversationTurn.id == turn_id)
            .with_for_update()
            .one_or_none()
        )
        if row is None or row.status != "pending":
            return
        if _turn_has_automation_trigger(db, row.id):
            # The bounded PersistentTask repair re-dispatches this same Turn;
            # do not manufacture a terminal result for a broker outage.
            return
        row.status = "failed"
        row.waiting_reason = None
        row.error = error
        row.completed_at = utc_now()
        if conversation and conversation.active_turn_id == row.id:
            conversation.active_turn_id = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _dispatch_handoff(turn_id: str | None) -> None:
    if not turn_id:
        return
    try:
        schedule_turn(turn_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not dispatch admitted conversation turn %s", turn_id)
        _fail_dispatched_turn_without_handoff(
            turn_id, f"后台任务队列暂时不可用: {humanize_error(exc)}"
        )


def cancel_pending_turn(db: Session, turn_id: str, user_id: int) -> bool:
    """Cancel an undispatched or waiting Turn and hand off its successor."""
    from app.models.persistent_task import PersistentTask, PersistentTaskTrigger

    automation_task_id = (
        db.query(PersistentTask.id)
        .join(
            PersistentTaskTrigger,
            PersistentTaskTrigger.persistent_task_id == PersistentTask.id,
        )
        .filter(
            PersistentTaskTrigger.admitted_turn_id == turn_id,
            PersistentTask.user_id == user_id,
        )
        .scalar()
    )
    automation_turn = db.get(ConversationTurn, turn_id)
    if (
        automation_task_id is not None
        and automation_turn is not None
        and automation_turn.status in {"pending", "waiting"}
    ):
        from app.agent_runtime.turn_tool_catalog import (
            cloud_sustainable_automation_tool_names,
        )
        from app.automation.application.tasks import (
            settle_automation_turn_and_admit_next,
        )

        admission = settle_automation_turn_and_admit_next(
            db,
            user_pk=user_id,
            task_id=automation_task_id,
            turn_id=turn_id,
            terminal_status="cancelled",
            error="Turn cancelled",
            cloud_sustainable_tool_names=cloud_sustainable_automation_tool_names(),
            user_stopped=True,
        )
        db.commit()
        if admission.user_turn_dispatch_id is not None:
            _dispatch_handoff(admission.user_turn_dispatch_id)
        elif admission.should_dispatch and admission.run_request is not None:
            try:
                schedule_turn(admission.run_request.turn_id)
            except Exception:  # noqa: BLE001 - bounded repair retains it
                logger.exception(
                    "Automation successor dispatch deferred to repair: %s",
                    admission.run_request.turn_id,
                )
        return True
    changed, next_turn_id = _terminalize(
        db,
        turn_id,
        allowed_statuses={"pending", "waiting"},
        status="cancelled",
        error="Turn cancelled",
        user_id=user_id,
    )
    if changed:
        _dispatch_handoff(next_turn_id)
    return changed


def fail_pending_turn(
    db: Session,
    turn_id: str,
    user_id: int,
    error: str,
) -> bool:
    """Fail an undispatched turn and atomically hand off its FIFO successor."""
    changed, next_turn_id = _terminalize(
        db,
        turn_id,
        allowed_statuses={"pending"},
        status="failed",
        error=error,
        user_id=user_id,
    )
    if changed:
        _dispatch_handoff(next_turn_id)
    return changed


def _claim(turn_id: str) -> TurnExecution | None:
    """Atomically lease one pending turn to this worker."""
    db = SessionLocal()
    try:
        row = (
            db.query(ConversationTurn)
            .filter(
                ConversationTurn.id == turn_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if row is None or row.status != "pending":
            return None
        username = db.query(User.username).filter(User.id == row.user_id).scalar()
        if username is None:
            return None
        from app.agent_runtime.turn_tool_catalog import (
            cloud_sustainable_automation_tool_names,
        )
        from app.automation.application.tasks import resolve_automation_run_request

        automation = resolve_automation_run_request(
            db,
            turn_id=row.id,
            cloud_sustainable_tool_names=cloud_sustainable_automation_tool_names(),
        )
        now = utc_now()
        row.status = "running"
        row.waiting_reason = None
        row.started_at = now
        row.heartbeat_at = now
        row.owner_id = _WORKER_ID
        result = TurnExecution(
            id=row.id,
            conversation_id=row.conversation_id,
            username=username,
            user_pk=int(row.user_id),
            mode=row.mode,
            execution_mode=row.execution_mode,
            message=automation.input_message if automation is not None else row.message,
            dispatch_generation=int(row.dispatch_generation or 1),
            question_indexes=tuple(row.question_indexes_json or []),
            attachments=tuple(
                dict(item)
                for item in (row.attachments_json or [])
                if isinstance(item, dict)
            ),
            object_references=tuple(
                dict(item)
                for item in (row.object_references_json or [])
                if isinstance(item, dict)
            ),
            automation_task_id=(
                automation.persistent_task_id if automation is not None else None
            ),
            automation_user_id=(automation.user_id if automation is not None else None),
            automation_definition_version=(
                automation.definition_version if automation is not None else None
            ),
            automation_tool_names=(
                automation.allowed_tool_names if automation is not None else ()
            ),
            automation_skill_refs=(
                automation.skill_refs if automation is not None else ()
            ),
            automation_validation_error=(
                automation.validation_error if automation is not None else None
            ),
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _finish(
    turn_id: str,
    status: str,
    error: str | None = None,
    *,
    expected_generation: int | None = None,
) -> bool:
    """Owner-fenced terminalization plus one atomic FIFO admission handoff."""
    db = SessionLocal()
    try:
        changed, next_turn_id = _terminalize(
            db,
            turn_id,
            allowed_statuses={"running"},
            status=status,
            error=error,
            owner_id=_WORKER_ID,
            expected_generation=expected_generation,
        )
        if changed:
            _dispatch_handoff(next_turn_id)
            if status == "completed":
                try:
                    from app.memory.recall import record_turn_usage

                    record_turn_usage(db, db.get(ConversationTurn, turn_id))
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception(
                        "Could not record memory citations for %s", turn_id
                    )
            if status == "completed" and settings.AGENT_MEMORY_PRODUCER_ENABLED:
                try:
                    from app.task_queue.dispatch import (
                        dispatch_agent_memory_consolidation,
                    )

                    dispatch_agent_memory_consolidation(
                        turn_id,
                        countdown=settings.AGENT_MEMORY_IDLE_SECONDS,
                    )
                except Exception:  # noqa: BLE001 - source Turn stays authoritative
                    logger.exception(
                        "Could not schedule optional Agent Memory consolidation for %s",
                        turn_id,
                    )
        return changed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _finish_automation(
    turn: TurnExecution,
    status: str,
    error: str | None = None,
) -> bool:
    """Settle an unattended Turn through its PersistentTask ingress owner."""

    if turn.automation_task_id is None:
        return _finish(
            turn.id, status, error, expected_generation=turn.dispatch_generation
        )
    db = SessionLocal()
    try:
        from app.agent_runtime.turn_tool_catalog import (
            cloud_sustainable_automation_tool_names,
        )
        from app.automation.application.tasks import PersistentTaskTriggerConflictError
        from app.automation.application.tasks import (
            settle_automation_turn_and_admit_next,
        )

        try:
            admission = settle_automation_turn_and_admit_next(
                db,
                user_pk=int(turn.automation_user_id or 0),
                task_id=turn.automation_task_id,
                turn_id=turn.id,
                terminal_status=status,
                error=error,
                cloud_sustainable_tool_names=(
                    cloud_sustainable_automation_tool_names()
                ),
                owner_id=_WORKER_ID,
                dispatch_generation=turn.dispatch_generation,
                user_stopped=status == "cancelled",
            )
        except PersistentTaskTriggerConflictError:
            db.rollback()
            return False
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if admission.user_turn_dispatch_id is not None:
        _dispatch_handoff(admission.user_turn_dispatch_id)
    elif admission.should_dispatch and admission.run_request is not None:
        try:
            schedule_turn(admission.run_request.turn_id)
        except Exception:  # noqa: BLE001 - bounded repair retains pending Turn
            logger.exception(
                "Automation successor dispatch deferred to repair: %s",
                admission.run_request.turn_id,
            )
    return True


def _wait(
    turn_id: str, reason: str = "interaction", *, expected_generation: int | None = None
) -> bool:
    """Release the worker while retaining this Turn as Conversation owner."""
    db = SessionLocal()
    try:
        row = (
            db.query(ConversationTurn)
            .filter(ConversationTurn.id == turn_id)
            .with_for_update()
            .one_or_none()
        )
        if (
            row is None
            or row.status != "running"
            or row.owner_id != _WORKER_ID
            or (
                expected_generation is not None
                and row.dispatch_generation != expected_generation
            )
        ):
            return False
        row.status = "waiting"
        row.waiting_reason = reason
        row.owner_id = None
        row.heartbeat_at = None
        row.error = None
        db.commit()
        if reason == "attachment_parsing":
            # Close the ingestion-before-wait race.  The parsing callback may
            # have observed the projection just before this waiting state was
            # committed; the same Turn CAS makes this bounded recheck safe.
            from app.conversation.application.attachment_waiting_service import (
                wake_attachment_turn_if_terminal,
            )

            wake_attachment_turn_if_terminal(
                turn_id, actions=attachment_resume_actions()
            )
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def resume_waiting_turn(
    db: Session,
    turn_id: str,
    user_id: int,
    *,
    expected_reason: str | None = None,
) -> int | None:
    """CAS a waiting Turn back to pending without admitting another input.

    The Interaction resolution and this transition share the caller's DB
    transaction. Incrementing ``dispatch_generation`` fences any late result
    from the released worker before the same Turn is dispatched again.
    """
    hint = db.get(ConversationTurn, turn_id)
    if hint is None:
        return None
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == hint.conversation_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    row = (
        db.query(ConversationTurn)
        .filter(ConversationTurn.id == turn_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if (
        conversation is None
        or row is None
        or row.user_id != user_id
        or row.status != "waiting"
        or (expected_reason is not None and row.waiting_reason != expected_reason)
        or conversation.active_turn_id != row.id
    ):
        return None
    row.status = "pending"
    row.waiting_reason = None
    row.dispatch_generation = int(row.dispatch_generation or 1) + 1
    row.dispatch_requested_at = utc_now()
    row.owner_id = None
    row.heartbeat_at = None
    row.error = None
    row.completed_at = None
    db.commit()
    return int(row.dispatch_generation)


def _heartbeat(turn_id: str, expected_generation: int | None = None) -> bool:
    # One conditional UPDATE closes the read/lease-takeover race.
    db = SessionLocal()
    try:
        query = db.query(ConversationTurn).filter(
            ConversationTurn.id == turn_id,
            ConversationTurn.status == "running",
            ConversationTurn.owner_id == _WORKER_ID,
        )
        if expected_generation is not None:
            query = query.filter(
                ConversationTurn.dispatch_generation == expected_generation
            )
        changed = query.update(
            {ConversationTurn.heartbeat_at: utc_now()}, synchronize_session=False
        )
        db.commit()
        return changed == 1
    finally:
        db.close()


def _has_assistant(turn_id: str) -> bool:
    db = SessionLocal()
    try:
        row = db.get(ConversationTurn, turn_id)
        return bool(row and row.assistant_message_seq is not None)
    finally:
        db.close()


async def execute_turn(turn_id: str) -> None:
    turn = await asyncio.to_thread(_claim, turn_id)
    if turn is None:
        return
    from app.usage.runtime import scope

    with scope(turn.user_pk, f"turn:{turn_id}", username=turn.username):
        await _execute_claimed_turn(turn_id, turn)


async def _execute_claimed_turn(turn_id: str, turn: TurnExecution) -> None:
    saw_done = False
    failure: str | None = None
    diagnostic_error: str | None = None
    engine = None
    cancelled = False
    waiting = False
    outcome = "completed"
    waiting_reason = "interaction"
    owner_task = asyncio.current_task()

    async def emit(event_json: str) -> None:
        envelope = json.loads(event_json)
        envelope["dispatch_generation"] = turn.dispatch_generation
        await turn_event_buffer.append(
            turn_id, json.dumps(envelope, ensure_ascii=False)
        )

    async def watch_cancel() -> None:
        await turn_event_buffer.wait_cancel(turn_id)
        if owner_task is not None:
            owner_task.cancel()

    cancel_watcher = asyncio.create_task(
        watch_cancel(), name=f"chat-turn-cancel:{turn_id}"
    )

    async def maintain_heartbeat() -> None:
        while True:
            await asyncio.sleep(settings.TURN_HEARTBEAT_SECONDS)
            try:
                owned = await asyncio.to_thread(
                    _heartbeat, turn_id, turn.dispatch_generation
                )
                if not owned and owner_task is not None:
                    owner_task.cancel()
                    return
            except Exception:  # noqa: BLE001
                logger.exception("turn heartbeat failed: %s", turn_id)

    heartbeat = asyncio.create_task(
        maintain_heartbeat(),
        name=f"chat-turn-heartbeat:{turn_id}",
    )
    try:
        if turn.automation_validation_error:
            raise ValueError(turn.automation_validation_error)
        from app.conversation.engine import ConversationEngine
        from app.conversation.factory import make_agent_strategy
        from app.conversation.factory import make_chat_strategy

        strategy = (
            make_agent_strategy() if turn.mode == "agent" else make_chat_strategy()
        )
        object_reference_context = await asyncio.to_thread(
            build_product_object_context,
            user_pk=turn.user_pk,
            references=turn.object_references,
        )
        strategy_extras = {
            "execution_mode": turn.execution_mode,
            # Preserve the immutable admitted typed identities separately from
            # the server-rendered label/context projection. The Engine uses
            # this only for deterministic explicit source reads.
            "admitted_object_references": list(turn.object_references),
        }
        if turn.automation_task_id is not None:
            strategy_extras.update(
                {
                    "unattended_automation": True,
                    "builtin_tool_allowlist": turn.automation_tool_names,
                    "persistent_task_skill_refs": list(turn.automation_skill_refs),
                    "persistent_task_id": turn.automation_task_id,
                    "persistent_task_definition_version": (
                        turn.automation_definition_version
                    ),
                }
            )
        engine = ConversationEngine(
            user_id=turn.username,
            user_pk=turn.user_pk,
            session_id=turn.conversation_id,
            user_message=turn.message,
            question_indexes=turn.question_indexes,
            attachments=turn.attachments,
            product_object_context=object_reference_context,
            strategy=strategy,
            turn_id=turn_id,
            dispatch_generation=turn.dispatch_generation,
            strategy_extras=strategy_extras,
        )
        async for event in engine.submit_message():
            await emit(event.to_json())
            saw_done = saw_done or event.type.value == "done"
            if event.type.value == "error":
                # Error events are diagnostics, not an implicit Turn outcome.
                diagnostic_error = str(
                    event.data.get("error") or "Turn execution failed"
                )
        declared_outcome = getattr(engine, "outcome", None)
        outcome = str(declared_outcome or "completed")
        waiting = outcome == "waiting"
        if outcome == "failed":
            failure = diagnostic_error or "Turn execution failed"
        elif declared_outcome is None and diagnostic_error is not None:
            # Compatibility for strategy hosts that predate explicit outcome:
            # only an authoritative modern Engine may decouple diagnostics
            # from terminal state.
            outcome = "failed"
            failure = diagnostic_error
        if (
            not waiting
            and not failure
            and outcome in {"completed", "blocked"}
            and not await asyncio.to_thread(_has_assistant, turn_id)
        ):
            failure = "本轮未生成有效回复"
            outcome = "failed"
    except asyncio.CancelledError:
        failure = "Turn cancelled"
        cancelled = True
        raise
    except Exception as exc:  # noqa: BLE001
        from app.rag.application.attachment_sources import (
            AttachmentParsingPendingError,
        )

        if isinstance(exc, AttachmentParsingPendingError):
            # The frozen Turn/AttachmentRef already exists. Release compute and
            # let the parsing worker resume this same Turn/generation lineage;
            # never create another user message or silently omit the source.
            waiting = True
            outcome = "waiting"
            waiting_reason = "attachment_parsing"
            await emit(
                HarnessEvent.status("附件仍在解析，完成后将自动继续本轮。").to_json(),
            )
        elif isinstance(exc, ProductObjectReferenceUnavailableError):
            failure = UNAVAILABLE_MESSAGE
            outcome = "failed"
            await emit(HarnessEvent.error(failure).to_json())
            # The admitted user input is already exact History. Persist the
            # deterministic read failure too, so a refresh does not erase the
            # reason this Turn failed before ConversationEngine was created.
            await asyncio.to_thread(
                transcript_service.complete_background_turn,
                turn_id=turn_id,
                ai_msg=f"⚠️ {failure}",
                expected_generation=turn.dispatch_generation,
                ai_blocks=[{"type": "text", "text": f"⚠️ {failure}"}],
            )
        else:
            failure = humanize_error(exc)
            outcome = "failed"
            logger.exception("background turn %s failed", turn_id)
            await emit(HarnessEvent.error(failure).to_json())
    finally:
        try:
            if engine is not None:
                declared_outcome = getattr(engine, "outcome", None)
                if declared_outcome is not None:
                    outcome = str(declared_outcome)
                waiting = outcome == "waiting"
                if outcome == "failed" and failure is None:
                    failure = diagnostic_error or "Turn execution failed"
            if failure and engine is not None and not cancelled and not waiting:
                await engine.persist_background_failure(failure)
            if not saw_done:
                emitted_outcome = (
                    "cancelled"
                    if cancelled
                    else "failed"
                    if failure
                    else "waiting"
                    if waiting
                    else outcome
                )
                await emit(
                    HarnessEvent.done(
                        step=0,
                        elapsed_ms=0,
                        outcome=emitted_outcome,
                    ).to_json(),
                )
        finally:
            cancel_watcher.cancel()
            heartbeat.cancel()
            await asyncio.gather(cancel_watcher, heartbeat, return_exceptions=True)
            if waiting and not cancelled and not failure:
                await asyncio.to_thread(
                    _wait,
                    turn_id,
                    waiting_reason,
                    expected_generation=turn.dispatch_generation,
                )
            else:
                finish = (
                    _finish_automation
                    if turn.automation_task_id is not None
                    else _finish
                )
                await asyncio.to_thread(
                    finish,
                    turn if turn.automation_task_id is not None else turn_id,
                    (
                        "cancelled"
                        if cancelled
                        else "failed"
                        if failure
                        else outcome
                        if outcome in {"blocked", "cancelled"}
                        else "completed"
                    ),
                    failure,
                    **(
                        {"expected_generation": turn.dispatch_generation}
                        if turn.automation_task_id is None
                        else {}
                    ),
                )


def schedule_turn(turn_id: str) -> None:
    """Dispatch a durable turn to the isolated conversation-worker queue."""
    from app.task_queue.dispatch import dispatch_conversation_turn

    dispatch_conversation_turn(turn_id)


async def fail_orphaned_turns() -> int:
    """Close turns whose worker heartbeat has expired."""
    db = SessionLocal()
    handoffs: list[str] = []
    try:
        cutoff = utc_now() - timedelta(seconds=settings.TURN_STALE_SECONDS)
        candidate_ids = [
            row_id
            for (row_id,) in (
                db.query(ConversationTurn.id)
                .filter(
                    or_(
                        (ConversationTurn.status == "pending")
                        & (
                            func.coalesce(
                                ConversationTurn.dispatch_requested_at,
                                ConversationTurn.created_at,
                            )
                            < cutoff
                        ),
                        (ConversationTurn.status == "running")
                        & (
                            func.coalesce(
                                ConversationTurn.heartbeat_at,
                                ConversationTurn.started_at,
                                ConversationTurn.created_at,
                            )
                            < cutoff
                        ),
                    )
                )
                .order_by(ConversationTurn.created_at, ConversationTurn.id)
                .limit(settings.TURN_RECOVERY_BATCH_SIZE)
                .all()
            )
        ]
        turn_ids: list[str] = []
        for turn_id in candidate_ids:
            from app.conversation.application.invitation_turn_recovery import (
                recover_invitation_turn,
            )

            recovered = recover_invitation_turn(
                db, turn_id=turn_id, stale_before=cutoff
            )
            if recovered is not None:
                if recovered == "pending":
                    handoffs.append(turn_id)
                continue
            changed, next_turn_id = _terminalize(
                db,
                turn_id,
                allowed_statuses={"pending", "running"},
                status="failed",
                error="服务重启，本轮执行已中断",
                stale_before=cutoff,
            )
            if changed:
                turn_ids.append(turn_id)
                if next_turn_id:
                    handoffs.append(next_turn_id)
    finally:
        db.close()

    for next_turn_id in handoffs:
        try:
            await asyncio.to_thread(schedule_turn, next_turn_id)
        except Exception:
            logger.exception("Recovered dispatch retained for repair: %s", next_turn_id)

    for turn_id in turn_ids:
        await asyncio.to_thread(
            transcript_service.complete_background_turn,
            turn_id=turn_id,
            ai_msg="⚠️ 服务重启，本轮执行已中断",
            ai_blocks=[{"type": "text", "text": "⚠️ 服务重启，本轮执行已中断"}],
        )
        await turn_event_buffer.append(
            turn_id,
            HarnessEvent.error("服务重启，本轮执行已中断").to_json(),
        )
        await turn_event_buffer.append(
            turn_id,
            HarnessEvent.done(
                step=0,
                elapsed_ms=0,
                outcome="failed",
            ).to_json(),
        )
    return len(turn_ids)


async def monitor_orphaned_turns() -> None:
    interval = max(5, settings.TURN_STALE_SECONDS // 2)
    while True:
        await asyncio.sleep(interval)
        try:
            orphan_count = await fail_orphaned_turns()
            if orphan_count:
                logger.warning("Closed %d stale conversation turn(s).", orphan_count)
            from app.conversation.application.attachment_waiting_service import (
                recover_terminal_attachment_turns,
            )

            resumed = await asyncio.to_thread(
                recover_terminal_attachment_turns, actions=attachment_resume_actions()
            )
            if resumed:
                logger.info(
                    "Recovered %d attachment-waiting conversation turn(s).",
                    len(resumed),
                )
        except Exception:  # noqa: BLE001
            logger.exception("orphan turn monitor failed")


def attachment_resume_actions():
    """Wire readiness to the same supervisor used by user/automation ingress."""
    from app.conversation.application.attachment_waiting_service import ResumeActions

    return ResumeActions(resume_waiting_turn, schedule_turn, fail_pending_turn)
