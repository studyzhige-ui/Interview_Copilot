"""Application Service for PersistentTask and automation trigger intake.

The caller owns the transaction.  Dispatch happens only after that transaction
commits by passing the returned ``AutomationRunRequest`` to an injected runner.
There is deliberately no PersistentTaskRun model: the admitted
``ConversationTurn`` is the run identity and the existing Conversation row
lock/``active_turn_id`` field remains the single admission CAS.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.types import as_utc, utc_now
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.pending_submission import PendingSubmission
from app.models.persistent_task import PersistentTask, PersistentTaskTrigger
from app.schemas.persistent_task import (
    PersistentTaskCreate,
    PersistentTaskDelete,
    PersistentTaskStateChange,
    PersistentTaskTriggerInput,
    PersistentTaskUpdate,
)
from app.services.chat.turn_executor import _active_turn_locked


class PersistentTaskError(ValueError):
    """Base class for deterministic PersistentTask command rejection."""


class PersistentTaskNotFoundError(PersistentTaskError):
    """The task is absent or outside the caller's ownership boundary."""


class PersistentTaskIdempotencyConflictError(PersistentTaskError):
    """An idempotency identity was reused with different content."""


class PersistentTaskVersionConflictError(PersistentTaskError):
    """The task definition changed since the caller last read it."""


class PersistentTaskPausedError(PersistentTaskError):
    """Paused tasks do not accept scheduler or connector intake."""


class PersistentTaskToolScopeError(PersistentTaskError):
    """The definition names a Tool that is not cloud-sustainable and concrete."""


class PersistentTaskTriggerConflictError(PersistentTaskError):
    """A trigger does not belong to the task's current trigger channel."""


class PersistentTaskDeleteConflictError(PersistentTaskError):
    """The dedicated Conversation cannot yet be deleted safely."""


class PersistentTaskUnsupportedTriggerError(PersistentTaskError):
    """A configured trigger has no real trusted intake implementation."""


@dataclass(frozen=True)
class AutomationRunRequest:
    """Post-commit input for the cloud automation runner seam."""

    persistent_task_id: str
    conversation_id: str
    turn_id: str
    user_id: int
    definition_version: int
    instruction: str
    input_message: str
    trigger_ids: tuple[str, ...]
    allowed_tool_names: tuple[str, ...]
    read_scope: tuple[str, ...]
    action_scope: tuple[str, ...]
    validation_error: str | None = None


@dataclass(frozen=True)
class AutomationAdmission:
    trigger_id: str | None
    status: Literal["admitted", "pending", "already_admitted", "empty"]
    reason: str | None
    turn_id: str | None
    merged_trigger_ids: tuple[str, ...]
    pending_trigger_count: int
    should_dispatch: bool = False
    run_request: AutomationRunRequest | None = None
    # True only when the admitted successor is an ordinary user Turn.  Its
    # dispatch still uses the existing Conversation runner, never the injected
    # automation runner seam.
    user_turn_dispatch_id: str | None = None


@dataclass(frozen=True)
class PersistentTaskDeleteResult:
    task_id: str
    conversation_id: str
    ingestion_task_ids: tuple[str, ...]


AutomationRunner = Callable[[AutomationRunRequest], None]


def create_persistent_task(
    db: Session,
    *,
    user_pk: int,
    command: PersistentTaskCreate,
    cloud_sustainable_tool_names: Collection[str],
) -> PersistentTask:
    """Create one definition and its one-to-one Dedicated Conversation."""

    _require_implemented_trigger(command.trigger.kind)
    tools = _validate_requested_tools(
        command.allowed_tool_names,
        cloud_sustainable_tool_names,
    )
    creation_fingerprint = _creation_fingerprint(command, tools)
    existing = (
        db.query(PersistentTask)
        .filter(
            PersistentTask.user_id == user_pk,
            PersistentTask.idempotency_key == command.idempotency_key,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.creation_fingerprint != creation_fingerprint:
            raise PersistentTaskIdempotencyConflictError(command.idempotency_key)
        return existing

    conversation = Conversation(
        user_id=user_pk,
        title=f"自动化 · {command.title.strip()}",
        type="persistent_task",
        mode="agent",
    )
    db.add(conversation)
    db.flush()
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            seq=1,
            role="User",
            content=command.instruction.strip(),
            content_blocks_json=json.dumps(
                [{"type": "text", "text": command.instruction.strip()}],
                ensure_ascii=False,
            ),
        )
    )
    task = PersistentTask(
        user_id=user_pk,
        conversation_id=conversation.id,
        title=command.title.strip(),
        instruction=command.instruction.strip(),
        state="active",
        version=1,
        trigger_kind=command.trigger.kind,
        trigger_spec_json=command.trigger.model_dump(mode="json"),
        read_scope_json=list(command.read_scope),
        action_scope_json=list(command.action_scope),
        allowed_tool_names_json=list(tools),
        user_request_identity=command.user_request_identity.strip(),
        user_request_version=_optional_text(command.user_request_version),
        idempotency_key=command.idempotency_key.strip(),
        creation_fingerprint=creation_fingerprint,
        next_due_at=_next_due_for_trigger(command.trigger, after=utc_now()),
    )
    db.add(task)
    db.flush()
    return task


