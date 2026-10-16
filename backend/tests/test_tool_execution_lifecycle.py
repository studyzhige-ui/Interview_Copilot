"""Real registry/stream/admission/audit seams with synthetic handlers."""

import asyncio
import pytest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import sessionmaker

from app.agent_runtime import tool_call_executor as executor
from app.agent_runtime.tool_call_streaming import (
    ToolCallAssembler,
    ToolCallProtocolError,
)
from app.agent_runtime.tool_policy import ToolEffect, ToolPolicyContext
from app.agent_runtime.tool_registry import (
    AgentToolContext,
    ToolDefinition,
    ToolRegistry,
    parse_tool_arguments,
)
from app.core.model_provider_adapter import ProviderStreamEvent, ProviderToolCallDelta
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.agent_execution import AgentToolCall


@pytest.fixture
def execution(db, owners, monkeypatch):
    owner = owners[0]
    conversation = Conversation(user_id=owner.id)
    db.add(conversation)
    db.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=owner.id,
        mode="agent",
        message="test",
        status="running",
        dispatch_generation=1,
    )
    db.add(turn)
    db.flush()
    conversation.active_turn_id = turn.id
    db.flush()
    monkeypatch.setattr(
        executor,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), join_transaction_mode="create_savepoint"),
    )
    return dict(
        call_id="call-1",
        turn_id=turn.id,
        session_id=conversation.id,
        user_id=owner.id,
        tool_name="read_value",
        arguments={"value": 3},
        timeout_seconds=1,
        effect=ToolEffect.READ,
    )


