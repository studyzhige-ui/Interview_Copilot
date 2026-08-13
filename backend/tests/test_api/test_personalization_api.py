from __future__ import annotations

from collections.abc import Iterator

import app.models  # noqa: F401
import pytest
from app.api import personalization
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.chat import Conversation, ConversationMessage
from app.models.interview_record import InterviewRecord
from app.models.user import User
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
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    user = User(username="alice-personalization", hashed_password="x")
    db.add(user)
    db.commit()

    def fake_db() -> Iterator[Session]:
        yield db

    app = FastAPI()
    app.include_router(personalization.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)


def test_personalization_api_routes_commands_to_three_real_owners(
    client: TestClient,
    db: Session,
):
    user = db.query(User).filter(User.username == "alice-personalization").one()
    record = InterviewRecord(user_id=user.id, source="upload", title="onsite")
    db.add(record)
    db.flush()
    conversation = Conversation(
        id="guidance-api-conversation",
        user_id=user.id,
        type="debrief",
        subject_type="interview_record",
        subject_id=record.id,
    )
    db.add(conversation)
    db.flush()
    message = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role="User",
        content="这个对话都先给结论。",
    )
    db.add(message)
    db.commit()

    empty = client.get("/api/v1/personalization/copilot-preference")
    assert empty.status_code == 200
    assert empty.json() == {
        "id": None,
        "instructions": [],
        "version": 0,
        "updated_at": None,
    }

    global_update = client.put(
        "/api/v1/personalization/copilot-preference",
        json={"expected_version": 0, "instructions": ["默认使用中文"]},
    )
    assert global_update.status_code == 200, global_update.text
    assert global_update.json()["version"] == 1

    local_update = client.put(
        f"/api/v1/personalization/conversations/{conversation.id}/guidance",
        json={
            "expected_version": 0,
            "guidance": "本对话只分析系统设计。",
            "source_message_id": message.id,
        },
    )
    assert local_update.status_code == 200, local_update.text
    assert local_update.json()["source_message_id"] == message.id

    debrief_update = client.put(
        f"/api/v1/personalization/interviews/{record.id}/guidance",
        json={
            "expected_version": 0,
            "guidance": "本次复盘先分析表达结构。",
        },
    )
    assert debrief_update.status_code == 200, debrief_update.text
    assert debrief_update.json()["owner_id"] == record.id

    stale = client.put(
        "/api/v1/personalization/copilot-preference",
        json={"expected_version": 0, "instructions": ["stale"]},
    )
    assert stale.status_code == 409


def test_personalization_api_rejects_cross_tenant_owners(
    client: TestClient,
    db: Session,
):
    other = User(username="other-personalization", hashed_password="x")
    db.add(other)
    db.flush()
    conversation = Conversation(id="foreign-guidance", user_id=other.id)
    db.add(conversation)
    db.commit()

    response = client.get(
        "/api/v1/personalization/conversations/foreign-guidance/guidance"
    )

    assert response.status_code == 404
