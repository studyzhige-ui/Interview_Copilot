import asyncio
import json

import pytest
from app.agent_runtime.tool_call_executor import execute_tool_call, persist_turn_budget
from app.agent_runtime.tool_policy import ToolEffect, ToolPolicyContext
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation
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


def test_tool_call_audits_result_and_budget(db_session, monkeypatch):
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
            effect=ToolEffect.READ,
        )
        await persist_turn_budget(turn.id, {"steps": 1})
        return result

    assert asyncio.run(run()) == {"value": 2}
    db_session.expire_all()
    audit = db_session.query(AgentToolCall).one()
    assert audit.status == "completed"
    assert audit.arguments_json == {"value": 1}
    assert audit.result_json == {"value": 2}
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
            effect=ToolEffect.READ,
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
                effect=ToolEffect.READ,
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


def test_nested_tool_credentials_are_redacted_in_audit(db_session, monkeypatch):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)
    sentinel = "sk-proj-NESTED_SENTINEL_123456789"
    arguments = {
        "safe": "keep-me",
        "headers": {"Authorization": f"Bearer {sentinel}"},
        "nested": [{"client_secret": sentinel}],
        "endpoint": f"https://candidate:{sentinel}@example.test/path",
    }
    result = {
        "error": f"Authorization: Bearer {sentinel}",
        "details": [
            {"refresh_token": sentinel},
            {"message": f"provider returned Bearer {sentinel}"},
        ],
        "safe": "still-here",
    }

    async def run():
        return await execute_tool_call(
            call_id="call-redacted",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="credential_probe",
            arguments=arguments,
            timeout_seconds=1,
            dispatch=lambda: asyncio.sleep(0, result=result),
            effect=ToolEffect.READ,
        )

    safe_result = asyncio.run(run())
    assert sentinel not in json.dumps(safe_result, ensure_ascii=False)
    assert safe_result["details"][0]["refresh_token"] == "[REDACTED]"
    # Handler-owned inputs are not mutated in place; every value crossing the
    # execution boundary is redacted before model/history/audit consumers.
    assert arguments["nested"][0]["client_secret"] == sentinel

    db_session.expire_all()
    audit = db_session.query(AgentToolCall).one()
    audit_payload = {
        "arguments": audit.arguments_json,
        "result": audit.result_json,
        "error": audit.error,
    }
    assert sentinel not in json.dumps(audit_payload, ensure_ascii=False)
    assert audit.arguments_json["safe"] == "keep-me"
    assert audit.arguments_json["headers"]["Authorization"] == "[REDACTED]"
    assert audit.arguments_json["nested"][0]["client_secret"] == "[REDACTED]"
    assert audit.result_json["details"][0]["refresh_token"] == "[REDACTED]"
    assert audit.result_json["safe"] == "still-here"
    assert audit.error == "Authorization: [REDACTED]"


def test_late_receipt_updates_original_call_without_resurrecting_turn(
    db_session,
    monkeypatch,
):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)
    call = AgentToolCall(
        call_id="call-late-receipt",
        turn_id=turn.id,
        session_id=conversation.id,
        user_id=user.id,
        tool_name="external_write",
        effect="external_write",
        arguments_json={"object_id": "candidate-1"},
        timeout_seconds=30,
        status="unknown",
        dispatch_generation=1,
        policy_decision="allow",
        policy_reason="call_confirmed",
    )
    db_session.add(call)
    turn.status = "cancelled"
    turn.dispatch_generation = 2
    db_session.commit()

    returned = executor_module._finish(
        call.call_id,
        turn.id,
        conversation.id,
        user.id,
        call.tool_name,
        "completed",
        {"receipt": "provider-receipt-1"},
        None,
        25.0,
        1,
    )

    assert returned == {
        "error": "stale_dispatch_generation",
        "tool_name": "external_write",
    }
    db_session.expire_all()
    stored = db_session.query(AgentToolCall).one()
    assert stored.status == "completed"
    assert stored.result_json == {
        "receipt": "provider-receipt-1",
        "late_result": True,
        "turn_status": "cancelled",
        "requires_reconcile": False,
    }
    assert db_session.get(ConversationTurn, turn.id).status == "cancelled"


def test_standard_external_write_waits_without_dispatch(db_session, monkeypatch):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)
    dispatched = False

    async def dispatch():
        nonlocal dispatched
        dispatched = True
        return {"receipt": "should-not-exist"}

    async def run():
        return await execute_tool_call(
            call_id="call-policy-wait",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="send_external",
            arguments={"recipient": "person@example.com"},
            timeout_seconds=1,
            dispatch=dispatch,
            effect=ToolEffect.EXTERNAL_WRITE,
            policy_context=ToolPolicyContext(
                execution_mode="standard",
                current_task_authorizes=True,
            ),
        )

    result = asyncio.run(run())
    assert result["error"] == "interaction_required"
    assert result["interaction_type"] == "approval"
    assert dispatched is False

    db_session.expire_all()
    audit = db_session.query(AgentToolCall).one()
    assert audit.status == "waiting"
    assert audit.effect == "external_write"
    assert audit.policy_decision == "ask"
    assert audit.policy_reason == "external_write_confirmation_required"


def test_same_call_identity_is_not_dispatched_twice(db_session, monkeypatch):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)
    dispatch_count = 0

    async def dispatch():
        nonlocal dispatch_count
        dispatch_count += 1
        return {"value": 7}

    async def invoke():
        return await execute_tool_call(
            call_id="call-idempotent",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="read_value",
            arguments={"key": "x"},
            timeout_seconds=1,
            dispatch=dispatch,
            effect=ToolEffect.READ,
        )

    assert asyncio.run(invoke()) == {"value": 7}
    assert asyncio.run(invoke()) == {"value": 7}
    assert dispatch_count == 1
    assert db_session.query(AgentToolCall).count() == 1
