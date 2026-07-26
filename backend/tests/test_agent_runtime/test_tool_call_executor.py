import asyncio

import pytest

from app.agent_runtime.tool_call_executor import execute_tool_call, persist_turn_budget
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation
from app.models.conversation_capability_state import ConversationCapabilityState
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from tests.conftest import patch_session_locals


def _turn(db_session):
    user = User(username="tool-audit", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, title="audit")
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="run",
    )
    db_session.add(turn)
    db_session.commit()
    return user, conversation, turn


def test_tool_call_audits_result_history_and_budget(db_session, monkeypatch):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)

    async def run():
        result = await execute_tool_call(
            call_id="call-1",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="demo",
            arguments={"value": 1},
            timeout_seconds=1,
            dispatch=lambda: asyncio.sleep(0, result={"value": 2}),
        )
        await persist_turn_budget(turn.id, {"steps": 1})
        return result

    assert asyncio.run(run()) == {"value": 2}
    db_session.expire_all()
    audit = db_session.query(AgentToolCall).one()
    assert audit.status == "completed"
    assert audit.arguments_json == {"value": 1}
    assert audit.result_json == {"value": 2}
    state = db_session.get(ConversationCapabilityState, conversation.id)
    assert state.tool_history_json[-1]["tool_name"] == "demo"
    assert db_session.get(ConversationTurn, turn.id).budget_json == {"steps": 1}


def test_tool_call_timeout_is_audited(db_session, monkeypatch):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)

    async def run():
        return await execute_tool_call(
            call_id="call-timeout",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="slow",
            arguments={},
            timeout_seconds=0.01,
            dispatch=lambda: asyncio.sleep(1, result={}),
        )

    assert asyncio.run(run())["error"] == "tool_timeout"
    db_session.expire_all()
    assert db_session.query(AgentToolCall).one().status == "timeout"


def test_tool_call_cancellation_is_audited(db_session, monkeypatch):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)

    async def run():
        task = asyncio.create_task(
            execute_tool_call(
                call_id="call-cancelled",
                turn_id=turn.id,
                session_id=conversation.id,
                user_id=user.id,
                tool_name="waiting",
                arguments={},
                timeout_seconds=10,
                dispatch=lambda: asyncio.sleep(10, result={}),
            )
        )
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.05)

    asyncio.run(run())
    db_session.expire_all()
    assert db_session.query(AgentToolCall).one().status == "cancelled"
