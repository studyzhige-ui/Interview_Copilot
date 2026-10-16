"""An EOF or token limit is not proof of a completed user task."""

import pytest

from app.agent_runtime.tool_call_streaming import (
    ToolCallAssembler,
    ToolCallProtocolError,
)
from app.core.model_provider_adapter import (
    ModelProfile,
    ModelProviderAdapter,
    ProviderStreamEvent,
)
from app.conversation import chat_strategy
from app.conversation.context_contracts import AssembledContext
from app.conversation.strategy import StrategyContext, StrategyResult


@pytest.mark.parametrize(
    "stop", [None, "length", "max_tokens", "content_filter", "stop"]
)
@pytest.mark.asyncio
async def test_chat_and_agent_reject_incomplete_final_answers(monkeypatch, stop):
    profile = ModelProfile(
        id="test",
        provider="test",
        model="test",
        display_name="test",
        api_base="",
        api_key_env="unused",
    )

    async def client(*args, **kwargs):
        return object(), profile

    async def stream(self, request):
        async def events():
            yield ProviderStreamEvent(
                text_delta="partial or full answer", stop_reason=stop
            )

        return events()

    monkeypatch.setattr(chat_strategy, "build_provider_client_for_role", client)
    monkeypatch.setattr(ModelProviderAdapter, "start_stream", stream)
    ctx = StrategyContext(
        user_id="synthetic",
        session_id="synthetic",
        user_message="question",
        assembled=AssembledContext(current_input="question", window_messages=[]),
    )
    result = StrategyResult()
    events = [
        event
        async for event in chat_strategy.ChatPipelineStrategy().execute(ctx, result)
    ]
    assert events and "partial or full answer" in result.final_answer
    assert result.outcome == ("completed" if stop == "stop" else "blocked")
    assembler = ToolCallAssembler()
    assembler.feed(
        ProviderStreamEvent(text_delta="partial or full answer", stop_reason=stop)
    )
    if stop == "stop":
        assert assembler.finish() == []
    else:
        with pytest.raises(ToolCallProtocolError):
            assembler.finish()
