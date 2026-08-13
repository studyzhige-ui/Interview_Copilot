from __future__ import annotations

from collections.abc import Iterator

import app.models  # noqa: F401
import pytest
from app.api import chat as chat_api
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.services.chat.chat_history_service import transcript_service
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
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    class FakeUser:
        username = "alice-tool-audit"

    def fake_user():
        return FakeUser()

    def fake_db():
        yield db

    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    yield TestClient(app)


def _seed_call(db: Session, *, username: str, suffix: str):
    user = User(username=username, hashed_password="x")
    db.add(user)
    db.flush()
    conversation = Conversation(
        id=f"conversation-{suffix}", user_id=user.id, mode="agent"
    )
    db.add(conversation)
    db.flush()
    user_message = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role="User",
        content="run",
    )
    assistant_message = ConversationMessage(
        conversation_id=conversation.id,
        seq=2,
        role="Agent",
        content="done",
        content_blocks_json=(
            '[{"type":"tool_use","id":"call-audit","name":"read_url",'
            '"input":{"url":"https://example.test"}},'
            '{"type":"tool_result","tool_use_id":"call-audit",'
            '"is_error":false,"latency_ms":2,"summary":"ok","content":"done"}]'
        ),
    )
    db.add_all([user_message, assistant_message])
    db.flush()
    turn = ConversationTurn(
        id=f"turn-{suffix}",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="run",
        user_message_seq=1,
        assistant_message_seq=2,
        status="completed",
    )
    db.add(turn)
    db.flush()
    call = AgentToolCall(
        call_id="call-audit",
        turn_id=turn.id,
        session_id=conversation.id,
        user_id=user.id,
        tool_name="read_url",
        effect="read",
        arguments_json={"url": "https://example.test", "api_key": "secret-input"},
        timeout_seconds=30,
        status="completed",
        dispatch_generation=2,
        policy_decision="allow",
        policy_reason="read_only",
        result_json={"authorization": "Bearer secret-output", "count": 3},
        error="token=secret-error",
        duration_ms=12.5,
    )
    db.add(call)
    db.commit()
    return conversation, turn


def test_tool_call_audit_uses_same_identity_and_redacts_projection(
    client: TestClient,
    db: Session,
):
    conversation, turn = _seed_call(
        db,
        username="alice-tool-audit",
        suffix="alice",
    )

    response = client.get(
        f"/api/v1/chat/{conversation.id}/turns/{turn.id}/tool-calls/call-audit"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["call_id"] == "call-audit"
    assert body["turn_id"] == turn.id
    assert body["dispatch_generation"] == 2
    assert body["policy_decision"] == "allow"
    assert body["arguments"]["api_key"] == "[REDACTED]"
    assert body["result"]["authorization"] == "[REDACTED]"
    assert body["error"] == "token=[REDACTED]"

    transcript = transcript_service.get_full_transcript(conversation.id, db=db)
    assert [message["turn_id"] for message in transcript] == [turn.id, turn.id]
    assert transcript[1]["blocks"][0]["id"] == body["call_id"]


def test_tool_call_audit_hides_cross_tenant_identity(
    client: TestClient,
    db: Session,
):
    conversation, turn = _seed_call(
        db,
        username="bob-tool-audit",
        suffix="bob",
    )

    response = client.get(
        f"/api/v1/chat/{conversation.id}/turns/{turn.id}/tool-calls/call-audit"
    )

    assert response.status_code == 404
