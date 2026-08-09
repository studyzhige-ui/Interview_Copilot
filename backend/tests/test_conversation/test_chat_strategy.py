from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from app.conversation.chat_strategy import ChatPipelineStrategy
from app.conversation.strategy import StrategyContext, StrategyResult
from app.rag.domain.models import RetrievalResult, SearchIntent
from app.rag.grounding.builder import grounding_builder
from app.services.chat.context_assembly_pipeline import AssembledContext


@pytest.mark.parametrize("uses_rag", [False, True])
def test_chat_answers_always_use_the_user_primary_model(monkeypatch, uses_rag):
    from app.conversation import chat_strategy

    calls: list[tuple[str, str | None]] = []
    generation_options: list[dict] = []

    class FakeLLM:
        async def astream_complete(self, prompt, **kwargs):
            generation_options.append(kwargs)

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
        retrieval_hit=uses_rag,
    )
    result = StrategyResult()

    async def run():
        return [event async for event in ChatPipelineStrategy().execute(ctx, result)]

    events = asyncio.run(run())

    assert calls == [("primary", "alice")]
    assert generation_options == [{"max_tokens": ctx.assembled.output_token_reserve}]
    assert result.final_answer == "answer"
    assert events


def test_chat_refuses_without_calling_model_when_retrieval_misses(monkeypatch):
    from app.conversation import chat_strategy

    monkeypatch.setattr(
        chat_strategy,
        "get_llm_for_role",
        lambda *_args, **_kwargs: pytest.fail("answer model must not be called"),
    )
    ctx = StrategyContext(
        user_id="alice",
        session_id="session-1",
        user_message="What is the missing fact?",
        assembled=AssembledContext(current_input="question"),
        needs_knowledge_retrieval=True,
        retrieval_hit=False,
    )
    result = StrategyResult()

    async def run():
        return [event async for event in ChatPipelineStrategy().execute(ctx, result)]

    events = asyncio.run(run())

    assert result.final_answer.startswith("The available sources")
    assert result.steps_used == 0
    assert events[-1].data["delta"] == result.final_answer


def test_chat_refuses_when_qualified_product_is_absent_from_evidence(monkeypatch):
    from app.conversation import chat_strategy

    monkeypatch.setattr(
        chat_strategy,
        "get_llm_for_role",
        lambda *_args, **_kwargs: pytest.fail("answer model must not be called"),
    )
    retrieval_result = RetrievalResult(
        chunks=[
            {
                "node_id": "n1",
                "text": "PostgreSQL Serializable uses predicate locking.",
                "intent_ids": ["I1"],
            }
        ],
        intents=[
            SearchIntent(
                intent_id="I1",
                query="How does Amazon Aurora implement PostgreSQL Serializable?",
                required_terms=["Amazon Aurora", "PostgreSQL Serializable"],
            )
        ],
    )
    grounding = grounding_builder.build(retrieval_result, token_budget=8_000)
    ctx = StrategyContext(
        user_id="alice",
        session_id="session-1",
        user_message="How does Amazon Aurora implement PostgreSQL Serializable?",
        assembled=AssembledContext(
            current_input="question",
            retrieval_result=retrieval_result,
            grounding=grounding,
            retrieved_context=grounding.context_text,
            sources=grounding.sources,
            prompt_token_limit=8_000,
        ),
        needs_knowledge_retrieval=True,
        retrieval_hit=True,
    )
    result = StrategyResult()

    async def run():
        return [event async for event in ChatPipelineStrategy().execute(ctx, result)]

    asyncio.run(run())

    assert result.final_answer.startswith("The available sources")
