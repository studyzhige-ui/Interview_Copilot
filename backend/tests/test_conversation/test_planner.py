"""Conversation planner tests for the SearchIntent contract."""

from __future__ import annotations

import json

import pytest

import app.conversation.query_planner as planner


class _Response:
    def __init__(self, text):
        self.text = text


class _LLM:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    async def acomplete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if self.error:
            raise self.error
        text = (
            self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        )
        return _Response(text)


def _patch(monkeypatch, fake):
    monkeypatch.setattr(planner, "get_internal_llm", lambda _role: fake)


@pytest.mark.asyncio
async def test_planner_builds_bilingual_search_intent(monkeypatch):
    fake = _LLM(
        {
            "needs_knowledge_retrieval": True,
            "intents": [
                {
                    "query": "Redis 缓存雪崩怎么处理？",
                    "alternate_query": "How to prevent a Redis cache avalanche?",
                    "keywords": ["Redis", "缓存雪崩", "cache avalanche"],
                    "required_terms": ["Redis"],
                }
            ],
            "load_strategy": False,
        }
    )
    _patch(monkeypatch, fake)
    plan = await planner.plan_query(
        user_message="Redis 缓存雪崩怎么处理？",
        recent_turns=[],
    )
    assert plan.needs_knowledge_retrieval is True
    assert plan.planner_failed is False
    assert plan.intents[0].dense_queries == (
        "Redis 缓存雪崩怎么处理？",
        "How to prevent a Redis cache avalanche?",
    )
    assert plan.intents[0].sparse_query == "Redis 缓存雪崩 cache avalanche"
    assert plan.intents[0].required_terms == ["Redis"]


@pytest.mark.asyncio
async def test_required_terms_must_come_from_conversation(monkeypatch):
    fake = _LLM(
        {
            "needs_knowledge_retrieval": True,
            "intents": [
                {
                    "query": "解释缓存淘汰",
                    "keywords": ["缓存", "淘汰"],
                    "required_terms": ["Redis 7", "LFU"],
                }
            ],
        }
    )
    _patch(monkeypatch, fake)
    plan = await planner.plan_query(
        user_message="解释缓存淘汰",
        recent_turns=[{"role": "user", "content": "LFU 是什么？"}],
    )
    assert plan.intents[0].required_terms == ["LFU"]


@pytest.mark.asyncio
async def test_direct_chat_clears_stray_intents(monkeypatch):
    fake = _LLM(
        {
            "needs_knowledge_retrieval": False,
            "intents": [{"query": "stray"}],
            "load_strategy": False,
        }
    )
    _patch(monkeypatch, fake)
    plan = await planner.plan_query(user_message="你好", recent_turns=[])
    assert plan.needs_knowledge_retrieval is False
    assert plan.intents == []


@pytest.mark.asyncio
async def test_empty_retrieval_plan_uses_original_query(monkeypatch):
    fake = _LLM({"needs_knowledge_retrieval": True, "intents": []})
    _patch(monkeypatch, fake)
    plan = await planner.plan_query(user_message="Explain HNSW", recent_turns=[])
    assert plan.intents[0].query == "Explain HNSW"
    assert "HNSW" in plan.intents[0].keywords
    assert plan.planner_failed is False


@pytest.mark.asyncio
async def test_intents_are_capped_by_shared_policy(monkeypatch):
    maximum = planner.current_rag_policy().retrieval.max_intents
    fake = _LLM(
        {
            "needs_knowledge_retrieval": True,
            "intents": [{"query": f"intent {index}"} for index in range(maximum + 3)],
        }
    )
    _patch(monkeypatch, fake)
    plan = await planner.plan_query(user_message="Compare them", recent_turns=[])
    assert len(plan.intents) == maximum


@pytest.mark.asyncio
async def test_memory_off_removes_memory_slot_and_load(monkeypatch):
    fake = _LLM(
        {
            "needs_knowledge_retrieval": False,
            "intents": [],
            "load_strategy": True,
        }
    )
    _patch(monkeypatch, fake)
    plan = await planner.plan_query(
        user_message="hello",
        recent_turns=[],
        learning_strategy_description="private strategy",
        global_memory_on=False,
    )
    assert plan.load_strategy is False
    assert "private strategy" not in fake.calls[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["not json", RuntimeError("offline")])
async def test_planner_failures_fall_back_to_original_query(monkeypatch, failure):
    fake = _LLM(error=failure) if isinstance(failure, Exception) else _LLM(failure)
    _patch(monkeypatch, fake)
    plan = await planner.plan_query(user_message="How does HNSW work?", recent_turns=[])
    assert plan.planner_failed is True
    assert plan.needs_knowledge_retrieval is True
    assert plan.intents[0].query == "How does HNSW work?"


@pytest.mark.asyncio
async def test_prompt_advertises_only_current_schema(monkeypatch):
    fake = _LLM({"needs_knowledge_retrieval": False, "intents": []})
    _patch(monkeypatch, fake)
    await planner.plan_query(user_message="hello", recent_turns=[])
    prompt = fake.calls[0][0]
    assert '"intents"' in prompt
    assert '"alternate_query"' in prompt
    assert "Chinese ↔ English" in prompt
    assert '"required_terms"' in prompt
    assert '"dense_query"' not in prompt
    assert '"sub_queries"' not in prompt
