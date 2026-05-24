"""Unit tests for the query planner (``app.conversation.query_planner``).

The planner asks a fast LLM for a JSON blob describing retrieval intent.
We stub the LLM proxy so tests are deterministic and offline.

Coverage:
  * Successful JSON response → parsed QueryPlan with all fields preserved.
  * LLM emits JSON wrapped in prose → still parses (regex extraction).
  * LLM emits non-JSON → fallback plan returned.
  * Empty ``dense_query`` / ``sparse_query`` → planner backfills from
    ``standalone_query`` and the keyword extractor.
  * ``fallback_query_plan`` returns the documented defaults.
  * The keyword extractor handles Chinese + symbols correctly.
"""
from __future__ import annotations

import asyncio
import json

import pytest


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeLLM:
    """Async-completing stub that returns a canned response."""

    def __init__(self, response_text: str):
        self._text = response_text
        self.calls: list[tuple[tuple, dict]] = []

    async def acomplete(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _FakeResponse(self._text)


def _patch_llm(monkeypatch, fake_llm):
    """Patch the proxy the planner imports. Also patch the registry-level
    factory so any future code path that calls ``get_llm_for_role`` lands
    on the same fake."""
    from app.conversation import query_planner as planner
    from app.core import model_registry

    monkeypatch.setattr(planner, "agent_fast_llm", fake_llm)
    monkeypatch.setattr(model_registry, "get_llm_for_role", lambda role: fake_llm)


# ─────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_parses_full_json_response(monkeypatch):
    from app.conversation import query_planner as planner

    payload = {
        "standalone_query": "Explain Redis cache avalanche for interviews.",
        "dense_query": "Redis cache avalanche interview explanation",
        "sparse_query": "Redis cache avalanche",
        "needs_memory_retrieval": True,
        "memory_types": ["interaction_preference", "user_profile"],
        "needs_knowledge_retrieval": True,
        "knowledge_sources": ["interview_qa", "official_docs"],
        "answer_mode": "knowledge_qa",
        "reasoning": "technical interview question",
    }
    fake = _FakeLLM(json.dumps(payload))
    _patch_llm(monkeypatch, fake)

    plan = asyncio.run(planner.plan_query("那这个怎么答？", "Redis cache avalanche"))

    assert plan.standalone_query == payload["standalone_query"]
    assert plan.dense_query == payload["dense_query"]
    assert plan.sparse_query == payload["sparse_query"]
    assert plan.memory_types == payload["memory_types"]
    assert plan.knowledge_sources == payload["knowledge_sources"]
    assert plan.answer_mode == "knowledge_qa"
    assert plan.needs_memory_retrieval is True
    assert plan.needs_knowledge_retrieval is True
    # The planner must have asked the LLM for a JSON object.
    assert fake.calls, "planner should call the LLM exactly once"
    _, kwargs = fake.calls[0]
    assert kwargs.get("response_format", {}).get("type") == "json_object"


def test_plan_query_extracts_json_from_prose_wrapper(monkeypatch):
    """If the LLM rambles before the JSON, the planner still extracts it."""
    from app.conversation import query_planner as planner

    payload = {
        "standalone_query": "What is HNSW indexing?",
        "dense_query": "HNSW indexing graph nearest neighbour",
        "sparse_query": "HNSW indexing graph nearest neighbour",
        "needs_memory_retrieval": False,
        "memory_types": [],
        "needs_knowledge_retrieval": True,
        "knowledge_sources": ["official_docs"],
        "answer_mode": "knowledge_qa",
        "reasoning": "concept lookup",
    }
    wrapped = "Sure! Here's the plan:\n" + json.dumps(payload) + "\nLet me know if you need more."
    _patch_llm(monkeypatch, _FakeLLM(wrapped))

    plan = asyncio.run(planner.plan_query("How does HNSW work?", ""))
    assert plan.answer_mode == "knowledge_qa"
    assert plan.knowledge_sources == ["official_docs"]


# ─────────────────────────────────────────────────────────────────────
# Direct chat / preference update
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_handles_direct_chat_mode(monkeypatch):
    from app.conversation import query_planner as planner

    payload = {
        "standalone_query": "hi",
        "dense_query": "hi",
        "sparse_query": "hi",
        "needs_memory_retrieval": False,
        "memory_types": [],
        "needs_knowledge_retrieval": False,
        "knowledge_sources": [],
        "answer_mode": "direct_chat",
        "reasoning": "casual greeting",
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query("hi", ""))
    assert plan.answer_mode == "direct_chat"
    assert plan.needs_knowledge_retrieval is False
    assert plan.knowledge_sources == []


def test_plan_query_handles_preference_update(monkeypatch):
    from app.conversation import query_planner as planner

    payload = {
        "standalone_query": "From now on answer in English only.",
        "dense_query": "answer in English only",
        "sparse_query": "answer English only",
        "needs_memory_retrieval": True,
        "memory_types": ["interaction_preference"],
        "needs_knowledge_retrieval": False,
        "knowledge_sources": [],
        "answer_mode": "preference_update",
        "reasoning": "user is updating an interaction preference",
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        "From now on answer in English only.", ""
    ))
    assert plan.answer_mode == "preference_update"
    assert "interaction_preference" in plan.memory_types


