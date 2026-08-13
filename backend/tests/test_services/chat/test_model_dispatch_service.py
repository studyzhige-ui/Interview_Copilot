import asyncio
from types import SimpleNamespace

import pytest

from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.model_dispatch import AgentModelDispatch
from app.models.user import User
from app.services.chat.model_dispatch_service import (
    ModelDispatchConflictError,
    durable_model_stream,
    request_fingerprint,
    start_model_dispatch,
)

from tests.conftest import patch_session_locals


def _turn(db_session):
    user = User(username="model-fence", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, title="model fence")
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="run",
        dispatch_generation=3,
    )
    db_session.add(turn)
    db_session.commit()
    return user, turn


def test_model_dispatch_fences_generation_and_identity(db_session):
    user, turn = _turn(db_session)
    fingerprint = request_fingerprint(
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
    )
    row = start_model_dispatch(
        db_session,
        call_id="model:3:1:1",
        turn_id=turn.id,
        user_id=user.id,
        dispatch_generation=3,
        provider="anthropic",
        model="claude-test",
        fingerprint=fingerprint,
    )
    replay = start_model_dispatch(
        db_session,
        call_id="model:3:1:1",
        turn_id=turn.id,
        user_id=user.id,
        dispatch_generation=3,
        provider="anthropic",
        model="claude-test",
        fingerprint=fingerprint,
    )
    assert replay.id == row.id

    with pytest.raises(ModelDispatchConflictError, match="identity_conflict"):
        start_model_dispatch(
            db_session,
            call_id="model:3:1:1",
            turn_id=turn.id,
            user_id=user.id,
            dispatch_generation=3,
            provider="anthropic",
            model="claude-test",
            fingerprint="different",
        )

    turn.dispatch_generation = 4
    db_session.flush()
    with pytest.raises(ModelDispatchConflictError, match="stale"):
        start_model_dispatch(
            db_session,
            call_id="model:3:2:1",
            turn_id=turn.id,
            user_id=user.id,
            dispatch_generation=3,
            provider="anthropic",
            model="claude-test",
            fingerprint=fingerprint,
        )


def test_durable_stream_persists_partial_and_terminal_usage(db_session, monkeypatch):
    import app.services.chat.model_dispatch_service as service_module

    patch_session_locals(monkeypatch, db_session, service_module)
    user, turn = _turn(db_session)
    start_model_dispatch(
        db_session,
        call_id="model:3:1:1",
        turn_id=turn.id,
        user_id=user.id,
        dispatch_generation=3,
        provider="openai",
        model="test",
        fingerprint=request_fingerprint(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        ),
    )

    async def source():
        yield SimpleNamespace(text_delta="a" * 1_500, usage=None)
        yield SimpleNamespace(
            text_delta="b" * 700,
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=3,
                cache_read_tokens=4,
                cache_creation_tokens=2,
            ),
        )

    async def run():
        values = []
        async for chunk in durable_model_stream(
            source(),
            turn_id=turn.id,
            call_id="model:3:1:1",
            dispatch_generation=3,
        ):
            values.append(chunk)
        return values

    assert len(asyncio.run(run())) == 2
    db_session.expire_all()
    row = db_session.query(AgentModelDispatch).one()
    assert row.status == "completed"
    assert row.partial_text == "a" * 1_500 + "b" * 700
    assert row.usage_json == {
        "prompt_tokens": 10,
        "completion_tokens": 3,
        "cache_read_tokens": 4,
        "cache_creation_tokens": 2,
    }
