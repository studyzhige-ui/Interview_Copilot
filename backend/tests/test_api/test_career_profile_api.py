from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterator

import app.models  # noqa: F401
import pytest
from app.api import career_profile
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.chat import Conversation, ConversationMessage
from app.models.user import User
from app.schemas.ability_signal import AbilitySignalCreateInput
from app.services import ability_signal_service
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
    user = User(username="alice", hashed_password="x")
    db.add(user)
    db.commit()

    def fake_db() -> Iterator[Session]:
        yield db

    app = FastAPI()
    app.include_router(career_profile.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)


def test_profile_api_keeps_facts_and_directions_under_one_owner(
    client: TestClient,
):
    initial = client.get("/api/v1/career-profile")
    assert initial.status_code == 200
    assert initial.json()["personal_facts"] == []

    fact = client.post(
        "/api/v1/career-profile/facts",
        json={
            "expected_profile_version": 1,
            "fact": {"kind": "skill", "name": "Python", "category": "backend"},
            "confirmation": {"kind": "user_edit"},
        },
    )
    assert fact.status_code == 200, fact.text
    assert fact.json()["version"] == 2

    direction = client.post(
        "/api/v1/career-profile/directions",
        json={
            "expected_profile_version": 2,
            "direction": {
                "label": "Backend Engineer",
                "criteria": {"role_keywords": ["backend", "python"]},
                "lifecycle": "active",
                "priority": 0,
            },
            "confirmation": {"kind": "user_edit"},
        },
    )
    assert direction.status_code == 200, direction.text
    payload = direction.json()
    assert payload["version"] == 3
    assert payload["personal_facts"][0]["value"]["name"] == "Python"
    assert payload["directions"][0]["label"] == "Backend Engineer"

    stale = client.post(
        "/api/v1/career-profile/facts",
        json={
            "expected_profile_version": 1,
            "fact": {"kind": "skill", "name": "Go"},
            "confirmation": {"kind": "user_edit"},
        },
    )
    assert stale.status_code == 409


def test_ability_signal_api_exposes_inference_and_user_dispute(
    client: TestClient,
    db: Session,
):
    user = db.query(User).filter(User.username == "alice").one()
    conversation = Conversation(
        id="conv-ability",
        user_id=user.id,
        title="能力复盘",
        type="general",
    )
    db.add(conversation)
    db.flush()
    message = ConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content="我刚完成了一次系统设计复盘。",
        seq=1,
    )
    db.add(message)
    db.commit()

    signal = ability_signal_service.create_ability_signal(
        db,
        user_pk=user.id,
        assessment=AbilitySignalCreateInput.model_validate(
            {
                "topic": "system_design",
                "signal_type": "communication",
                "summary": "能够说明核心取舍，但容量估算仍不稳定。",
                "confidence": 0.72,
                "formed_at": datetime.now(UTC),
                "sources": [
                    {"kind": "conversation_message", "source_id": str(message.id)}
                ],
            }
        ),
    )
    db.commit()

    listed = client.get("/api/v1/ability-signals")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == signal.id

    disputed = client.post(
        f"/api/v1/ability-signals/{signal.id}/dispute",
        json={"expected_version": 1, "reason": "该结论没有考虑最新一次面试。"},
    )
    assert disputed.status_code == 200, disputed.text
    assert disputed.json()["status"] == "disputed"
    assert disputed.json()["version"] == 2
