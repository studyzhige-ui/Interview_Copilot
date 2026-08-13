from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.pending_submission import PendingSubmission
from app.models.user import User
from app.services.chat import chat_history_service, turn_executor
from app.services.chat.attachment_ingress_service import (
    AttachmentDraftUnavailableError,
)


class _NonClosingSession:
    def __init__(self, session):
        self.session = session

    def __getattr__(self, name):
        return getattr(self.session, name)

    def close(self):
        pass


def test_turn_submission_fk_allows_ingress_cleanup():
    foreign_key = next(iter(ConversationTurn.__table__.c.submission_id.foreign_keys))
    assert foreign_key.ondelete == "SET NULL"


@pytest.mark.asyncio
async def test_fail_orphaned_turns_closes_active_rows(db_session, monkeypatch):
    user = User(username="turn-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="orphan-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="orphan-turn",
    )
    turn = ConversationTurn(
        id="orphan-turn",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="work",
        status="running",
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db_session.add_all([conversation, turn])
    db_session.commit()

    monkeypatch.setattr(
        turn_executor, "SessionLocal", lambda: _NonClosingSession(db_session)
    )
    monkeypatch.setattr(
        turn_executor.transcript_service,
        "complete_background_turn",
        lambda **_kwargs: 2,
    )
    events: list[str] = []

    async def append(_turn_id: str, event_json: str):
        events.append(event_json)

    monkeypatch.setattr(turn_executor.turn_event_buffer, "append", append)
    assert await turn_executor.fail_orphaned_turns() == 1

    db_session.refresh(turn)
    db_session.refresh(conversation)
    assert turn.status == "failed"
    assert conversation.active_turn_id is None
    assert [json.loads(event)["type"] for event in events] == ["error", "done"]


@pytest.mark.asyncio
async def test_fail_orphaned_turns_keeps_live_heartbeat(db_session, monkeypatch):
    user = User(username="live-turn-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="live-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="live-turn",
    )
    turn = ConversationTurn(
        id="live-turn",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="work",
        status="running",
        started_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
    )
    db_session.add_all([conversation, turn])
    db_session.commit()
    monkeypatch.setattr(
        turn_executor, "SessionLocal", lambda: _NonClosingSession(db_session)
    )

    assert await turn_executor.fail_orphaned_turns() == 0
    db_session.refresh(turn)
    assert turn.status == "running"


@pytest.mark.asyncio
async def test_execute_turn_marks_error_event_failed(monkeypatch):
    import app.conversation as conversation_module
    from app.conversation.events import HarnessEvent

    turn = turn_executor.TurnExecution(
        id="turn-error",
        mode="agent",
        conversation_id="session",
        message="work",
        username="alice",
    )
    monkeypatch.setattr(turn_executor, "_claim", lambda _turn_id: turn)
    marks: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        turn_executor,
        "_finish",
        lambda _turn_id, status, error=None: marks.append((status, error)) or True,
    )

    class FakeEngine:
        def __init__(self, **_kwargs):
            pass

        async def submit_message(self):
            yield HarnessEvent.error("model unavailable")
            yield HarnessEvent.done(step=0, elapsed_ms=0)

        async def persist_background_failure(self, _message: str):
            pass

    async def append(_turn_id: str, _event_json: str):
        return "1-0"

    monkeypatch.setattr(conversation_module, "ConversationEngine", FakeEngine)
    monkeypatch.setattr(conversation_module, "make_agent_strategy", lambda: object())
    monkeypatch.setattr(turn_executor.turn_event_buffer, "append", append)

    await turn_executor.execute_turn("turn-error")
    assert marks[-1] == ("failed", "model unavailable")


