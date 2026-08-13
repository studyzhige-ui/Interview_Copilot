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
        }
    )
    _patch(monkeypatch, fake)
    plan = await planner.plan_query(user_message="你好", recent_turns=[])
    assert plan.needs_knowledge_retrieval is False
    assert plan.intents == []


@pytest.mark.asyncio
async def test_planner_emits_closed_bounded_owner_read_requests(monkeypatch):
    fake = _LLM(
        {
            "needs_knowledge_retrieval": False,
            "intents": [],
            "source_requests": [
                {
                    "kind": "history",
                    "query": "上次确认的回答方式",
                    "scope": "all_conversations",
                    "limit": 2,
                },
                {
                    "kind": "career_domains",
                    "query": "当前申请进度",
                    "sections": ["job_opportunities", "next_actions"],
                    "limit": 5,
                },
            ],
        }
    )
    _patch(monkeypatch, fake)

    plan = await planner.plan_query(
        user_message="结合上次讨论告诉我当前申请进度",
        recent_turns=[],
    )

    assert [request.kind for request in plan.source_requests] == [
        "history",
        "career_domains",
    ]
    assert plan.source_requests[0].limit == 2
    assert plan.source_requests[1].sections == [
        "job_opportunities",
        "next_actions",
    ]


@pytest.mark.asyncio
async def test_planner_deduplicates_owner_requests_and_never_routes_url(monkeypatch):
    fake = _LLM(
        {
            "needs_knowledge_retrieval": False,
            "intents": [],
            "source_requests": [
                {"kind": "artifacts", "query": "简历", "limit": 1},
                {"kind": "artifacts", "query": "求职信", "limit": 1},
            ],
        }
    )
    _patch(monkeypatch, fake)

    plan = await planner.plan_query(
        user_message="比较简历和求职信 https://example.test/job",
        recent_turns=[],
    )

    assert len(plan.source_requests) == 1
    assert plan.source_requests[0].kind == "artifacts"
    prompt = fake.calls[0][0]
    assert "Do not emit a source request for public URLs" in prompt
    assert '"kind":"url"' not in prompt


@pytest.mark.asyncio
async def test_planner_cannot_create_authoritative_owner_identities(monkeypatch):
    fake = _LLM(
        {
            "needs_knowledge_retrieval": False,
            "intents": [],
            "source_requests": [
                {
                    "kind": "artifacts",
                    "query": "resume",
                    "artifact_ids": ["model-invented-artifact"],
                },
                {
                    "kind": "career_domains",
                    "query": "job",
                    "sections": ["job_opportunities"],
                    "reference_kind": "job_opportunity",
                    "object_ids": ["model-invented-job"],
                    "include_process_events": True,
                },
            ],
        }
    )
    _patch(monkeypatch, fake)

    plan = await planner.plan_query(
        user_message="summarize my sources", recent_turns=[]
    )

    assert plan.source_requests[0].artifact_ids == []
    assert plan.source_requests[1].reference_kind is None
    assert plan.source_requests[1].object_ids == []
    assert plan.source_requests[1].include_process_events is False


@pytest.mark.asyncio
async def test_planner_resolves_multiple_debrief_questions_and_validates_indexes(
    monkeypatch,
):
    fake = _LLM(
        {
            "needs_knowledge_retrieval": False,
            "intents": [],
            "referenced_question_indexes": [5, 2, 5, 99],
        }
    )
    _patch(monkeypatch, fake)

    plan = await planner.plan_query(
        user_message="比较索引和超时那两道题的回答",
        recent_turns=[],
        interview_questions=[
            (2, "为什么使用数据库索引？"),
            (5, "服务超时时如何处理？"),
        ],
    )

    assert plan.referenced_question_indexes == [5, 2]
    prompt = fake.calls[0][0]
    assert "[Interview Questions]" in prompt
    assert "Q2: 为什么使用数据库索引？" in prompt
    assert "Q5: 服务超时时如何处理？" in prompt


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
    assert '"referenced_question_indexes"' in prompt
    assert '"dense_query"' not in prompt
    assert '"sub_queries"' not in prompt
