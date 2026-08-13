from __future__ import annotations

from collections.abc import Iterator

import app.models  # noqa: F401
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import history
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.chat import Conversation, ConversationMessage
from app.models.user import User


@pytest.fixture
def history_api() -> Iterator[tuple[TestClient, Session, User]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username="history-api-user", hashed_password="x")
    db.add(user)
    db.flush()
    conversation = Conversation(id="history-api-conversation", user_id=user.id)
    db.add(conversation)
    db.flush()
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            seq=1,
            role="User",
            content="这条历史需要精确回读。",
        )
    )
    db.commit()

    def fake_db() -> Iterator[Session]:
        yield db

    app = FastAPI()
    app.include_router(history.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app), db, user
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_history_api_searches_exact_records_and_validates_closed_filters(history_api):
    client, _db, _user = history_api

    response = client.get(
        "/api/v1/history/search",
        params={"query": "精确回读", "kind": "message", "role": "user"},
    )
    invalid = client.get(
        "/api/v1/history/search",
        params={"query": "精确回读", "kind": "invented"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["identity"].startswith("conversation_message:")
    assert invalid.status_code == 422

    identity = response.json()["results"][0]["identity"]
    exact = client.get(f"/api/v1/history/records/{identity}")
    assert exact.status_code == 200, exact.text
    assert exact.json()["content"] == "这条历史需要精确回读。"


def test_history_api_hides_foreign_conversation(history_api):
    client, db, _user = history_api
    other = User(username="history-api-other", hashed_password="x")
    db.add(other)
    db.flush()
    db.add(Conversation(id="history-api-foreign", user_id=other.id))
    db.commit()

    response = client.get(
        "/api/v1/history/search",
        params={"query": "anything", "conversation_id": "history-api-foreign"},
    )

    assert response.status_code == 404