def update_persistent_task(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    command: PersistentTaskUpdate,
    cloud_sustainable_tool_names: Collection[str],
) -> PersistentTask:
    task = _locked_task(db, user_pk, task_id)
    _require_version(task, int(command.expected_version))
    if command.trigger is not None:
        _require_implemented_trigger(command.trigger.kind)
    if command.allowed_tool_names is not None:
        task.allowed_tool_names_json = list(
            _validate_requested_tools(
                command.allowed_tool_names,
                cloud_sustainable_tool_names,
            )
        )
    if command.title is not None:
        task.title = command.title.strip()
    if command.instruction is not None:
        task.instruction = command.instruction.strip()
    if command.trigger is not None:
        task.trigger_kind = command.trigger.kind
        task.trigger_spec_json = command.trigger.model_dump(mode="json")
        task.next_due_at = _next_due_for_trigger(command.trigger, after=utc_now())
    if command.read_scope is not None:
        task.read_scope_json = list(command.read_scope)
    if command.action_scope is not None:
        task.action_scope_json = list(command.action_scope)
    task.user_request_identity = command.user_request_identity.strip()
    task.user_request_version = _optional_text(command.user_request_version)
    task.version += 1
    task.updated_at = utc_now()
    db.add(task)
    db.flush()
    return task


def change_persistent_task_state(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    command: PersistentTaskStateChange,
) -> PersistentTask:
    """Pause/resume future intake without cancelling an existing Turn."""

    task = _locked_task(db, user_pk, task_id)
    _require_version(task, int(command.expected_version))
    if task.state == command.state:
        return task
    task.state = command.state
    task.user_request_identity = command.user_request_identity.strip()
    task.user_request_version = _optional_text(command.user_request_version)
    task.version += 1
    task.updated_at = utc_now()
    if task.state == "active" and task.trigger_kind == "scheduled":
        task.next_due_at = _next_due_from_saved_spec(task, after=task.updated_at)
    db.add(task)
    db.flush()
    return task


def delete_persistent_task(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    command: PersistentTaskDelete,
) -> PersistentTaskDeleteResult:
    """Delete a definition and its dedicated Conversation under one lock.

    Pending/waiting work has not acquired an active external execution lease,
    so it is terminalized in place. A running Turn is rejected: deleting its
    reconciliation identity would be unsafe. Promoted assets are preserved by
    the existing Conversation attachment cleanup owner.
    """

    task = _locked_task(db, user_pk, task_id)
    _require_version(task, int(command.expected_version))
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == task.conversation_id,
            Conversation.user_id == user_pk,
        )
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if conversation is None:
        raise PersistentTaskNotFoundError(task_id)
    active = _active_turn_locked(db, conversation)
    if active is not None and active.status == "running":
        raise PersistentTaskDeleteConflictError(
            "stop the running automation before deleting it"
        )
    if active is not None:
        if active.status not in {"pending", "waiting"}:
            raise PersistentTaskDeleteConflictError(
                f"cannot delete task with active Turn in {active.status}"
            )
        now = utc_now()
        active.status = "cancelled"
        active.waiting_reason = None
        active.error = "PersistentTask deleted by user"
        active.owner_id = None
        active.heartbeat_at = None
        active.dispatch_generation = int(active.dispatch_generation or 1) + 1
        active.completed_at = now
        conversation.active_turn_id = None
        from app.services.chat.agent_task_service import (
            freeze_agent_task_for_terminal_turn,
        )

        freeze_agent_task_for_terminal_turn(db, turn_id=active.id)
        db.add(active)
    task.state = "paused"
    task.next_due_at = None
    task.user_request_identity = command.user_request_identity.strip()
    task.user_request_version = _optional_text(command.user_request_version)
    task.version += 1
    task.updated_at = utc_now()
    db.add_all([task, conversation])
    db.flush()

    from app.services.chat.attachment_source_service import (
        cleanup_conversation_attachment_scope,
    )

    cleanup = cleanup_conversation_attachment_scope(
        db,
        user_pk=user_pk,
        conversation_id=conversation.id,
    )
    conversation_id = conversation.id
    # Keep local/test databases correct even when FK cascading is disabled;
    # production PostgreSQL performs the same dependency cleanup atomically.
    db.query(PersistentTaskTrigger).filter(
        PersistentTaskTrigger.persistent_task_id == task.id
    ).delete(synchronize_session="fetch")
    db.query(ConversationTurn).filter(
        ConversationTurn.conversation_id == conversation_id
    ).delete(synchronize_session="fetch")
    db.query(ConversationMessage).filter(
        ConversationMessage.conversation_id == conversation_id
    ).delete(synchronize_session=False)
    db.delete(task)
    db.delete(conversation)
    db.flush()
    return PersistentTaskDeleteResult(
        task_id=task_id,
        conversation_id=conversation_id,
        ingestion_task_ids=tuple(cleanup.ingestion_task_ids),
    )


