from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.db.database import Base
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.pending_submission import PendingSubmission
from app.models.persistent_task import PersistentTask, PersistentTaskTrigger
from app.models.user import User
from app.schemas.persistent_task import (
    PersistentTaskCreate,
    PersistentTaskDelete,
    PersistentTaskStateChange,
    PersistentTaskTriggerInput,
    PersistentTaskUpdate,
)
from app.services.chat import turn_executor
from app.services.persistent_task_service import (
    PersistentTaskIdempotencyConflictError,
    PersistentTaskDeleteConflictError,
    PersistentTaskNotFoundError,
    PersistentTaskPausedError,
    PersistentTaskToolScopeError,
    PersistentTaskTriggerConflictError,
    PersistentTaskVersionConflictError,
    PersistentTaskUnsupportedTriggerError,
    admit_pending_persistent_task_triggers,
    change_persistent_task_state,
    create_persistent_task,
    create_user_confirmed_manual_trigger,
    dispatch_automation_run,
    due_persistent_task_ids,
    delete_persistent_task,
    intake_persistent_task_trigger,
    latest_persistent_task_cursor,
    list_persistent_task_triggers,
    list_persistent_tasks,
    record_user_stopped_automation_run,
    repairable_automation_turn_ids,
    resolve_automation_run_request,
    schedule_due_persistent_task,
    settle_automation_turn_and_admit_next,
    update_persistent_task,
)


NOW = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)
CLOUD_TOOLS = {"web_search", "read_url", "search_jobs"}


