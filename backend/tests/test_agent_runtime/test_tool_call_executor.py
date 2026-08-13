import asyncio
import json

import pytest
from app.agent_runtime.tool_call_executor import (
    cancel_deferred_tool_calls,
    defer_tool_calls,
    execute_tool_call,
    plan_tool_call,
    persist_turn_budget,
)
from app.agent_runtime.tool_policy import ToolEffect, ToolPolicyContext
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
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
    assert audit.completion_sequence == 1
    assert audit.timeline_json[-1]["event"] == "waiting"
    assert audit.timeline_json[-1]["completion_sequence"] == 1


def test_missing_deployment_connector_hard_denies_without_interaction(
    db_session,
    monkeypatch,
):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)
    dispatched = False

    async def dispatch():
        nonlocal dispatched
        dispatched = True
        return {"should_not": "dispatch"}

    async def run():
        plan = await plan_tool_call(
            call_id="call-missing-deployment-connector",
            turn_id=turn.id,
            tool_name="web_search",
            arguments={"query": "python roles"},
            effect=ToolEffect.READ,
            policy_context=ToolPolicyContext(
                connection_ready=False,
                hard_deny_reason="connector_unavailable",
            ),
            provider_identity="tavily",
        )
        return await execute_tool_call(
            call_id=plan.call_id,
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name=plan.tool_name,
            arguments={"query": "python roles"},
            timeout_seconds=1,
            dispatch=dispatch,
            effect=ToolEffect.READ,
            plan=plan,
        )

    result = asyncio.run(run())
    assert result == {
        "error": "connector_unavailable",
        "tool_name": "web_search",
        "reason": "connector_unavailable",
        "provider": "tavily",
    }
    assert dispatched is False

    db_session.expire_all()
    audit = db_session.query(AgentToolCall).one()
    assert audit.status == "denied"
    assert audit.policy_decision == "deny"
    assert audit.policy_reason == "connector_unavailable"
    assert db_session.query(AgentInteraction).count() == 0


