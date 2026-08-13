from __future__ import annotations

import uuid
from collections.abc import Iterator

import app.models  # noqa: F401
import pytest
from app.api import chat as chat_api
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.pending_submission import PendingSubmission
from app.models.user import User
from app.schemas.client_action import MockPrefillPayload
from app.services.chat.client_action_service import create_mock_client_action
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    class FakeUser:
        username = "alice-client-action"

    def fake_user():
        return FakeUser()

    def fake_db():
        yield db

    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    yield TestClient(app)


def _seed(db: Session):
    suffix = uuid.uuid4().hex
    user = User(username="alice-client-action", hashed_password="x")
    db.add(user)
    db.flush()
    conversation = Conversation(user_id=user.id, mode="agent")
    db.add(conversation)
    db.flush()
    submission = PendingSubmission(
        id=f"sub-{suffix}",
        conversation_id=conversation.id,
        user_id=user.id,
        position=1,
        status="claimed",
        message="start mock",
        mode="agent",
        source_client_id="client-a",
    )
    db.add(submission)
    db.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        submission_id=submission.id,
        mode="agent",
        message=submission.message,
        status="waiting",
        waiting_reason="interaction",
    )
    db.add(turn)
    db.flush()
    conversation.active_turn_id = turn.id
    db.add(
        AgentToolCall(
            call_id="call-mock",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="start_mock_interview",
            effect="client_action",
            arguments_json={},
            timeout_seconds=30,
            status="waiting",
        )
    )
    db.flush()
    interaction, request = create_mock_client_action(
        db,
        turn=turn,
        tool_call_id="call-mock",
        action="mock_interview.prefill",
        payload=MockPrefillPayload(
            resume_id="resume-private",
            jd_text="A private and sufficiently detailed backend job description.",
            interviewer_style="professional",
            target_question_count=20,
        ),
        original_client_id="client-a",
        bound_client_id="client-a",
    )
    db.commit()
    return user, conversation, turn, interaction, request


def test_delivery_takeover_resolution_and_replay_keep_one_turn_call(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    _user, conversation, turn, interaction, action = _seed(db)
    from app.services.chat import turn_executor
    from app.services.chat.turn_event_buffer import turn_event_buffer

    scheduled: list[str] = []

    async def reset(_turn_id: str):
        return None

    monkeypatch.setattr(turn_event_buffer, "reset", reset)
    monkeypatch.setattr(turn_executor, "schedule_turn", scheduled.append)

    base = f"/api/v1/chat/{conversation.id}/turns/{turn.id}"
    delivered = client.get(
        f"{base}/client-actions/pending",
        params={"client_id": "client-a"},
    )
    assert delivered.status_code == 200
    assert delivered.json()["payload"]["resume_id"] == "resume-private"
    wrong_tab = client.get(
        f"{base}/client-actions/pending",
        params={"client_id": "client-b"},
    )
    assert wrong_tab.status_code == 200 and wrong_tab.json() is None

    observer = client.get(f"{base}/interaction")
    assert observer.status_code == 200
    assert observer.json()["request"]["delivery"] == "bound_client_only"
    assert "resume-private" not in observer.text

    bypass = client.post(
        f"{base}/interactions/{interaction.id}/resolve",
        json={
            "expected_version": 1,
            "status": "resolved",
            "resolution": {"outcome": "acknowledged"},
        },
    )
    assert bypass.status_code == 409

    takeover = client.post(
        f"{base}/client-actions/{interaction.id}/takeover",
        json={
            "action_id": action.action_id,
            "expected_version": 1,
            "client_id": "client-b",
        },
    )
    assert takeover.status_code == 200, takeover.text
    assert takeover.json()["version"] == 2
    assert takeover.json()["takeover_generation"] == 1

    result_body = {
        "action_id": action.action_id,
        "client_id": "client-b",
        "expected_version": 2,
        "outcome": "acknowledged",
    }
    accepted = client.post(
        f"{base}/client-actions/{interaction.id}/resolve",
        json=result_body,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["replayed"] is False
    assert accepted.json()["dispatch_generation"] == 2
    assert scheduled == [turn.id]

    replay = client.post(
        f"{base}/client-actions/{interaction.id}/resolve",
        json=result_body,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert scheduled == [turn.id]

    db.expire_all()
    refreshed = db.get(ConversationTurn, turn.id)
    assert refreshed is not None
    assert refreshed.status == "pending"
    assert refreshed.dispatch_generation == 2