def _user(db_session, username: str = "automation-owner") -> User:
    user = User(username=username, hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return user


def _task_command(**overrides) -> PersistentTaskCreate:
    values = {
        "title": "每日求职邮件检查",
        "instruction": "每天检查新的求职邮件，并汇报需要我决定的事项。",
        "trigger": {
            "kind": "scheduled",
            "schedule": "0 9 * * *",
            "timezone": "Asia/Shanghai",
        },
        "read_scope": ["connected_mailbox:primary:inbox"],
        "action_scope": ["read_and_summarize"],
        "allowed_tool_names": ["web_search"],
        "user_request_identity": "message-create-automation",
        "idempotency_key": "create-mail-automation",
    }
    values.update(overrides)
    return PersistentTaskCreate(**values)


def _create(db_session, user: User, **overrides) -> PersistentTask:
    return create_persistent_task(
        db_session,
        user_pk=user.id,
        command=_task_command(**overrides),
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )


def _trigger(
    identity: str,
    *,
    kind: str = "scheduled",
    observed_at: datetime | None = None,
    cursor: str | None = None,
    **overrides,
) -> PersistentTaskTriggerInput:
    values = {
        "kind": kind,
        "occurred_at": observed_at or NOW,
        "observed_at": observed_at or NOW,
        "source_identity": identity,
        "summary": f"automation occurrence {identity}",
        "cursor_after": cursor,
        "idempotency_key": identity,
    }
    values.update(overrides)
    return PersistentTaskTriggerInput(**values)


def _intake(db_session, user: User, task: PersistentTask, command, *, tools=None):
    return intake_persistent_task_trigger(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        command=command,
        cloud_sustainable_tool_names=CLOUD_TOOLS if tools is None else tools,
    )


def test_create_task_owns_one_dedicated_conversation_and_is_idempotent(db_session):
    user = _user(db_session)

    task = _create(db_session, user)
    retried = _create(db_session, user)

    assert retried.id == task.id
    assert task.state == "active"
    assert task.version == 1
    assert task.allowed_tool_names_json == ["web_search"]
    conversation = db_session.get(Conversation, task.conversation_id)
    assert conversation is not None
    assert conversation.user_id == user.id
    assert conversation.type == "persistent_task"
    assert conversation.mode == "agent"
    assert conversation.active_turn_id is None
    assert db_session.query(ConversationTurn).count() == 0
    messages = (
        db_session.query(ConversationMessage)
        .filter_by(conversation_id=conversation.id)
        .all()
    )
    assert [(row.seq, row.role, row.content) for row in messages] == [
        (1, "User", task.instruction)
    ]

    with pytest.raises(PersistentTaskIdempotencyConflictError):
        _create(db_session, user, instruction="同一创建 key 的不同长期目标")
    with pytest.raises(PersistentTaskToolScopeError):
        _create(
            db_session,
            user,
            idempotency_key="create-local-tool-task",
            allowed_tool_names=["write_file"],
        )
    assert db_session.query(PersistentTask).count() == 1
    assert db_session.query(Conversation).count() == 1

    with pytest.raises(PersistentTaskUnsupportedTriggerError):
        _create(
            db_session,
            user,
            idempotency_key="event-without-connector",
            trigger={
                "kind": "event",
                "connector": "gmail",
                "event_types": ["message.received"],
            },
        )


def test_create_retry_survives_later_definition_update(db_session):
    user = _user(db_session)
    task = _create(db_session, user)
    update_persistent_task(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        command=PersistentTaskUpdate(
            expected_version=1,
            instruction="每天检查邮件，只汇报需要我决定的事项。",
            user_request_identity="message-update-task",
        ),
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )

    retry = _create(db_session, user)

    assert retry.id == task.id
    assert retry.version == 2
    assert retry.instruction == "每天检查邮件，只汇报需要我决定的事项。"
    original = (
        db_session.query(ConversationMessage)
        .filter_by(conversation_id=task.conversation_id, seq=1)
        .one()
    )
    assert original.content == _task_command().instruction


def test_trigger_admits_one_authoritative_turn_and_runner_is_post_commit_seam(
    db_session,
):
    user = _user(db_session)
    task = _create(db_session, user)
    command = _trigger("tick-2026-08-13", cursor="mail-cursor-7")

    admission = _intake(db_session, user, task, command)

    assert admission.status == "admitted"
    assert admission.should_dispatch is True
    assert admission.turn_id is not None
    assert len(admission.merged_trigger_ids) == 1
    turn = db_session.get(ConversationTurn, admission.turn_id)
    conversation = db_session.get(Conversation, task.conversation_id)
    trigger = db_session.get(PersistentTaskTrigger, admission.trigger_id)
    assert turn is not None and turn.submission_id is None
    assert turn.status == "pending"
    assert conversation.active_turn_id == turn.id
    assert trigger.admitted_turn_id == turn.id
    hidden_input = json.loads(turn.message)
    assert hidden_input["kind"] == "persistent_task_automation"
    assert hidden_input["triggers"][0]["source_identity"] == "tick-2026-08-13"
    assert db_session.query(PendingSubmission).count() == 0
    assert db_session.query(ConversationMessage).count() == 1

    dispatched = []
    db_session.commit()
    assert dispatch_automation_run(admission, dispatched.append) is True
    assert dispatched[0].turn_id == turn.id
    assert dispatched[0].allowed_tool_names == ("web_search",)

    retried = _intake(db_session, user, task, command)
    assert retried.status == "already_admitted"
    assert retried.should_dispatch is False
    assert dispatch_automation_run(retried, dispatched.append) is False
    assert len(dispatched) == 1
    assert (
        latest_persistent_task_cursor(
            db_session,
            user_pk=user.id,
            task_id=task.id,
        )
        == "mail-cursor-7"
    )

    with pytest.raises(PersistentTaskIdempotencyConflictError):
        _intake(
            db_session,
            user,
            task,
            _trigger("tick-2026-08-13", summary="different occurrence"),
        )


def test_worker_resolves_current_task_contract_from_trigger_identity(db_session):
    user = _user(db_session)
    task = _create(db_session, user)
    admission = _intake(db_session, user, task, _trigger("worker-contract"))

    update_persistent_task(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        command=PersistentTaskUpdate(
            expected_version=1,
            instruction="只读取并汇报新增岗位。",
            allowed_tool_names=["read_url"],
            user_request_identity="definition-update-before-worker-claim",
        ),
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )
    request = resolve_automation_run_request(
        db_session,
        turn_id=admission.turn_id,
        cloud_sustainable_tool_names={"read_url"},
    )

    assert request is not None
    assert request.persistent_task_id == task.id
    assert request.definition_version == 2
    assert request.instruction == "只读取并汇报新增岗位。"
    assert request.allowed_tool_names == ("read_url",)
    assert request.validation_error is None
    assert json.loads(request.input_message)["definition_version"] == 2

    unavailable = resolve_automation_run_request(
        db_session,
        turn_id=admission.turn_id,
        cloud_sustainable_tool_names=set(),
    )
    assert unavailable is not None
    assert unavailable.allowed_tool_names == ()
    assert unavailable.validation_error == "cloud_tool_unavailable:read_url"


def test_pending_automation_dispatch_repair_is_bounded_and_excludes_user_turns(
    db_session,
):
    user = _user(db_session)
    task = _create(db_session, user)
    admission = _intake(db_session, user, task, _trigger("repair-contract"))
    turn = db_session.get(ConversationTurn, admission.turn_id)
    turn.created_at = NOW - timedelta(minutes=5)

    other_conversation = Conversation(
        id="ordinary-repair-conversation",
        user_id=user.id,
        title="ordinary",
        type="general",
        active_turn_id="ordinary-repair-turn",
    )
    ordinary = ConversationTurn(
        id="ordinary-repair-turn",
        conversation_id=other_conversation.id,
        user_id=user.id,
        mode="agent",
        message="ordinary",
        status="pending",
        created_at=NOW - timedelta(minutes=5),
    )
    db_session.add_all([other_conversation, ordinary])
    db_session.flush()

    assert repairable_automation_turn_ids(
        db_session,
        stale_before=NOW - timedelta(minutes=1),
        limit=1,
    ) == [admission.turn_id]


def test_waiting_turn_releases_compute_and_merges_later_triggers_once(db_session):
    user = _user(db_session)
    task = _create(db_session, user)
    first = _intake(db_session, user, task, _trigger("tick-1"))
    turn = db_session.get(ConversationTurn, first.turn_id)
    turn.status = "waiting"
    turn.waiting_reason = "approval"
    turn.owner_id = None
    turn.heartbeat_at = None
    db_session.flush()

    second = _intake(
        db_session,
        user,
        task,
        _trigger("tick-2", observed_at=NOW + timedelta(minutes=1)),
    )
    third = _intake(
        db_session,
        user,
        task,
        _trigger("tick-3", observed_at=NOW + timedelta(minutes=2)),
    )

    assert second.status == third.status == "pending"
    assert third.reason == "active_or_waiting_turn"
    assert third.pending_trigger_count == 2
    assert db_session.query(ConversationTurn).count() == 1
    assert turn.status == "waiting"
    assert turn.owner_id is None and turn.heartbeat_at is None

    turn.status = "completed"
    turn.completed_at = NOW + timedelta(minutes=3)
    conversation = db_session.get(Conversation, task.conversation_id)
    conversation.active_turn_id = None
    merged = admit_pending_persistent_task_triggers(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )

    assert merged.status == "admitted"
    assert len(merged.merged_trigger_ids) == 2
    assert db_session.query(ConversationTurn).count() == 2
    admitted_rows = list_persistent_task_triggers(
        db_session,
        user_pk=user.id,
        task_id=task.id,
    )
    assert [row.admitted_turn_id for row in admitted_rows[1:]] == [
        merged.turn_id,
        merged.turn_id,
    ]


def test_user_pending_submission_wins_without_entering_trigger_intake(db_session):
    user = _user(db_session)
    task = _create(db_session, user)
    conversation = db_session.get(Conversation, task.conversation_id)
    submission = PendingSubmission(
        id="user-submission-1",
        conversation_id=conversation.id,
        user_id=user.id,
        version=1,
        position=1,
        status="pending",
        message="先修改这项自动化的范围",
        mode="agent",
        question_indexes_json=[],
        attachments_json=[],
    )
    db_session.add(submission)
    db_session.flush()

    trigger_admission = _intake(db_session, user, task, _trigger("tick-held"))

    assert trigger_admission.status == "pending"
    assert trigger_admission.reason == "user_submission_precedes_automation"
    assert db_session.query(PendingSubmission).count() == 1
    assert db_session.query(PersistentTaskTrigger).count() == 1
    assert db_session.query(ConversationTurn).count() == 0

    user_turn = turn_executor._create_turn_from_submission_locked(
        db_session,
        conversation,
        submission,
    )
    assert conversation.active_turn_id == user_turn.id
    assert user_turn.submission_id == submission.id
    still_held = admit_pending_persistent_task_triggers(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )
    assert still_held.reason == "active_or_waiting_turn"

    user_turn.status = "completed"
    conversation.active_turn_id = None
    automation = admit_pending_persistent_task_triggers(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )
    assert automation.status == "admitted"
    assert db_session.get(
        PersistentTaskTrigger, trigger_admission.trigger_id
    ).admitted_turn_id == (automation.turn_id)


def test_automation_terminal_handoff_reuses_user_fifo_before_compensation(db_session):
    user = _user(db_session)
    task = _create(db_session, user)
    current = _intake(db_session, user, task, _trigger("tick-current"))
    held = _intake(
        db_session,
        user,
        task,
        _trigger("tick-held", observed_at=NOW + timedelta(minutes=1)),
    )
    assert held.status == "pending"
    conversation = db_session.get(Conversation, task.conversation_id)
    submission = PendingSubmission(
        id="user-before-compensation",
        conversation_id=conversation.id,
        user_id=user.id,
        version=1,
        position=1,
        status="pending",
        message="先调整任务范围",
        mode="agent",
        question_indexes_json=[],
        attachments_json=[],
    )
    db_session.add(submission)
    db_session.flush()

    handoff = settle_automation_turn_and_admit_next(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        turn_id=current.turn_id,
        terminal_status="completed",
        error=None,
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )

    assert handoff.reason == "user_submission_admitted_first"
    assert handoff.should_dispatch is True
    assert handoff.run_request is None
    assert handoff.user_turn_dispatch_id == handoff.turn_id
    assert dispatch_automation_run(handoff, lambda _request: None) is False
    user_turn = db_session.get(ConversationTurn, handoff.turn_id)
    assert user_turn.submission_id == submission.id
    assert db_session.get(PersistentTaskTrigger, held.trigger_id).admitted_at is None
    assert db_session.query(ConversationTurn).count() == 2

    user_turn.status = "running"
    user_turn.owner_id = "user-turn-worker"
    db_session.flush()
    changed, compensation_turn_id = turn_executor._terminalize(
        db_session,
        user_turn.id,
        allowed_statuses={"running"},
        status="completed",
        error=None,
        owner_id="user-turn-worker",
    )
    assert changed is True
    assert compensation_turn_id is not None
    assert db_session.get(PersistentTaskTrigger, held.trigger_id).admitted_turn_id == (
        compensation_turn_id
    )


def test_clean_automation_completion_does_not_create_an_empty_compensation_turn(
    db_session,
):
    user = _user(db_session)
    task = _create(db_session, user)
    current = _intake(db_session, user, task, _trigger("tick-only"))

    settled = settle_automation_turn_and_admit_next(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        turn_id=current.turn_id,
        terminal_status="completed",
        error=None,
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )

    assert settled.status == "empty"
    assert settled.should_dispatch is False
    assert db_session.query(ConversationTurn).count() == 1
    assert db_session.get(Conversation, task.conversation_id).active_turn_id is None


def test_automation_settlement_is_worker_and_generation_fenced(db_session):
    user = _user(db_session)
    task = _create(db_session, user)
    current = _intake(db_session, user, task, _trigger("tick-fenced"))
    turn = db_session.get(ConversationTurn, current.turn_id)
    turn.status = "running"
    turn.owner_id = "automation-worker"
    turn.dispatch_generation = 2
    db_session.flush()

    with pytest.raises(PersistentTaskTriggerConflictError):
        settle_automation_turn_and_admit_next(
            db_session,
            user_pk=user.id,
            task_id=task.id,
            turn_id=turn.id,
            terminal_status="completed",
            error=None,
            cloud_sustainable_tool_names=CLOUD_TOOLS,
            owner_id="other-worker",
            dispatch_generation=2,
        )
    with pytest.raises(PersistentTaskTriggerConflictError):
        settle_automation_turn_and_admit_next(
            db_session,
            user_pk=user.id,
            task_id=task.id,
            turn_id=turn.id,
            terminal_status="completed",
            error=None,
            cloud_sustainable_tool_names=CLOUD_TOOLS,
            owner_id="automation-worker",
            dispatch_generation=1,
        )

    settled = settle_automation_turn_and_admit_next(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        turn_id=turn.id,
        terminal_status="completed",
        error=None,
        cloud_sustainable_tool_names=CLOUD_TOOLS,
        owner_id="automation-worker",
        dispatch_generation=2,
    )
    assert settled.status == "empty"
    assert turn.status == "completed"


def test_pause_and_definition_version_do_not_cancel_current_turn(db_session):
    user = _user(db_session)
    task = _create(db_session, user)
    admitted = _intake(db_session, user, task, _trigger("tick-running"))

    paused = change_persistent_task_state(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        command=PersistentTaskStateChange(
            expected_version=1,
            state="paused",
            user_request_identity="message-pause-task",
        ),
    )

    assert paused.state == "paused"
    assert paused.version == 2
    assert paused.user_request_identity == "message-pause-task"
    assert db_session.get(Conversation, task.conversation_id).active_turn_id == (
        admitted.turn_id
    )
    with pytest.raises(PersistentTaskPausedError):
        _intake(db_session, user, task, _trigger("tick-while-paused"))
    with pytest.raises(PersistentTaskVersionConflictError):
        change_persistent_task_state(
            db_session,
            user_pk=user.id,
            task_id=task.id,
            command=PersistentTaskStateChange(
                expected_version=1,
                state="active",
                user_request_identity="stale-resume",
            ),
        )

    resumed = change_persistent_task_state(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        command=PersistentTaskStateChange(
            expected_version=2,
            state="active",
            user_request_identity="message-resume-task",
        ),
    )
    assert resumed.state == "active" and resumed.version == 3
    assert db_session.get(ConversationTurn, admitted.turn_id).status == "pending"


def test_removed_cloud_tool_retains_trigger_until_real_definition_returns(db_session):
    user = _user(db_session)
    task = _create(db_session, user)

    deferred = _intake(
        db_session,
        user,
        task,
        _trigger("tick-tool-unavailable"),
        tools={"read_url"},
    )

    assert deferred.status == "pending"
    assert deferred.reason == "cloud_tool_unavailable:web_search"
    assert db_session.query(PersistentTaskTrigger).count() == 1
    assert db_session.query(ConversationTurn).count() == 0

    admitted = admit_pending_persistent_task_triggers(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )
    assert admitted.status == "admitted"


def test_user_stop_blocks_immediate_compensation_until_a_new_trigger(db_session):
    user = _user(db_session)
    task = _create(db_session, user)
    first = _intake(db_session, user, task, _trigger("tick-before-stop"))
    pending = _intake(
        db_session,
        user,
        task,
        _trigger("tick-merged-before-stop", observed_at=NOW + timedelta(minutes=1)),
    )
    assert pending.status == "pending"

    turn = db_session.get(ConversationTurn, first.turn_id)
    turn.status = "cancelled"
    turn.completed_at = NOW + timedelta(minutes=2)
    conversation = db_session.get(Conversation, task.conversation_id)
    conversation.active_turn_id = None
    record_user_stopped_automation_run(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        turn_id=turn.id,
        stopped_at=NOW + timedelta(minutes=2),
    )

    blocked = admit_pending_persistent_task_triggers(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )
    assert blocked.status == "pending"
    assert blocked.reason == "stopped_run_waits_for_next_trigger"
    assert db_session.query(ConversationTurn).count() == 1

    released = _intake(
        db_session,
        user,
        task,
        _trigger("tick-after-stop", observed_at=NOW + timedelta(minutes=3)),
    )
    assert released.status == "admitted"
    assert len(released.merged_trigger_ids) == 2
    assert task.compensation_blocked_at is None


def test_trigger_channel_owner_scope_and_no_duplicate_run_model(db_session):
    owner = _user(db_session, "persistent-owner")
    other = _user(db_session, "persistent-other")
    task = _create(db_session, owner)

    with pytest.raises(PersistentTaskTriggerConflictError):
        _intake(db_session, owner, task, _trigger("event-wrong", kind="event"))
    with pytest.raises(PersistentTaskTriggerConflictError):
        create_user_confirmed_manual_trigger(
            db_session,
            user_pk=owner.id,
            task_id=task.id,
            command=_trigger("fake-user-tick", kind="scheduled"),
            cloud_sustainable_tool_names=CLOUD_TOOLS,
        )
    manual = create_user_confirmed_manual_trigger(
        db_session,
        user_pk=owner.id,
        task_id=task.id,
        command=_trigger("manual-run", kind="manual"),
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )
    assert manual.status == "admitted"
    assert list_persistent_tasks(db_session, user_pk=other.id) == []
    with pytest.raises(PersistentTaskNotFoundError):
        list_persistent_task_triggers(
            db_session,
            user_pk=other.id,
            task_id=task.id,
        )
    assert "persistent_task_runs" not in Base.metadata.tables
    assert db_session.query(ConversationTurn).count() == 1


def test_due_scheduler_uses_stable_occurrence_and_advances_cursor(db_session):
    user = _user(db_session)
    task = _create(
        db_session,
        user,
        trigger={
            "kind": "scheduled",
            "schedule": "*/5 * * * *",
            "timezone": "Asia/Shanghai",
        },
    )
    original_due = task.next_due_at
    assert original_due is not None
    assert due_persistent_task_ids(db_session, due_at=original_due, limit=10) == [
        task.id
    ]

    admission = schedule_due_persistent_task(
        db_session,
        task_id=task.id,
        due_at=original_due + timedelta(seconds=30),
        cloud_sustainable_tool_names=CLOUD_TOOLS,
    )

    assert admission is not None and admission.status == "admitted"
    trigger = db_session.get(PersistentTaskTrigger, admission.trigger_id)
    assert trigger is not None
    assert trigger.source_identity == f"persistent-task-scheduler:{task.id}"
    assert trigger.idempotency_key == f"scheduled:{original_due.isoformat()}"
    assert task.next_due_at == original_due + timedelta(minutes=5)
    # An overlapping scheduler that scanned the same row before commit cannot
    # manufacture a second trigger once it obtains the task lock.
    assert (
        schedule_due_persistent_task(
            db_session,
            task_id=task.id,
            due_at=original_due + timedelta(seconds=30),
            cloud_sustainable_tool_names=CLOUD_TOOLS,
        )
        is None
    )
    assert db_session.query(PersistentTaskTrigger).count() == 1


def test_delete_cancels_pending_turn_and_removes_only_dedicated_scope(db_session):
    user = _user(db_session)
    task = _create(db_session, user)
    admission = _intake(db_session, user, task, _trigger("delete-pending"))
    conversation_id = task.conversation_id

    result = delete_persistent_task(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        command=PersistentTaskDelete(
            expected_version=1,
            user_request_identity="settings-delete-task",
        ),
    )
    db_session.commit()

    assert result.conversation_id == conversation_id
    assert db_session.get(PersistentTask, task.id) is None
    assert db_session.get(Conversation, conversation_id) is None
    assert db_session.get(ConversationTurn, admission.turn_id) is None


def test_delete_rejects_running_turn_to_preserve_reconciliation_identity(db_session):
    user = _user(db_session)
    task = _create(db_session, user)
    admission = _intake(db_session, user, task, _trigger("delete-running"))
    turn = db_session.get(ConversationTurn, admission.turn_id)
    turn.status = "running"
    turn.owner_id = "worker"

    with pytest.raises(PersistentTaskDeleteConflictError):
        delete_persistent_task(
            db_session,
            user_pk=user.id,
            task_id=task.id,
            command=PersistentTaskDelete(
                expected_version=1,
                user_request_identity="settings-delete-task",
            ),
        )
    assert db_session.get(PersistentTask, task.id) is task
    assert db_session.get(ConversationTurn, turn.id) is turn