def test_unresolved_mutation_fences_same_user_resource_across_conversations(
    db_session,
    monkeypatch,
):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, first_conversation, first_turn = _turn(db_session)
    second_conversation = Conversation(user_id=user.id, title="second")
    db_session.add(second_conversation)
    db_session.flush()
    second_turn = ConversationTurn(
        conversation_id=second_conversation.id,
        user_id=user.id,
        mode="agent",
        message="retry same object",
    )
    db_session.add(second_turn)
    db_session.commit()
    second_dispatched = False
    resource = ("gmail-message:provider-message-7",)

    async def run():
        first_plan = await plan_tool_call(
            call_id="call-unknown-write",
            turn_id=first_turn.id,
            tool_name="mutate_message",
            arguments={"message_id": "provider-message-7"},
            effect=ToolEffect.EXTERNAL_WRITE,
            policy_context=ToolPolicyContext(user_confirmed_this_call=True),
            resource_identities=resource,
        )
        first = await execute_tool_call(
            call_id=first_plan.call_id,
            turn_id=first_turn.id,
            session_id=first_conversation.id,
            user_id=user.id,
            tool_name=first_plan.tool_name,
            arguments={"message_id": "provider-message-7"},
            timeout_seconds=1,
            dispatch=lambda: asyncio.sleep(0, result={"status": "unknown"}),
            effect=ToolEffect.EXTERNAL_WRITE,
            plan=first_plan,
        )

        async def blocked_dispatch():
            nonlocal second_dispatched
            second_dispatched = True
            return {"receipt": "must-not-exist"}

        second_plan = await plan_tool_call(
            call_id="call-overlap-write",
            turn_id=second_turn.id,
            tool_name="mutate_message",
            arguments={"message_id": "provider-message-7", "retry": True},
            effect=ToolEffect.EXTERNAL_WRITE,
            policy_context=ToolPolicyContext(user_confirmed_this_call=True),
            resource_identities=resource,
        )
        blocked = await execute_tool_call(
            call_id=second_plan.call_id,
            turn_id=second_turn.id,
            session_id=second_conversation.id,
            user_id=user.id,
            tool_name=second_plan.tool_name,
            arguments={"message_id": "provider-message-7", "retry": True},
            timeout_seconds=1,
            dispatch=blocked_dispatch,
            effect=ToolEffect.EXTERNAL_WRITE,
            plan=second_plan,
        )

        read_plan = await plan_tool_call(
            call_id="call-overlap-read",
            turn_id=second_turn.id,
            tool_name="read_message",
            arguments={"message_id": "provider-message-7"},
            effect=ToolEffect.READ,
            resource_identities=resource,
        )
        read = await execute_tool_call(
            call_id=read_plan.call_id,
            turn_id=second_turn.id,
            session_id=second_conversation.id,
            user_id=user.id,
            tool_name=read_plan.tool_name,
            arguments={"message_id": "provider-message-7"},
            timeout_seconds=1,
            dispatch=lambda: asyncio.sleep(0, result={"value": "safe-read"}),
            effect=ToolEffect.READ,
            plan=read_plan,
        )
        return first, blocked, read

    first, blocked, read = asyncio.run(run())
    assert first["status"] == "unknown"
    assert blocked == {
        "error": "reconcile_required",
        "reason": "unresolved_resource_side_effect",
        "blocking_call_id": "call-unknown-write",
        "blocking_session_id": first_conversation.id,
        "resource_identities": list(resource),
    }
    assert second_dispatched is False
    assert read == {"value": "safe-read"}

    db_session.expire_all()
    unknown = (
        db_session.query(AgentToolCall).filter_by(call_id="call-unknown-write").one()
    )
    assert unknown.status == "unknown"
    assert unknown.resource_identities_json == list(resource)
    assert (
        db_session.query(AgentToolCall)
        .filter_by(call_id="call-overlap-write")
        .one_or_none()
        is None
    )

    unknown.status = "completed"
    unknown.result_json = {"reconciled": True}
    db_session.commit()

    async def retry_after_reconcile():
        plan = await plan_tool_call(
            call_id="call-after-reconcile",
            turn_id=second_turn.id,
            tool_name="mutate_message",
            arguments={"message_id": "provider-message-7", "retry": 2},
            effect=ToolEffect.EXTERNAL_WRITE,
            policy_context=ToolPolicyContext(user_confirmed_this_call=True),
            resource_identities=resource,
        )
        return await execute_tool_call(
            call_id=plan.call_id,
            turn_id=second_turn.id,
            session_id=second_conversation.id,
            user_id=user.id,
            tool_name=plan.tool_name,
            arguments={"message_id": "provider-message-7", "retry": 2},
            timeout_seconds=1,
            dispatch=lambda: asyncio.sleep(0, result={"receipt": "settled-8"}),
            effect=ToolEffect.EXTERNAL_WRITE,
            plan=plan,
        )

    assert asyncio.run(retry_after_reconcile()) == {"receipt": "settled-8"}