@pytest.mark.asyncio
async def test_execute_turn_preserves_authoritative_blocked_outcome(monkeypatch):
    import app.conversation as conversation_module
    from app.conversation.events import HarnessEvent

    turn = turn_executor.TurnExecution(
        id="turn-blocked",
        mode="agent",
        conversation_id="session",
        message="complex work",
        username="alice",
    )
    monkeypatch.setattr(turn_executor, "_claim", lambda _turn_id: turn)
    monkeypatch.setattr(turn_executor, "_has_assistant", lambda _turn_id: True)
    marks: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        turn_executor,
        "_finish",
        lambda _turn_id, status, error=None: marks.append((status, error)) or True,
    )

    class FakeEngine:
        outcome = "blocked"

        def __init__(self, **_kwargs):
            pass

        async def submit_message(self):
            # A diagnostic event must not override the Kernel outcome.
            yield HarnessEvent.error("completion gate retained partial results")
            yield HarnessEvent.done(step=3, elapsed_ms=1, outcome="blocked")

        async def persist_background_failure(self, _message: str):
            raise AssertionError("blocked is not failed")

    events: list[dict] = []

    async def append(_turn_id: str, event_json: str):
        events.append(json.loads(event_json))

    monkeypatch.setattr(conversation_module, "ConversationEngine", FakeEngine)
    monkeypatch.setattr(conversation_module, "make_agent_strategy", lambda: object())
    monkeypatch.setattr(turn_executor.turn_event_buffer, "append", append)

    await turn_executor.execute_turn(turn.id)

    assert marks == [("blocked", None)]
    assert events[-1]["data"]["outcome"] == "blocked"


@pytest.mark.asyncio
async def test_execute_automation_reuses_engine_with_frozen_builtin_allowlist(
    monkeypatch,
):
    import app.conversation as conversation_module
    from app.conversation.events import HarnessEvent

    turn = turn_executor.TurnExecution(
        id="automation-turn",
        mode="agent",
        conversation_id="automation-conversation",
        message='{"kind":"persistent_task_automation"}',
        username="alice",
        automation_task_id="pt_automation",
        automation_user_id=7,
        automation_definition_version=3,
        automation_tool_names=("read_url", "web_search"),
        execution_mode="auto",
    )
    monkeypatch.setattr(turn_executor, "_claim", lambda _turn_id: turn)
    monkeypatch.setattr(turn_executor, "_has_assistant", lambda _turn_id: True)
    settled: list[tuple[str, str, str | None]] = []
    monkeypatch.setattr(
        turn_executor,
        "_finish_automation",
        lambda claimed, status, error=None: (
            settled.append((claimed.id, status, error)) or True
        ),
    )
    engine_kwargs: dict = {}

    class FakeEngine:
        outcome = "completed"

        def __init__(self, **kwargs):
            engine_kwargs.update(kwargs)

        async def submit_message(self):
            yield HarnessEvent.done(step=0, elapsed_ms=0)

        async def persist_background_failure(self, _message: str):
            raise AssertionError("successful automation is not a failure")

    async def append(_turn_id: str, _event_json: str):
        return "1-0"

    monkeypatch.setattr(conversation_module, "ConversationEngine", FakeEngine)
    monkeypatch.setattr(conversation_module, "make_agent_strategy", lambda: object())
    monkeypatch.setattr(turn_executor.turn_event_buffer, "append", append)

    await turn_executor.execute_turn(turn.id)

    assert engine_kwargs["strategy_extras"] == {
        "execution_mode": "auto",
        "unattended_automation": True,
        "builtin_tool_allowlist": ("read_url", "web_search"),
        "persistent_task_id": "pt_automation",
        "persistent_task_definition_version": 3,
    }
    assert settled == [(turn.id, "completed", None)]


@pytest.mark.asyncio
async def test_execute_turn_waits_for_attachment_without_failing(monkeypatch):
    import app.conversation as conversation_module
    from app.rag.application.attachment_sources import AttachmentParsingPendingError

    turn = turn_executor.TurnExecution(
        id="turn-attachment-wait",
        mode="agent",
        conversation_id="session",
        message="review the file",
        username="alice",
        attachments=({"attachment_ref_id": "ref-1"},),
    )
    monkeypatch.setattr(turn_executor, "_claim", lambda _turn_id: turn)
    waits: list[tuple[str, str]] = []
    finishes: list[str] = []
    monkeypatch.setattr(
        turn_executor,
        "_wait",
        lambda turn_id, reason="interaction": waits.append((turn_id, reason)) or True,
    )
    monkeypatch.setattr(
        turn_executor,
        "_finish",
        lambda _turn_id, status, error=None: finishes.append(status) or True,
    )

    class FakeEngine:
        outcome = "waiting"

        def __init__(self, **_kwargs):
            pass

        async def submit_message(self):
            raise AttachmentParsingPendingError(
                attachment_ref_ids=("ref-1",), document_ids=("doc-1",)
            )
            yield  # pragma: no cover - keeps this an async generator

        async def persist_background_failure(self, _message: str):
            raise AssertionError("waiting is not a background failure")

    events: list[dict] = []

    async def append(_turn_id: str, event_json: str):
        events.append(json.loads(event_json))

    monkeypatch.setattr(conversation_module, "ConversationEngine", FakeEngine)
    monkeypatch.setattr(conversation_module, "make_agent_strategy", lambda: object())
    monkeypatch.setattr(turn_executor.turn_event_buffer, "append", append)

    await turn_executor.execute_turn(turn.id)

    assert waits == [(turn.id, "attachment_parsing")]
    assert finishes == []
    assert [event["type"] for event in events] == ["status", "done"]


