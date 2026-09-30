"""Wire safety and trusted per-tool argument budgets must agree end to end."""

import asyncio
import json
from types import SimpleNamespace as NS
from pydantic import BaseModel
import pytest
from app.agent_runtime.tool_call_streaming import (
    ToolCallAssembler,
    ToolCallProtocolError,
)
from app.agent_runtime.tool_registry import (
    ToolDefinition,
    ToolRegistryView,
    AgentToolContext,
    parse_tool_arguments,
)
from app.agent_runtime import tool_call_executor as executor
from app.agent_runtime.tool_policy import ToolEffect
from app.core.config import settings
from tests.conftest import patch_session_locals
from tests.test_agent_runtime.test_tool_call_executor import _turn


class Args(BaseModel):
    jd_text: str


@pytest.mark.parametrize("approved_large_input", [True, False])
def test_stream_parse_plan_execute_share_declared_budget(
    db_session, monkeypatch, approved_large_input
):
    patch_session_locals(monkeypatch, db_session, executor)
    user, conversation, turn = _turn(db_session)
    received = []

    async def handler(args, _ctx):
        received.append(args.jd_text)
        return {"characters": len(args.jd_text)}

    entry = ToolDefinition(
        "jd",
        "read supplied JD",
        Args,
        handler,
        effect=ToolEffect.READ,
        max_argument_chars=56_000 if approved_large_input else None,
    )
    view = ToolRegistryView({"jd": entry})
    text = "工" * 4500
    wire = json.dumps({"jd_text": text}, ensure_ascii=False)
    assembler = ToolCallAssembler()
    for offset in range(0, len(wire), 37):
        assembler.feed(
            NS(
                stop_reason=None,
                tool_call_deltas=[
                    NS(
                        index=0,
                        call_id="long-jd",
                        name="jd",
                        arguments_delta=wire[offset : offset + 37],
                    )
                ],
            )
        )
    assembler.feed(NS(stop_reason="tool_calls", tool_call_deltas=[]))
    call = assembler.finish()[0]
    arguments = parse_tool_arguments(call.function.arguments)
    ctx = AgentToolContext(
        user.username, conversation.id, turn_id=turn.id, user_pk=user.id
    )

    async def run():
        dispatch_plan = await view.plan_call("jd", arguments, ctx)
        if not approved_large_input:
            assert dispatch_plan.error["error"] == "tool_args_too_large"
            return
        assert dispatch_plan.error is None
        plan = await executor.plan_tool_call(
            call_id="long-jd",
            turn_id=turn.id,
            tool_name="jd",
            arguments=arguments,
            effect=ToolEffect.READ,
            max_argument_chars=dispatch_plan.max_argument_chars,
        )
        result = await executor.execute_tool_call(
            call_id="long-jd",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="jd",
            arguments=arguments,
            effect=ToolEffect.READ,
            timeout_seconds=1,
            plan=plan,
            dispatch=lambda: view.dispatch("jd", arguments, ctx),
        )
        assert result == {"characters": 4500}

    asyncio.run(run())
    assert received == ([text] if approved_large_input else [])


def test_transport_still_rejects_unbounded_arguments(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_MAX_TOOL_WIRE_ARG_CHARS", 20)
    assembler = ToolCallAssembler()
    with pytest.raises(ToolCallProtocolError):
        assembler.feed(
            NS(
                stop_reason=None,
                tool_call_deltas=[
                    NS(
                        index=0,
                        call_id="too-large",
                        name="jd",
                        arguments_delta="a" * 21,
                    )
                ],
            )
        )
    with pytest.raises(ValueError):
        parse_tool_arguments("a" * 21)