def create_user_confirmed_manual_trigger(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    command: PersistentTaskTriggerInput,
    cloud_sustainable_tool_names: Collection[str],
) -> AutomationAdmission:
    """User-facing manual-run entry; non-manual kinds are trusted intake only."""

    if command.kind != "manual":
        raise PersistentTaskTriggerConflictError(
            "users can manually run a task but cannot manufacture scheduler events"
        )
    return intake_persistent_task_trigger(
        db,
        user_pk=user_pk,
        task_id=task_id,
        command=command,
        cloud_sustainable_tool_names=cloud_sustainable_tool_names,
    )


def intake_persistent_task_trigger(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    command: PersistentTaskTriggerInput,
    cloud_sustainable_tool_names: Collection[str],
) -> AutomationAdmission:
    """Persist one trigger and attempt shared Conversation admission.

    Observation/source validation belongs to the concrete scheduler or
    Connector that invokes this trusted intake command.  The summary remains
    trigger input; it does not become Product Domain State by being admitted.
    """

    task = _locked_task(db, user_pk, task_id)
    if task.state != "active":
        raise PersistentTaskPausedError(task.id)
    if command.kind != "manual" and command.kind != task.trigger_kind:
        raise PersistentTaskTriggerConflictError(
            f"{command.kind} trigger cannot enter a {task.trigger_kind} task"
        )

    existing = (
        db.query(PersistentTaskTrigger)
        .filter(
            PersistentTaskTrigger.persistent_task_id == task.id,
            PersistentTaskTrigger.idempotency_key == command.idempotency_key,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.occurrence_fingerprint != _trigger_fingerprint(command):
            raise PersistentTaskIdempotencyConflictError(command.idempotency_key)
        if existing.admitted_at is not None:
            return AutomationAdmission(
                trigger_id=existing.id,
                status="already_admitted",
                reason=None,
                turn_id=existing.admitted_turn_id,
                merged_trigger_ids=(existing.id,),
                pending_trigger_count=0,
            )
        return _attempt_admission_locked(
            db,
            task=task,
            trigger_id=existing.id,
            cloud_sustainable_tool_names=cloud_sustainable_tool_names,
        )

    trigger = PersistentTaskTrigger(
        persistent_task_id=task.id,
        kind=command.kind,
        occurred_at=command.occurred_at,
        observed_at=command.observed_at or utc_now(),
        source_identity=command.source_identity.strip(),
        source_version=_optional_text(command.source_version),
        summary=command.summary.strip(),
        cursor_after=_optional_text(command.cursor_after),
        occurrence_fingerprint=_trigger_fingerprint(command),
        idempotency_key=command.idempotency_key.strip(),
    )
    db.add(trigger)
    db.flush()
    return _attempt_admission_locked(
        db,
        task=task,
        trigger_id=trigger.id,
        cloud_sustainable_tool_names=cloud_sustainable_tool_names,
    )


def admit_pending_persistent_task_triggers(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    cloud_sustainable_tool_names: Collection[str],
) -> AutomationAdmission:
    """Re-evaluate retained triggers after the current/user Turn changes."""

    task = _locked_task(db, user_pk, task_id)
    if task.state != "active":
        return AutomationAdmission(
            trigger_id=None,
            status="pending",
            reason="task_paused",
            turn_id=None,
            merged_trigger_ids=(),
            pending_trigger_count=_pending_trigger_count(db, task.id),
        )
    return _attempt_admission_locked(
        db,
        task=task,
        trigger_id=None,
        cloud_sustainable_tool_names=cloud_sustainable_tool_names,
    )


def record_user_stopped_automation_run(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    turn_id: str,
    stopped_at: datetime | None = None,
) -> PersistentTask:
    """Block immediate compensation after the shared Kernel stops this Turn.

    This command does not cancel the Turn.  The integration must first use the
    existing safe Conversation cancellation path, then record the stop against
    the same authoritative Turn identity.
    """

    task = _locked_task(db, user_pk, task_id)
    owned_turn = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.id == turn_id,
            ConversationTurn.conversation_id == task.conversation_id,
            ConversationTurn.user_id == user_pk,
        )
        .one_or_none()
    )
    bound_trigger = (
        db.query(PersistentTaskTrigger.id)
        .filter(
            PersistentTaskTrigger.persistent_task_id == task.id,
            PersistentTaskTrigger.admitted_turn_id == turn_id,
        )
        .first()
    )
    if owned_turn is None or bound_trigger is None:
        raise PersistentTaskNotFoundError(turn_id)
    if owned_turn.status != "cancelled":
        raise PersistentTaskTriggerConflictError(
            "safe Conversation cancellation must finish before recording a stop"
        )
    task.compensation_blocked_at = stopped_at or utc_now()
    task.updated_at = utc_now()
    db.add(task)
    db.flush()
    return task