def test_claim_and_finish_are_owner_fenced(db_session, monkeypatch):
    user = User(username="lease-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="lease-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="lease-turn",
    )
    turn = ConversationTurn(
        id="lease-turn",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="work",
        status="pending",
    )
    db_session.add_all([conversation, turn])
    db_session.commit()
    monkeypatch.setattr(
        turn_executor, "SessionLocal", lambda: _NonClosingSession(db_session)
    )

    claimed = turn_executor._claim(turn.id)
    assert claimed is not None
    assert turn_executor._claim(turn.id) is None
    db_session.refresh(turn)
    assert turn.status == "running"
    assert turn.owner_id == turn_executor._WORKER_ID

    turn.owner_id = "replacement-worker"
    db_session.commit()
    assert turn_executor._finish(turn.id, "completed") is False
    db_session.refresh(turn)
    assert turn.status == "running"


def test_terminalization_freezes_agent_task_in_same_transaction(
    db_session,
    monkeypatch,
):
    from app.schemas.agent_task import CreateAgentTaskRequest
    from app.services.chat.agent_task_service import create_agent_task

    user = User(username="task-freeze-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="task-freeze-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="task-freeze-turn",
    )
    turn = ConversationTurn(
        id="task-freeze-turn",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="complex work",
        status="running",
        owner_id=turn_executor._WORKER_ID,
    )
    db_session.add_all([conversation, turn])
    db_session.flush()
    task = create_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=CreateAgentTaskRequest(
            objective="Complex work",
            completion_conditions=["Done"],
            phases=[
                {"id": "one", "title": "One", "status": "in_progress"},
                {"id": "two", "title": "Two", "status": "pending"},
            ],
            idempotency_key="create-freeze-task",
        ),
    )
    db_session.commit()
    monkeypatch.setattr(
        turn_executor,
        "SessionLocal",
        lambda: _NonClosingSession(db_session),
    )

    assert turn_executor._finish(turn.id, "blocked") is True
    db_session.refresh(turn)
    db_session.refresh(task)
    assert turn.status == "blocked"
    assert task.frozen_at == turn.completed_at


def test_terminal_turn_atomically_claims_fifo_submission(db_session, monkeypatch):
    user = User(username="fifo-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="fifo-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="fifo-active",
    )
    active = ConversationTurn(
        id="fifo-active",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="current",
        status="running",
        owner_id=turn_executor._WORKER_ID,
    )
    first = PendingSubmission(
        id="fifo-first",
        conversation_id=conversation.id,
        user_id=user.id,
        version=1,
        position=1,
        status="pending",
        mode="agent",
        message="first queued",
        question_indexes_json=[],
        attachments_json=[],
    )
    second = PendingSubmission(
        id="fifo-second",
        conversation_id=conversation.id,
        user_id=user.id,
        version=1,
        position=2,
        status="pending",
        mode="agent",
        message="second queued",
        question_indexes_json=[],
        attachments_json=[],
    )
    db_session.add_all([conversation, active, first, second])
    db_session.commit()
    monkeypatch.setattr(
        turn_executor, "SessionLocal", lambda: _NonClosingSession(db_session)
    )
    dispatched: list[str] = []
    monkeypatch.setattr(turn_executor, "schedule_turn", dispatched.append)

    assert turn_executor._finish(active.id, "completed") is True

    db_session.expire_all()
    conversation = db_session.get(Conversation, conversation.id)
    first = db_session.get(PendingSubmission, first.id)
    second = db_session.get(PendingSubmission, second.id)
    assert first.status == "claimed"
    assert second.status == "pending"
    admitted = db_session.get(ConversationTurn, conversation.active_turn_id)
    assert admitted is not None and admitted.submission_id == first.id
    assert dispatched == [admitted.id]
    assert [
        (message.role, message.content)
        for message in (
            db_session.query(ConversationMessage)
            .filter_by(conversation_id=conversation.id)
            .order_by(ConversationMessage.seq)
            .all()
        )
    ] == [("User", "first queued")]