@pytest.mark.asyncio
async def test_definition_stream_dispatch_and_replay_share_one_identity(db, execution):
    class Arguments(BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: int = Field(ge=0, description="Requested value")

    calls = []

    async def handler(args, context):
        calls.append(args.value)
        return {"value": args.value}

    registry = ToolRegistry()
    definition = ToolDefinition(
        name="read_value",
        description="Read a value",
        args_model=Arguments,
        handler=handler,
        effect=ToolEffect.READ,
    )
    registry.register(definition)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(definition)
    assert (
        registry.get_openai_schemas()[0]["function"]["parameters"]["properties"][
            "value"
        ]["minimum"]
        == 0
    )
    assembler = ToolCallAssembler()
    assembler.feed(
        ProviderStreamEvent(
            tool_call_deltas=(
                ProviderToolCallDelta(
                    index=0,
                    call_id="call-1",
                    name="read_value",
                    arguments_delta='{"value":',
                ),
            )
        )
    )
    with pytest.raises(ToolCallProtocolError):
        assembler.finish()
    assembler.feed(
        ProviderStreamEvent(
            tool_call_deltas=(ProviderToolCallDelta(index=0, arguments_delta="3}"),),
            stop_reason="tool_calls",
        )
    )
    call = assembler.finish()[0]
    args = parse_tool_arguments(call.arguments)
    context = AgentToolContext(user_id="synthetic", session_id=execution["session_id"])
    assert (await registry.plan_call(call.name, {"value": -1}, context)).error

    async def dispatch():
        return await registry.dispatch(call.name, args, context)

    assert await executor.execute_tool_call(**execution, dispatch=dispatch) == {
        "value": 3
    }
    assert await executor.execute_tool_call(**execution, dispatch=dispatch) == {
        "value": 3
    }
    assert calls == [3]
    conflict = await executor.execute_tool_call(
        **{**execution, "arguments": {"value": 4}}, dispatch=dispatch
    )
    assert conflict["error"] == "tool_call_identity_conflict" and calls == [3]
    row = db.query(AgentToolCall).one()
    assert row.status == "completed" and row.completed_at and row.arguments_digest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "effect, expected",
    [(ToolEffect.READ, "timeout"), (ToolEffect.EXTERNAL_WRITE, "unknown")],
)
async def test_timeout_persists_distinct_read_and_external_outcomes(
    db, execution, effect, expected
):
    attempts = []

    async def never_finishes():
        attempts.append(1)
        await asyncio.Event().wait()

    args = {
        **execution,
        "effect": effect,
        "timeout_seconds": 0.01,
        "policy_context": ToolPolicyContext(user_confirmed_this_call=True),
    }
    await executor.execute_tool_call(**args, dispatch=never_finishes)
    row = db.query(AgentToolCall).one()
    assert row.status == expected
    await executor.execute_tool_call(**args, dispatch=never_finishes)
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_cancel_reaps_handler_and_records_unknown_write(db, execution):
    started, reaped = asyncio.Event(), asyncio.Event()

    async def dispatch():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            reaped.set()

    task = asyncio.create_task(
        executor.execute_tool_call(
            **{
                **execution,
                "effect": ToolEffect.EXTERNAL_WRITE,
                "policy_context": ToolPolicyContext(user_confirmed_this_call=True),
            },
            dispatch=dispatch,
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert reaped.is_set()
    assert db.query(AgentToolCall).one().status == "unknown"


@pytest.mark.parametrize("raw", ['{"value":1,"value":2}', '{"value":NaN}', "[]", "{"])
def test_ambiguous_arguments_are_not_dispatchable(raw):
    with pytest.raises(ValueError):
        parse_tool_arguments(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("overflow", [False, True])
async def test_agent_loop_uses_real_tool_result_to_choose_next_step(
    db, execution, monkeypatch, recover, overflow
):
    import json
    from app.db import database
    from app.conversation import agent_strategy, agent_turn_state
    from app.conversation.application import model_dispatch_service
    from app.conversation.context_contracts import AssembledContext
    from app.conversation.strategy import StrategyContext, StrategyResult
    from app.agent_runtime.turn_tool_catalog import TurnToolCatalog
    from app.core.model_provider_adapter import ModelProfile, ModelProviderAdapter
    from app.models.model_dispatch import AgentModelDispatch

    sessions = sessionmaker(
        bind=db.get_bind(), join_transaction_mode="create_savepoint"
    )
    for module in (database, agent_turn_state, model_dispatch_service):
        monkeypatch.setattr(module, "SessionLocal", sessions)
    registry = ToolRegistry()
    dispatched = []

    class Arguments(BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: int

    async def handler(args, context):
        dispatched.append(args.value)
        if recover and args.value == 3:
            return {"error": "value_unavailable", "retry_value": 4}
        return {"value": args.value, "verified": True}

    registry.register(
        ToolDefinition(
            name="read_value",
            description="Read a value",
            args_model=Arguments,
            handler=handler,
            effect=ToolEffect.READ,
            concurrency_safe=True,
        )
    )
    catalog = TurnToolCatalog(
        builtins=registry.snapshot(),
        excluded=frozenset(),
        user_id=str(execution["user_id"]),
        user_pk=execution["user_id"],
        session_id=execution["session_id"],
        turn_id=execution["turn_id"],
        skills=(),
        mcp_tools=(),
        mcp_configs={},
    )

    async def create(*args, **kwargs):
        return catalog

    monkeypatch.setattr(TurnToolCatalog, "create", create)
    profile = ModelProfile(
        id="test",
        provider="test",
        model="test",
        display_name="test",
        api_base="",
        api_key_env="unused",
        supports_function_calling=True,
    )

    async def client(*args, **kwargs):
        return object(), profile

    monkeypatch.setattr(agent_strategy, "build_provider_client_for_role", client)
    requests = []

    if overflow:
        from app.agent_runtime.context_compactor import ActiveTurnContextReducer

        async def recompile(self, messages):
            # Compaction content is tested separately. Here a server rejects a
            # locally fitting request; the retry must keep durable step identity.
            return messages, True

        monkeypatch.setattr(ActiveTurnContextReducer, "on_context_too_long", recompile)

    async def stream(self, request):
        requests.append(request)
        if overflow and len(requests) == 1:
            error = RuntimeError("context_length_exceeded")
            error.status_code = 400
            raise error
        results = [
            json.loads(m["content"])
            for m in request.messages
            if m.get("role") == "tool"
        ]

        async def events():
            if not results or results[-1].get("error"):
                value = results[-1]["retry_value"] if results else 3
                yield ProviderStreamEvent(
                    tool_call_deltas=[
                        ProviderToolCallDelta(
                            index=0,
                            call_id=f"call-{len(results) + 1}",
                            name="read_value",
                            arguments_delta=json.dumps({"value": value}),
                        )
                    ],
                    stop_reason="tool_calls",
                )
            else:
                assert results[-1]["verified"] is True
                yield ProviderStreamEvent(
                    text_delta=f"Verified {results[-1]['value']}", stop_reason="stop"
                )

        return events()

    monkeypatch.setattr(ModelProviderAdapter, "start_stream", stream)
    ctx = StrategyContext(
        user_id=str(execution["user_id"]),
        user_pk=execution["user_id"],
        session_id=execution["session_id"],
        turn_id=execution["turn_id"],
        user_message="Read the available value, recover if necessary",
        assembled=AssembledContext(
            conversation_id=execution["session_id"],
            turn_id=execution["turn_id"],
            current_input="Read the available value",
            window_messages=[],
        ),
    )
    result = StrategyResult()
    events = [
        event async for event in agent_strategy.AgentLoopStrategy().execute(ctx, result)
    ]
    assert events and result.outcome == "completed"
    assert dispatched == ([3, 4] if recover else [3])
    assert result.final_answer == ("Verified 4" if recover else "Verified 3")
    assert len(requests) == len(dispatched) + 1 + int(overflow)
    assert result.steps_used == len(dispatched) + 1
    calls = db.query(AgentToolCall).order_by(AgentToolCall.model_call_order).all()
    assert [call.status for call in calls] == (
        ["failed", "completed"] if recover else ["completed"]
    )
    dispatches = db.query(AgentModelDispatch).all()
    assert len(dispatches) == len(requests)
    assert sum(row.status == "failed" for row in dispatches) == int(overflow)
    assert sum(row.status == "completed" for row in dispatches) == len(dispatched) + 1