def dispatch_automation_run(
    admission: AutomationAdmission,
    runner: AutomationRunner,
) -> bool:
    """Dispatch one newly admitted Turn after its DB transaction commits."""

    if not admission.should_dispatch or admission.run_request is None:
        return False
    runner(admission.run_request)
    return True


def list_persistent_tasks(
    db: Session,
    *,
    user_pk: int,
) -> list[PersistentTask]:
    return (
        db.query(PersistentTask)
        .filter(PersistentTask.user_id == user_pk)
        .order_by(PersistentTask.updated_at.desc(), PersistentTask.id.asc())
        .all()
    )


def get_persistent_task(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
) -> PersistentTask:
    """Read one task without acquiring a command lock."""

    return _owned_task(db, user_pk, task_id)


def list_persistent_task_triggers(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
) -> list[PersistentTaskTrigger]:
    task = _owned_task(db, user_pk, task_id)
    return (
        db.query(PersistentTaskTrigger)
        .filter(PersistentTaskTrigger.persistent_task_id == task.id)
        .order_by(
            PersistentTaskTrigger.observed_at.asc(),
            PersistentTaskTrigger.id.asc(),
        )
        .all()
    )


def due_persistent_task_ids(
    db: Session,
    *,
    due_at: datetime,
    limit: int = 100,
) -> list[str]:
    """Return a bounded, deterministic scheduler batch from the DB cursor."""

    normalized_due_at = as_utc(due_at)
    assert normalized_due_at is not None
    return [
        task_id
        for (task_id,) in (
            db.query(PersistentTask.id)
            .filter(
                PersistentTask.state == "active",
                PersistentTask.trigger_kind == "scheduled",
                or_(
                    PersistentTask.next_due_at.is_(None),
                    PersistentTask.next_due_at <= normalized_due_at,
                ),
            )
            .order_by(PersistentTask.next_due_at, PersistentTask.id)
            .limit(max(1, min(int(limit), 500)))
            .all()
        )
    ]