def test_complete_background_turn_is_idempotent(db_session, monkeypatch):
    user = User(username="transcript-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="reserved", user_id=user.id, title="T", type="general"
    )
    user_message = ConversationMessage(
        conversation_id="reserved",
        seq=1,
        role="User",
        content="question",
    )
    turn = ConversationTurn(
        id="reserved-turn",
        conversation_id="reserved",
        user_id=user.id,
        mode="chat",
        message="question",
        user_message_seq=1,
        status="running",
    )
    db_session.add_all([conversation, user_message, turn])
    db_session.commit()
    monkeypatch.setattr(
        chat_history_service,
        "SessionLocal",
        lambda: _NonClosingSession(db_session),
    )

    service = chat_history_service.transcript_service
    first = service.complete_background_turn(turn_id=turn.id, ai_msg="answer")
    second = service.complete_background_turn(turn_id=turn.id, ai_msg="duplicate")

    assert first == second == 2
    assert (
        db_session.query(ConversationMessage)
        .filter_by(
            conversation_id="reserved",
            role="Agent",
        )
        .count()
        == 1
    )
    assert conversation.turn_count == 1


def _pending_row(*, row_id: str, conversation, user, position: int, status="pending"):
    return PendingSubmission(
        id=row_id,
        conversation_id=conversation.id,
        user_id=user.id,
        version=1,
        position=position,
        status=status,
        mode="agent",
        message=row_id,
        question_indexes_json=[],
        attachments_json=[],
        error="claim failed" if status == "failed" else None,
    )


def test_claim_failure_retains_hold_and_never_falls_back(db_session, monkeypatch):
    user = User(username="claim-hold-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="claim-hold-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="claim-hold-active",
    )
    active = ConversationTurn(
        id="claim-hold-active",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="current",
        status="running",
        owner_id=turn_executor._WORKER_ID,
    )
    first = _pending_row(
        row_id="claim-hold-first", conversation=conversation, user=user, position=1
    )
    second = _pending_row(
        row_id="claim-hold-second", conversation=conversation, user=user, position=2
    )
    db_session.add_all([conversation, active, first, second])
    db_session.commit()

    original = turn_executor.preflight_attachment_drafts

    def reject_first(db, **kwargs):
        if kwargs["submission_id"] == first.id:
            raise AttachmentDraftUnavailableError("private parser details")
        return original(db, **kwargs)

    monkeypatch.setattr(turn_executor, "preflight_attachment_drafts", reject_first)
    changed, next_turn_id = turn_executor._terminalize(
        db_session,
        active.id,
        allowed_statuses={"running"},
        status="completed",
        error=None,
        owner_id=turn_executor._WORKER_ID,
    )
    assert changed is True
    assert next_turn_id is None
    db_session.expire_all()
    assert db_session.get(Conversation, conversation.id).active_turn_id is None
    assert db_session.get(PendingSubmission, first.id).status == "failed"
    assert "private parser" not in db_session.get(PendingSubmission, first.id).error
    assert db_session.get(PendingSubmission, second.id).status == "pending"


def test_failed_hold_queues_new_input_without_history(db_session):
    user = User(username="new-behind-hold", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="new-behind-hold-session", user_id=user.id, title="T", type="general"
    )
    failed = _pending_row(
        row_id="existing-failed",
        conversation=conversation,
        user=user,
        position=1,
        status="failed",
    )
    db_session.add_all([conversation, failed])
    db_session.commit()

    result = turn_executor.admit_submission(
        db_session,
        conversation,
        submission_id="new-behind-hold-input",
        version=1,
        user_id=user.id,
        requested_mode="agent",
        message="must remain queued",
    )
    assert result.status == "queued"
    assert result.turn_id is None
    assert db_session.query(ConversationTurn).count() == 0
    assert db_session.query(ConversationMessage).count() == 0