def test_same_call_approval_cannot_cross_connection_identity(
    db_session,
    monkeypatch,
):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)
    dispatched = False

    async def dispatch():
        nonlocal dispatched
        dispatched = True
        return {"value": 3}

    async def run():
        first_plan = await plan_tool_call(
            call_id="call-connection-fence",
            turn_id=turn.id,
            tool_name="mcp__demo__add",
            arguments={"a": 1, "b": 2},
            effect=ToolEffect.UNKNOWN,
            handler_identity="mcp.manager.call_tool",
            provider_identity="mcp:demo",
            connection_identity="mcp-server:7:revision:1",
        )
        first = await execute_tool_call(
            call_id="call-connection-fence",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="mcp__demo__add",
            arguments={"a": 1, "b": 2},
            timeout_seconds=1,
            dispatch=dispatch,
            effect=ToolEffect.UNKNOWN,
            plan=first_plan,
        )
        changed_plan = await plan_tool_call(
            call_id="call-connection-fence",
            turn_id=turn.id,
            tool_name="mcp__demo__add",
            arguments={"a": 1, "b": 2},
            effect=ToolEffect.UNKNOWN,
            policy_context=ToolPolicyContext(user_confirmed_this_call=True),
            resume_waiting=True,
            handler_identity="mcp.manager.call_tool",
            provider_identity="mcp:demo",
            connection_identity="mcp-server:7:revision:2",
        )
        second = await execute_tool_call(
            call_id="call-connection-fence",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="mcp__demo__add",
            arguments={"a": 1, "b": 2},
            timeout_seconds=1,
            dispatch=dispatch,
            effect=ToolEffect.UNKNOWN,
            resume_waiting=True,
            plan=changed_plan,
        )
        return first, second

    first, second = asyncio.run(run())
    assert first["error"] == "interaction_required"
    assert second == {
        "error": "tool_call_identity_conflict",
        "tool_name": "mcp__demo__add",
    }
    assert dispatched is False
    row = db_session.query(AgentToolCall).one()
    assert row.status == "waiting"
    assert row.connection_identity == "mcp-server:7:revision:1"


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


def test_deferred_batch_call_resumes_same_identity_exactly_once(
    db_session, monkeypatch
):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)
    dispatch_count = 0

    async def dispatch():
        nonlocal dispatch_count
        dispatch_count += 1
        return {"value": 9}

    async def run():
        reserved = await defer_tool_calls(
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            dispatch_generation=1,
            blocked_by_call_id="call-waiting",
            calls=[
                {
                    "call_id": "call-deferred",
                    "tool_name": "read_value",
                    "arguments": {"key": "x"},
                    "effect": "read",
                    "timeout_seconds": 1,
                }
            ],
        )
        first = await execute_tool_call(
            call_id="call-deferred",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="read_value",
            arguments={"key": "x"},
            timeout_seconds=1,
            dispatch=dispatch,
            effect=ToolEffect.READ,
            resume_waiting=True,
        )
        second = await execute_tool_call(
            call_id="call-deferred",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="read_value",
            arguments={"key": "x"},
            timeout_seconds=1,
            dispatch=dispatch,
            effect=ToolEffect.READ,
        )
        return reserved, first, second

    reserved, first, second = asyncio.run(run())
    assert reserved is True
    assert first == second == {"value": 9}
    assert dispatch_count == 1
    call = db_session.query(AgentToolCall).one()
    assert call.call_id == "call-deferred"
    assert call.status == "completed"
    assert [item["event"] for item in call.timeline_json] == [
        "deferred",
        "admitted",
        "handler_started",
        "finished",
        "replayed",
    ]


def test_rejected_prerequisite_closes_deferred_calls_without_dispatch(
    db_session, monkeypatch
):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)

    async def reserve():
        return await defer_tool_calls(
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            dispatch_generation=1,
            blocked_by_call_id="call-waiting",
            calls=[
                {
                    "call_id": "call-later",
                    "tool_name": "later_write",
                    "arguments": {"value": 1},
                    "effect": "internal_write",
                }
            ],
        )

    assert asyncio.run(reserve()) is True
    closed = cancel_deferred_tool_calls(
        turn_id=turn.id,
        dispatch_generation=1,
        blocked_by_call_id="call-waiting",
    )
    assert closed[0]["call_id"] == "call-later"
    assert closed[0]["result"]["error"] == "tool_not_dispatched"
    assert db_session.query(AgentToolCall).one().status == "cancelled"