def schedule_due_persistent_task(
    db: Session,
    *,
    task_id: str,
    due_at: datetime,
    cloud_sustainable_tool_names: Collection[str],
) -> AutomationAdmission | None:
    """Persist one due occurrence and advance its cursor atomically.

    The occurrence identity is derived from the task and scheduled UTC minute,
    so overlapping beat workers and broker retries converge on the same trigger.
    """

    normalized_due_at = as_utc(due_at)
    assert normalized_due_at is not None
    task = (
        db.query(PersistentTask)
        .filter(PersistentTask.id == task_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if (
        task is None
        or task.state != "active"
        or task.trigger_kind != "scheduled"
        or (task.next_due_at is not None and task.next_due_at > normalized_due_at)
    ):
        return None
    if task.next_due_at is None:
        task.next_due_at = _next_due_from_saved_spec(
            task,
            after=normalized_due_at,
        )
        task.updated_at = utc_now()
        db.add(task)
        return None
    occurred_at = task.next_due_at.astimezone(UTC)
    task.next_due_at = _next_due_from_saved_spec(task, after=occurred_at)
    task.updated_at = utc_now()
    db.add(task)
    command = PersistentTaskTriggerInput(
        kind="scheduled",
        occurred_at=occurred_at,
        # Keep every fingerprint field stable across overlapping/retried beat
        # deliveries. ``created_at`` still records when intake actually won.
        observed_at=occurred_at,
        source_identity=f"persistent-task-scheduler:{task.id}",
        source_version=str(task.version),
        summary=f"Scheduled occurrence at {occurred_at.isoformat()}.",
        cursor_after=occurred_at.isoformat(),
        idempotency_key=f"scheduled:{occurred_at.isoformat()}",
    )
    return intake_persistent_task_trigger(
        db,
        user_pk=task.user_id,
        task_id=task.id,
        command=command,
        cloud_sustainable_tool_names=cloud_sustainable_tool_names,
    )


def resolve_automation_run_request(
    db: Session,
    *,
    turn_id: str,
    cloud_sustainable_tool_names: Collection[str],
) -> AutomationRunRequest | None:
    """Resolve a pending/running automation from durable domain identities.

    The worker never trusts caller-supplied dispatch metadata or the serialized
    Turn message.  Trigger ownership identifies the PersistentTask; the task's
    current version and saved scopes then define the execution contract.
    """

    triggers = (
        db.query(PersistentTaskTrigger)
        .filter(PersistentTaskTrigger.admitted_turn_id == turn_id)
        .order_by(PersistentTaskTrigger.observed_at, PersistentTaskTrigger.id)
        .all()
    )
    if not triggers:
        return None
    task_ids = {row.persistent_task_id for row in triggers}
    if len(task_ids) != 1:
        raise PersistentTaskTriggerConflictError(
            "one automation Turn cannot belong to multiple PersistentTasks"
        )
    task = db.get(PersistentTask, next(iter(task_ids)))
    turn = db.get(ConversationTurn, turn_id)
    if (
        task is None
        or turn is None
        or task.user_id != turn.user_id
        or task.conversation_id != turn.conversation_id
    ):
        raise PersistentTaskTriggerConflictError(
            "automation trigger, task, and Turn ownership do not match"
        )
    saved_tools = tuple(sorted(task.allowed_tool_names_json or []))
    current_tools = set(cloud_sustainable_tool_names)
    missing_tools = tuple(name for name in saved_tools if name not in current_tools)
    tools = tuple(name for name in saved_tools if name in current_tools)
    return AutomationRunRequest(
        persistent_task_id=task.id,
        conversation_id=task.conversation_id,
        turn_id=turn.id,
        user_id=task.user_id,
        definition_version=int(task.version),
        instruction=task.instruction,
        input_message=_compile_automation_input(task, triggers),
        trigger_ids=tuple(row.id for row in triggers),
        allowed_tool_names=tools,
        read_scope=tuple(task.read_scope_json or []),
        action_scope=tuple(task.action_scope_json or []),
        validation_error=(
            "cloud_tool_unavailable:" + ",".join(missing_tools)
            if missing_tools
            else None
        ),
    )


def repairable_automation_turn_ids(
    db: Session,
    *,
    stale_before: datetime,
    limit: int = 100,
) -> list[str]:
    """Return a bounded batch of admitted automation Turns needing dispatch.

    A pending Turn is safe to re-dispatch because the existing worker claim is
    a status CAS.  The trigger join excludes ordinary user Turns without
    introducing another run/status table.
    """

    return [
        row_id
        for (row_id,) in (
            db.query(ConversationTurn.id)
            .join(
                PersistentTaskTrigger,
                PersistentTaskTrigger.admitted_turn_id == ConversationTurn.id,
            )
            .join(
                Conversation,
                Conversation.id == ConversationTurn.conversation_id,
            )
            .filter(
                ConversationTurn.status == "pending",
                ConversationTurn.created_at < stale_before,
                Conversation.active_turn_id == ConversationTurn.id,
            )
            .distinct()
            .order_by(ConversationTurn.created_at, ConversationTurn.id)
            .limit(max(1, min(int(limit), 500)))
            .all()
        )
    ]


def repairable_persistent_task_ids(
    db: Session,
    *,
    limit: int = 100,
) -> list[str]:
    """Return active definitions with retained triggers and no active Turn."""

    return [
        task_id
        for (task_id,) in (
            db.query(PersistentTask.id)
            .join(
                PersistentTaskTrigger,
                PersistentTaskTrigger.persistent_task_id == PersistentTask.id,
            )
            .join(Conversation, Conversation.id == PersistentTask.conversation_id)
            .filter(
                PersistentTask.state == "active",
                PersistentTaskTrigger.admitted_at.is_(None),
                Conversation.active_turn_id.is_(None),
                Conversation.archived_at.is_(None),
            )
            .distinct()
            .order_by(PersistentTask.updated_at, PersistentTask.id)
            .limit(max(1, min(int(limit), 500)))
            .all()
        )
    ]


def settle_automation_turn_and_admit_next(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    turn_id: str,
    terminal_status: Literal["completed", "blocked", "failed", "cancelled"],
    error: str | None,
    cloud_sustainable_tool_names: Collection[str],
    user_stopped: bool = False,
    owner_id: str | None = None,
    dispatch_generation: int | None = None,
) -> AutomationAdmission:
    """Terminalize an Automation Turn and arbitrate the next ingress atomically.

    This is the PersistentTask runner's completion seam.  It uses the same
    Dedicated Conversation lock/active-turn CAS as ordinary admission, gives a
    pending user submission precedence through the existing Kernel claim
    helper, and otherwise admits at most one merged automation Turn.  Waiting
    is deliberately not handled here: waiting retains the active Turn and only
    releases compute through the existing Kernel path.
    """

    task = _locked_task(db, user_pk, task_id)
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == task.conversation_id,
            Conversation.user_id == user_pk,
        )
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    turn = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.id == turn_id,
            ConversationTurn.conversation_id == task.conversation_id,
            ConversationTurn.user_id == user_pk,
        )
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if conversation is None or turn is None:
        raise PersistentTaskNotFoundError(turn_id)
    if conversation.active_turn_id != turn.id:
        if turn.status == terminal_status:
            return AutomationAdmission(
                trigger_id=None,
                status="empty",
                reason="already_terminal",
                turn_id=None,
                merged_trigger_ids=(),
                pending_trigger_count=_pending_trigger_count(db, task.id),
            )
        raise PersistentTaskTriggerConflictError("automation Turn lost active CAS")
    if turn.status not in {"pending", "running", "waiting"}:
        raise PersistentTaskTriggerConflictError(
            f"cannot terminalize automation Turn in {turn.status}"
        )
    if owner_id is not None and turn.owner_id != owner_id:
        raise PersistentTaskTriggerConflictError("automation Turn lost worker lease")
    if dispatch_generation is not None and int(turn.dispatch_generation or 1) != int(
        dispatch_generation
    ):
        raise PersistentTaskTriggerConflictError(
            "automation Turn dispatch generation is stale"
        )

    now = utc_now()
    turn.status = terminal_status
    turn.waiting_reason = None
    turn.error = error
    turn.owner_id = None
    turn.heartbeat_at = None
    turn.completed_at = now
    conversation.active_turn_id = None
    if user_stopped:
        task.compensation_blocked_at = now
        task.updated_at = now
    db.add_all([turn, conversation, task])
    from app.services.chat.agent_task_service import freeze_agent_task_for_terminal_turn

    freeze_agent_task_for_terminal_turn(db, turn_id=turn.id)
    db.flush()

    # Reuse the existing user FIFO claim under the same already-held
    # Conversation lock.  Automation never reads or consumes its payload.
    from app.services.chat.turn_executor import (
        _claim_next_submission_locked,
        _claim_selected_submission_locked,
    )

    if turn.interrupt_submission_id is not None:
        user_turn = _claim_selected_submission_locked(
            db,
            conversation,
            submission_id=turn.interrupt_submission_id,
            expected_version=int(turn.interrupt_submission_version or 0),
        )
    else:
        user_turn = _claim_next_submission_locked(db, conversation)
    turn.interrupt_submission_id = None
    turn.interrupt_submission_version = None
    if user_turn is not None:
        return AutomationAdmission(
            trigger_id=None,
            status="pending",
            reason="user_submission_admitted_first",
            turn_id=user_turn.id,
            merged_trigger_ids=(),
            pending_trigger_count=_pending_trigger_count(db, task.id),
            should_dispatch=True,
            run_request=None,
            user_turn_dispatch_id=user_turn.id,
        )
    if user_stopped:
        return AutomationAdmission(
            trigger_id=None,
            status="pending",
            reason="stopped_run_waits_for_next_trigger",
            turn_id=None,
            merged_trigger_ids=(),
            pending_trigger_count=_pending_trigger_count(db, task.id),
        )
    pending_count = _pending_trigger_count(db, task.id)
    if task.state != "active":
        return AutomationAdmission(
            trigger_id=None,
            status="pending",
            reason="task_paused",
            turn_id=None,
            merged_trigger_ids=(),
            pending_trigger_count=pending_count,
        )
    if pending_count == 0:
        return AutomationAdmission(
            trigger_id=None,
            status="empty",
            reason=None,
            turn_id=None,
            merged_trigger_ids=(),
            pending_trigger_count=0,
        )
    return _attempt_admission_locked(
        db,
        task=task,
        trigger_id=None,
        cloud_sustainable_tool_names=cloud_sustainable_tool_names,
    )


