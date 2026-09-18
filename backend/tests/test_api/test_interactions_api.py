from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import interactions
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.schemas.agent_interaction import InteractionPayload
from app.services.chat.interaction_service import create_pending_interaction


def _client(db_session, user: User) -> TestClient:
    async def current_user():
        return user

    def current_db():
        yield db_session

    app = FastAPI()
    app.include_router(interactions.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = current_db
    return TestClient(app)


def _user(db_session, label: str) -> User:
    row = User(
        username=f"interaction-projection-{label}-{uuid.uuid4().hex}",
        hashed_password="x",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _interaction(db_session, user: User, kind: str):
    conversation = Conversation(user_id=user.id, mode="agent")
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="waiting",
        status="waiting",
        waiting_reason="interaction",
    )
    db_session.add(turn)
    db_session.flush()
    interaction = create_pending_interaction(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        kind=kind,
        request=InteractionPayload(root={"protocol": f"test.{kind}.v1"}),
    )
    return conversation, turn, interaction


def test_pending_confirmation_projection_is_empty_for_a_new_user(db_session) -> None:
    user = _user(db_session, "empty")
    response = _client(db_session, user).get(
        "/api/v1/interactions/pending-confirmations"
    )
    assert response.status_code == 200
    assert response.json() == []


def test_pending_confirmation_projection_is_owned_and_kind_filtered(
    db_session,
) -> None:
    owner = _user(db_session, "owner")
    other = _user(db_session, "other")
    conversation, turn, expected = _interaction(
        db_session,
        owner,
        "fact_confirmation",
    )
    _interaction(db_session, owner, "clarification")
    _interaction(db_session, other, "approval")

    response = _client(db_session, owner).get(
        "/api/v1/interactions/pending-confirmations"
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["conversation_id"] == conversation.id
    assert body[0]["turn_status"] == turn.status
    assert body[0]["interaction"]["id"] == expected.id
    assert body[0]["interaction"]["turn_id"] == turn.id
    assert body[0]["interaction"]["kind"] == "fact_confirmation"
    assert body[0]["interaction"]["request"] == {
        "protocol": "test.fact_confirmation.v1"
    }
