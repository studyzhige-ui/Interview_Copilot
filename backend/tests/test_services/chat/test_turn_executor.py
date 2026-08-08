from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.outbox_job import OutboxJob
from app.models.user import User
from app.services.chat import chat_history_service, turn_executor


class _NonClosingSession:
    def __init__(self, session):
        self.session = session

    def __getattr__(self, name):
        return getattr(self.session, name)

    def close(self):
        pass


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
    first = service.complete_background_turn(
        turn_id=turn.id,
        ai_msg="answer",
        enqueue_memory=True,
        memory_user_id=user.username,
    )
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
    job = (
        db_session.query(OutboxJob)
        .filter_by(
            job_type="extract_memory_realtime",
            aggregate_id=conversation.id,
        )
        .one()
    )
    assert job.status == "pending"
