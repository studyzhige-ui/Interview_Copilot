from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from app.conversation.chat_strategy import ChatPipelineStrategy
from app.conversation.strategy import StrategyContext, StrategyResult
from app.core.model_catalog import ModelProfile
from app.core.model_provider_adapter import ProviderStreamEvent, ProviderUsage
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


def test_chat_native_provider_path_uses_canonical_partition_and_usage(monkeypatch):
    from app.conversation import chat_strategy

    captured: dict = {}
    profile = ModelProfile(
        id="anthropic/test",
        provider="anthropic",
        display_name="Test",
        model="test",
        api_base="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
    )

    class FakeAdapter:
        prompt_cache_supported = True
        prompt_cache_enabled = True

        def __init__(self, *, client, profile):
            captured["client"] = client
            captured["profile"] = profile

        async def start_stream(self, request):
            captured["request"] = request

            async def events():
                yield ProviderStreamEvent(
                    usage=ProviderUsage(
                        prompt_tokens=12,
                        completion_tokens=0,
                        cache_read_tokens=8,
                        cache_creation_tokens=2,
                    )
                )
                yield ProviderStreamEvent(text_delta="native answer")
                yield ProviderStreamEvent(
                    usage=ProviderUsage(completion_tokens=3),
                    stop_reason="end_turn",
                )

            return events()

    monkeypatch.setattr(
        chat_strategy,
        "get_llm_for_role",
        lambda *_args, **_kwargs: (object(), profile),
    )
    monkeypatch.setattr(chat_strategy, "ModelProviderAdapter", FakeAdapter)
    assembled = AssembledContext(
        summary="lossy history",
        personalization_guidance="user guidance",
        retrieved_context="turn data",
        recent_turns=[{"role": "User", "content": "earlier"}],
        current_input="current direction",
    )
    ctx = StrategyContext(
        user_id="alice",
        session_id="session-1",
        user_message="current direction",
        assembled=assembled,
    )
    result = StrategyResult()

    async def run():
        return [event async for event in ChatPipelineStrategy().execute(ctx, result)]

    asyncio.run(run())

    request = captured["request"]
    assert "user guidance" not in request.system
    assert "turn data" not in request.system
    assert [message["role"] for message in request.messages] == ["user", "user", "user"]
    assert request.messages[-1]["content"].endswith(
        "[Current Query]\ncurrent direction"
    )
    assert result.final_answer == "native answer"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 3
    assert result.cache_read_tokens == 8
    assert result.cache_creation_tokens == 2
    assert result.prompt_cache_supported is True
    assert result.prompt_cache_enabled is True


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