def latest_persistent_task_cursor(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
) -> str | None:
    task = _owned_task(db, user_pk, task_id)
    return (
        db.query(PersistentTaskTrigger.cursor_after)
        .filter(
            PersistentTaskTrigger.persistent_task_id == task.id,
            PersistentTaskTrigger.cursor_after.is_not(None),
        )
        .order_by(
            PersistentTaskTrigger.observed_at.desc(),
            PersistentTaskTrigger.id.desc(),
        )
        .limit(1)
        .scalar()
    )


def _attempt_admission_locked(
    db: Session,
    *,
    task: PersistentTask,
    trigger_id: str | None,
    cloud_sustainable_tool_names: Collection[str],
) -> AutomationAdmission:
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == task.conversation_id,
            Conversation.user_id == task.user_id,
            Conversation.archived_at.is_(None),
        )
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if conversation is None:
        raise PersistentTaskNotFoundError(task.conversation_id)

    pending = _pending_triggers_locked(db, task.id)
    if not pending:
        return AutomationAdmission(
            trigger_id=trigger_id,
            status="empty",
            reason=None,
            turn_id=None,
            merged_trigger_ids=(),
            pending_trigger_count=0,
        )

    active = _active_turn_locked(db, conversation)
    if active is not None:
        return _pending_admission(
            trigger_id,
            pending,
            reason="active_or_waiting_turn",
            turn_id=active.id,
        )

    # PendingSubmission remains the sole ordinary-user ingress record.  We do
    # not claim, consume, or copy it into automation intake; its mere presence
    # wins arbitration and keeps every trigger retained for a later check.
    user_pending = (
        db.query(PendingSubmission.id)
        .filter(
            PendingSubmission.conversation_id == conversation.id,
            PendingSubmission.status.in_(("pending", "failed")),
        )
        .order_by(PendingSubmission.position, PendingSubmission.id)
        .with_for_update()
        .first()
    )
    if user_pending is not None:
        return _pending_admission(
            trigger_id,
            pending,
            reason="user_submission_precedes_automation",
        )

    blocked_at = task.compensation_blocked_at
    if blocked_at is not None and not any(
        occurrence.observed_at > blocked_at for occurrence in pending
    ):
        return _pending_admission(
            trigger_id,
            pending,
            reason="stopped_run_waits_for_next_trigger",
        )

    requested_tools = tuple(sorted(task.allowed_tool_names_json or []))
    current_cloud_tools = set(cloud_sustainable_tool_names)
    missing_tools = [
        name for name in requested_tools if name not in current_cloud_tools
    ]
    if missing_tools:
        return _pending_admission(
            trigger_id,
            pending,
            reason="cloud_tool_unavailable:" + ",".join(missing_tools),
        )

    now = utc_now()
    if blocked_at is not None:
        task.compensation_blocked_at = None
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=task.user_id,
        submission_id=None,
        mode="agent",
        # PersistentTask definitions own their own visible action scope. The
        # Turn still passes through per-call Policy and hard-deny checks.
        execution_mode="auto",
        message=_compile_automation_input(task, pending),
        question_indexes_json=[],
        attachments_json=[],
        status="pending",
    )
    db.add(turn)
    db.flush()
    for occurrence in pending:
        occurrence.admitted_turn_id = turn.id
        occurrence.admitted_at = now
        db.add(occurrence)
    conversation.active_turn_id = turn.id
    conversation.updated_at = now
    db.add(conversation)
    db.flush()

    trigger_ids = tuple(occurrence.id for occurrence in pending)
    request = AutomationRunRequest(
        persistent_task_id=task.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        user_id=task.user_id,
        definition_version=int(task.version),
        instruction=task.instruction,
        input_message=_compile_automation_input(task, pending),
        trigger_ids=trigger_ids,
        allowed_tool_names=requested_tools,
        read_scope=tuple(task.read_scope_json or []),
        action_scope=tuple(task.action_scope_json or []),
    )
    return AutomationAdmission(
        trigger_id=trigger_id,
        status="admitted",
        reason=None,
        turn_id=turn.id,
        merged_trigger_ids=trigger_ids,
        pending_trigger_count=0,
        should_dispatch=True,
        run_request=request,
    )