def test_tool_audit_preserves_model_order_and_real_completion_order(
    db_session, monkeypatch
):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)
    for call_id, model_index in (("call-first", 0), ("call-second", 1)):
        db_session.add(
            AgentToolCall(
                call_id=call_id,
                turn_id=turn.id,
                session_id=conversation.id,
                user_id=user.id,
                tool_name="read_value",
                effect="read",
                arguments_json={"key": call_id},
                timeout_seconds=1,
                status="running",
                dispatch_generation=1,
                policy_decision="allow",
                policy_reason="read_allowed",
                model_step=4,
                model_call_index=model_index,
                model_call_order=40_000 + model_index,
                timeline_json=[],
                receipt_refs_json=[],
            )
        )
    db_session.commit()

    executor_module._finish(
        "call-second",
        turn.id,
        conversation.id,
        user.id,
        "read_value",
        "completed",
        {"value": 2},
        None,
        5.0,
        1,
    )
    executor_module._finish(
        "call-first",
        turn.id,
        conversation.id,
        user.id,
        "read_value",
        "completed",
        {"value": 1},
        None,
        9.0,
        1,
    )

    db_session.expire_all()
    model_order = (
        db_session.query(AgentToolCall).order_by(AgentToolCall.model_call_order).all()
    )
    completion_order = (
        db_session.query(AgentToolCall)
        .order_by(AgentToolCall.completion_sequence)
        .all()
    )
    assert [row.call_id for row in model_order] == ["call-first", "call-second"]
    assert [row.call_id for row in completion_order] == [
        "call-second",
        "call-first",
    ]
    assert completion_order[0].timeline_json[-1]["completion_sequence"] == 1
    assert completion_order[1].timeline_json[-1]["completion_sequence"] == 2


def test_declared_receipt_refs_are_recorded_without_generic_result_guessing(
    db_session, monkeypatch
):
    import app.agent_runtime.tool_call_executor as executor_module

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)

    async def run():
        plan = await plan_tool_call(
            call_id="call-receipt",
            turn_id=turn.id,
            tool_name="provider_write",
            arguments={"object": "x"},
            effect=ToolEffect.EXTERNAL_WRITE,
            policy_context=ToolPolicyContext(user_confirmed_this_call=True),
            dispatch_generation=1,
            model_step=2,
            model_call_index=0,
            model_call_order=20_000,
            handler_identity="tests.provider_write",
            provider_identity="provider",
            connection_identity="provider-account:7",
            receipt_ref_resolver=lambda result: [result["typed_receipt"]["id"]],
        )
        return await execute_tool_call(
            call_id="call-receipt",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="provider_write",
            arguments={"object": "x"},
            timeout_seconds=1,
            dispatch=lambda: asyncio.sleep(
                0,
                result={
                    "typed_receipt": {"id": "receipt-7"},
                    "receipt_like_text": "do-not-guess-this",
                },
            ),
            effect=ToolEffect.EXTERNAL_WRITE,
            plan=plan,
        )

    assert asyncio.run(run())["typed_receipt"]["id"] == "receipt-7"
    db_session.expire_all()
    row = db_session.query(AgentToolCall).one()
    assert row.receipt_refs_json == ["receipt-7"]
    assert row.handler_identity == "tests.provider_write"
    assert row.provider_identity == "provider"
    assert row.connection_identity == "provider-account:7"