# ─────────────────────────────────────────────────────────────────────
# Empty / partial JSON → planner backfills
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_backfills_missing_dense_and_sparse(monkeypatch):
    """If the LLM returns blank dense/sparse, the planner derives them."""
    from app.conversation import query_planner as planner

    payload = {
        "standalone_query": "Explain Kafka consumer rebalance",
        "dense_query": "   ",
        "sparse_query": "",
        "needs_memory_retrieval": False,
        "memory_types": [],
        "needs_knowledge_retrieval": True,
        "knowledge_sources": ["interview_qa"],
        "answer_mode": "knowledge_qa",
        "reasoning": "",
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query("explain it", "Kafka consumer rebalance"))
    assert plan.dense_query == "Explain Kafka consumer rebalance"
    # Sparse query backfilled from the keyword extractor.
    assert "Kafka" in plan.sparse_query or "kafka" in plan.sparse_query.lower()
    assert "rebalance" in plan.sparse_query.lower() or "rebalance" in plan.sparse_query


# ─────────────────────────────────────────────────────────────────────
# Failure → fallback
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_falls_back_on_non_json_response(monkeypatch):
    """LLM returns plain prose with no JSON → planner returns its fallback plan."""
    from app.conversation import query_planner as planner

    _patch_llm(monkeypatch, _FakeLLM("sorry I cannot answer right now."))

    plan = asyncio.run(planner.plan_query(
        "Tell me about Redis caching.", "earlier discussed concurrency"
    ))
    assert plan.standalone_query == "Tell me about Redis caching."
    assert plan.needs_memory_retrieval is True
    assert plan.needs_knowledge_retrieval is True
    assert plan.answer_mode == "knowledge_qa"
    assert plan.knowledge_sources == ["interview_qa"]
    assert "Fallback" in plan.reasoning


def test_plan_query_falls_back_when_llm_raises(monkeypatch):
    """An async exception inside the LLM call must be caught silently."""
    from app.conversation import query_planner as planner

    class BoomLLM:
        async def acomplete(self, *args, **kwargs):
            raise RuntimeError("upstream provider 503")

    boom = BoomLLM()
    monkeypatch.setattr(planner, "agent_fast_llm", boom)

    plan = asyncio.run(planner.plan_query("anything", ""))
    assert plan.needs_knowledge_retrieval is True
    assert "Fallback" in plan.reasoning


def test_plan_query_falls_back_on_invalid_pydantic_payload(monkeypatch):
    """Valid JSON but missing required fields → fallback rather than crash."""
    from app.conversation import query_planner as planner

    bad = json.dumps({"answer_mode": "knowledge_qa"})  # missing standalone_query etc
    _patch_llm(monkeypatch, _FakeLLM(bad))

    plan = asyncio.run(planner.plan_query("hi there", ""))
    # Falls back, so we see the user message echoed.
    assert plan.standalone_query == "hi there"
    assert "Fallback" in plan.reasoning


# ─────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────


def test_fallback_query_plan_returns_documented_defaults():
    from app.conversation.query_planner import fallback_query_plan

    plan = fallback_query_plan("How does HNSW work?")
    assert plan.standalone_query == "How does HNSW work?"
    assert plan.needs_memory_retrieval is True
    assert plan.needs_knowledge_retrieval is True
    assert set(plan.memory_types) == {
        "user_profile",
        "interaction_preference",
        "feedback_rule",
        "project_reference",
    }
    assert plan.knowledge_sources == ["interview_qa"]
    assert plan.answer_mode == "knowledge_qa"


def test_keyword_query_handles_mixed_lang_and_symbols():
    from app.conversation.query_planner import _keyword_query

    out = _keyword_query("Explain Redis 缓存雪崩 and C++ 多线程")
    # English+symbols token preserved.
    assert "C++" in out
    assert "Redis" in out
    # Chinese 2+ char clusters kept (Pinyin / single chars are NOT kept).
    assert "缓存雪崩" in out or "多线程" in out