def _pending_admission(
    trigger_id: str | None,
    pending: list[PersistentTaskTrigger],
    *,
    reason: str,
    turn_id: str | None = None,
) -> AutomationAdmission:
    return AutomationAdmission(
        trigger_id=trigger_id,
        status="pending",
        reason=reason,
        turn_id=turn_id,
        merged_trigger_ids=(),
        pending_trigger_count=len(pending),
    )


def _pending_triggers_locked(
    db: Session,
    task_id: str,
) -> list[PersistentTaskTrigger]:
    return (
        db.query(PersistentTaskTrigger)
        .filter(
            PersistentTaskTrigger.persistent_task_id == task_id,
            PersistentTaskTrigger.admitted_at.is_(None),
        )
        .order_by(
            PersistentTaskTrigger.observed_at.asc(),
            PersistentTaskTrigger.id.asc(),
        )
        .with_for_update()
        .all()
    )


def _pending_trigger_count(db: Session, task_id: str) -> int:
    return (
        db.query(PersistentTaskTrigger)
        .filter(
            PersistentTaskTrigger.persistent_task_id == task_id,
            PersistentTaskTrigger.admitted_at.is_(None),
        )
        .count()
    )


def _compile_automation_input(
    task: PersistentTask,
    triggers: list[PersistentTaskTrigger],
) -> str:
    payload = {
        "kind": "persistent_task_automation",
        "persistent_task_id": task.id,
        "definition_version": int(task.version),
        "instruction": task.instruction,
        "read_scope": list(task.read_scope_json or []),
        "action_scope": list(task.action_scope_json or []),
        "allowed_tool_names": sorted(task.allowed_tool_names_json or []),
        "triggers": [
            {
                "id": occurrence.id,
                "kind": occurrence.kind,
                "occurred_at": occurrence.occurred_at.isoformat(),
                "observed_at": occurrence.observed_at.isoformat(),
                "source_identity": occurrence.source_identity,
                "source_version": occurrence.source_version,
                "summary": occurrence.summary,
                "cursor_after": occurrence.cursor_after,
            }
            for occurrence in triggers
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _validate_requested_tools(
    requested: Collection[str],
    cloud_sustainable: Collection[str],
) -> tuple[str, ...]:
    normalized = tuple(sorted({name.strip() for name in requested if name.strip()}))
    available = set(cloud_sustainable)
    missing = [name for name in normalized if name not in available]
    if missing:
        raise PersistentTaskToolScopeError(
            "PersistentTask requires cloud-sustainable concrete Tools: "
            + ", ".join(missing)
        )
    return normalized


def _require_implemented_trigger(kind: str) -> None:
    if kind != "scheduled":
        raise PersistentTaskUnsupportedTriggerError(
            "event connector triggers are not available"
        )


def _next_due_for_trigger(trigger: object, *, after: datetime) -> datetime | None:
    if getattr(trigger, "kind", None) != "scheduled":
        return None
    from app.services.persistent_task_schedule import next_cron_occurrence

    return next_cron_occurrence(
        str(getattr(trigger, "schedule")),
        str(getattr(trigger, "timezone")),
        after,
    )


def _next_due_from_saved_spec(
    task: PersistentTask,
    *,
    after: datetime,
) -> datetime | None:
    if task.trigger_kind != "scheduled":
        return None
    spec = dict(task.trigger_spec_json or {})
    from app.services.persistent_task_schedule import next_cron_occurrence

    try:
        return next_cron_occurrence(
            str(spec["schedule"]),
            str(spec["timezone"]),
            after,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PersistentTaskTriggerConflictError(
            "saved scheduled trigger definition is invalid"
        ) from exc


def _creation_fingerprint(
    command: PersistentTaskCreate,
    tools: tuple[str, ...],
) -> str:
    payload = {
        "title": command.title.strip(),
        "instruction": command.instruction.strip(),
        "trigger": command.trigger.model_dump(mode="json"),
        "read_scope": list(command.read_scope),
        "action_scope": list(command.action_scope),
        "allowed_tool_names": list(tools),
        "user_request_identity": command.user_request_identity.strip(),
        "user_request_version": _optional_text(command.user_request_version),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _trigger_fingerprint(
    command: PersistentTaskTriggerInput,
) -> str:
    payload = {
        "kind": command.kind,
        "occurred_at": command.occurred_at.isoformat(),
        "observed_at": command.observed_at.isoformat()
        if command.observed_at is not None
        else None,
        "source_identity": command.source_identity.strip(),
        "source_version": _optional_text(command.source_version),
        "summary": command.summary.strip(),
        "cursor_after": _optional_text(command.cursor_after),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _locked_task(db: Session, user_pk: int, task_id: str) -> PersistentTask:
    task = (
        db.query(PersistentTask)
        .filter(PersistentTask.id == task_id, PersistentTask.user_id == user_pk)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if task is None:
        raise PersistentTaskNotFoundError(task_id)
    return task


def _owned_task(db: Session, user_pk: int, task_id: str) -> PersistentTask:
    task = (
        db.query(PersistentTask)
        .filter(PersistentTask.id == task_id, PersistentTask.user_id == user_pk)
        .one_or_none()
    )
    if task is None:
        raise PersistentTaskNotFoundError(task_id)
    return task


def _require_version(task: PersistentTask, expected_version: int) -> None:
    if int(task.version) != expected_version:
        raise PersistentTaskVersionConflictError(
            f"expected version {expected_version}, found {task.version}"
        )


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


__all__ = [
    "AutomationAdmission",
    "AutomationRunRequest",
    "AutomationRunner",
    "PersistentTaskError",
    "PersistentTaskDeleteConflictError",
    "PersistentTaskDeleteResult",
    "PersistentTaskIdempotencyConflictError",
    "PersistentTaskNotFoundError",
    "PersistentTaskPausedError",
    "PersistentTaskToolScopeError",
    "PersistentTaskTriggerConflictError",
    "PersistentTaskUnsupportedTriggerError",
    "PersistentTaskVersionConflictError",
    "admit_pending_persistent_task_triggers",
    "change_persistent_task_state",
    "create_persistent_task",
    "create_user_confirmed_manual_trigger",
    "dispatch_automation_run",
    "due_persistent_task_ids",
    "delete_persistent_task",
    "get_persistent_task",
    "intake_persistent_task_trigger",
    "latest_persistent_task_cursor",
    "list_persistent_task_triggers",
    "list_persistent_tasks",
    "record_user_stopped_automation_run",
    "repairable_automation_turn_ids",
    "repairable_persistent_task_ids",
    "resolve_automation_run_request",
    "settle_automation_turn_and_admit_next",
    "schedule_due_persistent_task",
    "update_persistent_task",
]