def test_large_result_is_canonical_and_audit_projection_preserves_coverage(
    db_session,
    monkeypatch,
):
    import app.agent_runtime.tool_call_executor as executor_module
    from app.agent_runtime.tool_redaction import (
        TOOL_RESULT_PROJECTION_CHARS,
        bounded_tool_result_projection,
    )

    patch_session_locals(monkeypatch, db_session, executor_module)
    user, conversation, turn = _turn(db_session)
    content = "x" * (TOOL_RESULT_PROJECTION_CHARS + 5_000)
    dispatched = 0

    async def dispatch():
        nonlocal dispatched
        dispatched += 1
        return {
            "attachment_ref_id": "attachment-ref-7",
            "source_ref_id": "source-ref-8",
            "path": "C:/safe/persisted/read-output.json",
            "content": content,
            "offset": 20_000,
            "total": 42_000,
            "total_chars": 42_000,
            "returned_chars": 20_000,
            "next_offset": 40_000,
            "has_more": True,
            # Legitimate read_file paging, not the legacy audit envelope.
            "truncated": True,
            "original_chars": 42_000,
            "preview": "legitimate provider paging metadata",
            "coverage": {
                "projection_chunk_count": 12,
                "projection_total_chars": 42_000,
                "read_mode": "exact_full_projection",
                "segment_start": 20_000,
                "segment_end": 40_000,
                "total_chars": 42_000,
                "starts_at_beginning": False,
                "reaches_end": False,
                "single_call_full_coverage": False,
                "untrusted_large_field": "y" * 20_000,
            },
            "untrusted_large_field": "z" * 20_000,
            "api_key": "secret-must-not-persist",
        }

    async def invoke():
        return await execute_tool_call(
            call_id="call-large-read",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="read_file",
            arguments={"attachment_ref_id": "attachment-ref-7"},
            timeout_seconds=1,
            dispatch=dispatch,
            effect=ToolEffect.READ,
        )

    first = asyncio.run(invoke())
    replay = asyncio.run(invoke())
    assert first["content"] == content
    assert replay["content"] == content
    assert replay["preview"] == "legitimate provider paging metadata"
    assert dispatched == 1

    db_session.expire_all()
    row = db_session.query(AgentToolCall).one()
    assert row.result_json["content"] == content
    assert row.result_json["untrusted_large_field"] == "z" * 20_000
    assert row.result_json["api_key"] == "[REDACTED]"
    audited = bounded_tool_result_projection(row.result_json)

    assert audited is not None and audited["truncated"] is True
    assert audited["attachment_ref_id"] == "attachment-ref-7"
    assert audited["source_ref_id"] == "source-ref-8"
    assert audited["path"] == "C:/safe/persisted/read-output.json"
    assert audited["offset"] == 20_000
    assert audited["total"] == 42_000
    assert audited["total_chars"] == 42_000
    assert audited["has_more"] is True
    assert audited["coverage"] == {
        "projection_chunk_count": 12,
        "projection_total_chars": 42_000,
        "read_mode": "exact_full_projection",
        "segment_start": 20_000,
        "segment_end": 40_000,
        "total_chars": 42_000,
        "starts_at_beginning": False,
        "reaches_end": False,
        "single_call_full_coverage": False,
    }
    assert "content" not in audited
    assert "untrusted_large_field" not in audited

    # The model can page the exact canonical result on another worker. No
    # APP_DATA_DIR path or duplicate result file participates in the read.
    import app.db.database as database_module
    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.file_tool import ReadFileArgs, _read_file_sync

    patch_session_locals(monkeypatch, db_session, database_module)
    ctx = AgentToolContext(
        user_id=str(user.id),
        user_pk=user.id,
        session_id=conversation.id,
        turn_id=turn.id,
    )
    canonical = json.dumps(
        row.result_json,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    first_page = _read_file_sync(
        ReadFileArgs(tool_call_id="call-large-read", offset=0, limit=101),
        ctx,
    )
    assert first_page["content"] == canonical[:101]
    assert first_page["read_mode"] == "canonical_tool_result"
    assert first_page["total_chars"] == len(canonical)
    assert first_page["next_offset"] == 101

    second_page = _read_file_sync(
        ReadFileArgs(
            tool_call_id="call-large-read",
            offset=first_page["next_offset"],
            limit=101,
        ),
        ctx,
    )
    assert second_page["content"] == canonical[101:202]
    assert second_page["coverage"]["segment_start"] == 101

    wrong_turn = _read_file_sync(
        ReadFileArgs(tool_call_id="call-large-read"),
        AgentToolContext(
            user_id=str(user.id),
            user_pk=user.id,
            session_id=conversation.id,
            turn_id="another-turn",
        ),
    )
    assert wrong_turn == {
        "error": "tool_result_unavailable",
        "tool_call_id": "call-large-read",
    }
