"""A stopped local await is not a receipt proving a mutation did not happen."""

import asyncio

import pytest

from app.agent_runtime import tool_call_executor as executor
from app.agent_runtime.tool_policy import ToolEffect, ToolPolicyContext
from app.models.agent_execution import AgentToolCall
from tests.conftest import patch_session_locals
from tests.test_agent_runtime.test_tool_call_executor import _turn


@pytest.mark.parametrize(
    "failure", ["timeout", "cancel", "transport", "invalid_result"]
)
def test_started_mutation_retains_resource_fence(db_session, monkeypatch, failure):
    patch_session_locals(monkeypatch, db_session, executor)
    user, conversation, turn = _turn(db_session)
    committed = []
    context = ToolPolicyContext(user_confirmed_this_call=True)

    async def run():
        started = asyncio.Event()

        async def dispatch():
            committed.append("remote-effect")
            started.set()
            if failure == "transport":
                raise OSError("response lost")
            if failure == "invalid_result":
                return None
            await asyncio.Event().wait()

        async def execute(call_id, handler):
            plan = await executor.plan_tool_call(
                call_id=call_id,
                turn_id=turn.id,
                tool_name="publish",
                arguments={},
                effect=ToolEffect.EXTERNAL_WRITE,
                policy_context=context,
                resource_identities=("document:one",),
            )
            return await executor.execute_tool_call(
                call_id=call_id,
                turn_id=turn.id,
                session_id=conversation.id,
                user_id=user.id,
                tool_name="publish",
                arguments={},
                effect=ToolEffect.EXTERNAL_WRITE,
                policy_context=context,
                timeout_seconds=0.03 if failure == "timeout" else 2,
                dispatch=handler,
                plan=plan,
            )

        task = asyncio.create_task(execute("first", dispatch))
        await started.wait()
        if failure == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert result["external_outcome"] == "unknown"
            assert result["requires_reconcile"] is True
        db_session.expire_all()
        row = db_session.query(AgentToolCall).one()
        assert row.status == "unknown"
        assert row.result_json["execution_status"] in {"timeout", "cancelled", "failed"}

        async def must_not_run():
            raise AssertionError("unresolved mutation must be fenced")

        assert (await execute("second", must_not_run))["error"] == "reconcile_required"
        replay = await execute("first", must_not_run)
        assert replay["external_outcome"] == "unknown"
        assert committed == ["remote-effect"]

    asyncio.run(run())


def test_explicit_provider_rejection_is_not_an_unknown_outcome(db_session, monkeypatch):
    patch_session_locals(monkeypatch, db_session, executor)
    user, conversation, turn = _turn(db_session)

    async def run():
        return await executor.execute_tool_call(
            call_id="rejected",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="publish",
            arguments={},
            effect=ToolEffect.EXTERNAL_WRITE,
            policy_context=ToolPolicyContext(user_confirmed_this_call=True),
            timeout_seconds=1,
            dispatch=lambda: asyncio.sleep(0, result={"error": "provider_rejected"}),
        )

    assert asyncio.run(run()) == {"error": "provider_rejected"}
    db_session.expire_all()
    assert db_session.query(AgentToolCall).one().status == "failed"
