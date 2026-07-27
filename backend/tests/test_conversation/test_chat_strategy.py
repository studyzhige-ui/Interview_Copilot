from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.conversation.chat_strategy import ChatPipelineStrategy
from app.conversation.strategy import StrategyContext, StrategyResult
from app.services.chat.context_assembly_pipeline import AssembledContext


@pytest.mark.parametrize("uses_rag", [False, True])
def test_chat_answers_always_use_the_user_primary_model(monkeypatch, uses_rag):
    from app.conversation import chat_strategy

    calls: list[tuple[str, str | None]] = []

    class FakeLLM:
        async def astream_complete(self, prompt):
            async def chunks():
                yield SimpleNamespace(delta="answer")

            return chunks()

    def fake_get_llm(role, user_id=None):
        calls.append((role, user_id))
        return FakeLLM()

    monkeypatch.setattr(chat_strategy, "get_llm_for_role", fake_get_llm)

    ctx = StrategyContext(
        user_id="alice",
        session_id="session-1",
        user_message="question",
        assembled=AssembledContext(current_input="question"),
        needs_knowledge_retrieval=uses_rag,
    )
    result = StrategyResult()

    async def run():
        return [event async for event in ChatPipelineStrategy().execute(ctx, result)]

    events = asyncio.run(run())

    assert calls == [("primary", "alice")]
    assert result.final_answer == "answer"
    assert events