def test_edit_then_retry_failed_submission_uses_new_version(db_session):
    user = User(username="retry-edited", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="retry-edited-session", user_id=user.id, title="T", type="general"
    )
    failed = _pending_row(
        row_id="retry-edited-submission",
        conversation=conversation,
        user=user,
        position=1,
        status="failed",
    )
    db_session.add_all([conversation, failed])
    db_session.commit()

    edited = turn_executor.update_pending_submission(
        db_session,
        conversation.id,
        user.id,
        failed.id,
        expected_version=1,
        message="corrected",
        mode="agent",
        question_indexes=[],
        attachment_draft_ids=[],
    )
    assert edited.version == 2
    assert edited.status == "pending"
    assert edited.error is None

    # The edit removed the failure marker; an explicit retry of the FIFO head
    # is still safe, but arbitrary pending rows cannot use retry as reordering.
    edited.status = "failed"
    edited.error = "retry me"
    db_session.commit()
    result = turn_executor.retry_pending_submission(
        db_session,
        conversation.id,
        user.id,
        edited.id,
        expected_version=2,
    )
    assert result.status == "admitted"
    turn = db_session.get(ConversationTurn, result.turn_id)
    assert turn is not None and turn.message == "corrected"
    assert turn.submission_id == edited.id


def test_interrupt_admits_only_selected_submission(db_session):
    user = User(username="interrupt-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="interrupt-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="interrupt-active",
    )
    active = ConversationTurn(
        id="interrupt-active",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="current",
        status="running",
        owner_id=turn_executor._WORKER_ID,
        dispatch_generation=1,
    )
    first = _pending_row(
        row_id="interrupt-first", conversation=conversation, user=user, position=1
    )
    selected = _pending_row(
        row_id="interrupt-selected", conversation=conversation, user=user, position=2
    )
    db_session.add_all([conversation, active, first, selected])
    db_session.commit()

    status, generation = turn_executor.request_turn_interrupt(
        db_session,
        conversation.id,
        active.id,
        user.id,
        selected.id,
        expected_version=1,
    )
    assert (status, generation) == ("running", 2)
    changed, next_turn_id = turn_executor._terminalize(
        db_session,
        active.id,
        allowed_statuses={"running"},
        status="cancelled",
        error="Turn cancelled",
        user_id=user.id,
    )
    assert changed is True
    admitted = db_session.get(ConversationTurn, next_turn_id)
    assert admitted is not None and admitted.submission_id == selected.id
    assert db_session.get(PendingSubmission, first.id).status == "pending"


def test_interrupt_selected_failure_never_falls_back(db_session, monkeypatch):
    user = User(username="interrupt-fail-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="interrupt-fail-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="interrupt-fail-active",
    )
    active = ConversationTurn(
        id="interrupt-fail-active",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="current",
        status="running",
        owner_id=turn_executor._WORKER_ID,
    )
    first = _pending_row(
        row_id="interrupt-fail-first", conversation=conversation, user=user, position=1
    )
    selected = _pending_row(
        row_id="interrupt-fail-selected",
        conversation=conversation,
        user=user,
        position=2,
    )
    db_session.add_all([conversation, active, first, selected])
    db_session.commit()
    turn_executor.request_turn_interrupt(
        db_session,
        conversation.id,
        active.id,
        user.id,
        selected.id,
        expected_version=1,
    )

    monkeypatch.setattr(
        turn_executor,
        "preflight_attachment_drafts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AttachmentDraftUnavailableError("no")
        ),
    )
    changed, next_turn_id = turn_executor._terminalize(
        db_session,
        active.id,
        allowed_statuses={"running"},
        status="cancelled",
        error="Turn cancelled",
        user_id=user.id,
    )
    assert changed is True
    assert next_turn_id is None
    db_session.expire_all()
    assert db_session.get(Conversation, conversation.id).active_turn_id is None
    assert db_session.get(PendingSubmission, selected.id).status == "failed"
    assert db_session.get(PendingSubmission, first.id).status == "pending"
