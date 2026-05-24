"""Unit tests for the unified query planner (``app.conversation.query_planner``).

After the planner-merge refactor the planner emits both the
query-rewrite fields AND the memory-body selection decisions in a
single LLM call. These tests stub the LLM proxy with deterministic
JSON / exception responses to exercise the parser, the validators,
and the fallback paths.
"""
import asyncio
import json
from dataclasses import dataclass


@dataclass
class _FakeResponse:
    text: str


class _FakeLLM:
    """Pretends to be the LlamaIndex async LLM proxy."""

    def __init__(self, text: str):
        self._text = text
        self.calls: list[tuple] = []

    async def acomplete(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _FakeResponse(self._text)


def _patch_llm(monkeypatch, fake_llm):
    """Patch the proxy the planner imports."""
    from app.conversation import query_planner as planner
    from app.core import model_registry

    monkeypatch.setattr(planner, "agent_fast_llm", fake_llm)
    monkeypatch.setattr(model_registry, "get_llm_for_role", lambda role: fake_llm)


_INDEX_LINES = [
    "- [Redis] strong | 8 facts | 上次 2026-05-21 — caching + pub/sub",
    "- [TCP] progressing | 3 facts | 上次 2026-05-14 — networking fundamentals",
]


# ─────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_parses_full_json_response(monkeypatch):
    from app.conversation import query_planner as planner

    payload = {
        "standalone_query": "Explain Redis cache avalanche for interviews.",
        "dense_query": "Redis cache avalanche interview explanation",
        "sparse_query": "Redis cache avalanche",
        "needs_knowledge_retrieval": True,
        "knowledge_topics": ["Redis"],
        "load_strategy": False,
        "load_habit": False,
    }
    fake = _FakeLLM(json.dumps(payload))
    _patch_llm(monkeypatch, fake)

    plan = asyncio.run(planner.plan_query(
        "那这个怎么答？",
        "Redis cache avalanche",
        knowledge_index_lines=_INDEX_LINES,
    ))

    assert plan.standalone_query == payload["standalone_query"]
    assert plan.dense_query == payload["dense_query"]
    assert plan.sparse_query == payload["sparse_query"]
    assert plan.needs_knowledge_retrieval is True
    assert plan.knowledge_topics == ["Redis"]
    assert plan.load_strategy is False
    assert plan.load_habit is False
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
        "needs_knowledge_retrieval": True,
        "knowledge_topics": [],
        "load_strategy": False,
        "load_habit": False,
    }
    wrapped = "Sure! Here's the plan:\n" + json.dumps(payload) + "\nLet me know if you need more."
    _patch_llm(monkeypatch, _FakeLLM(wrapped))

    plan = asyncio.run(planner.plan_query("How does HNSW work?", ""))
    assert plan.needs_knowledge_retrieval is True
    assert plan.knowledge_topics == []


# ─────────────────────────────────────────────────────────────────────
# Direct chat — no retrieval, no body loads
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_handles_direct_chat_mode(monkeypatch):
    from app.conversation import query_planner as planner

    payload = {
        "standalone_query": "hi",
        "dense_query": "hi",
        "sparse_query": "hi",
        "needs_knowledge_retrieval": False,
        "knowledge_topics": [],
        "load_strategy": False,
        "load_habit": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query("hi", ""))
    assert plan.needs_knowledge_retrieval is False
    assert plan.knowledge_topics == []
    assert plan.load_strategy is False
    assert plan.load_habit is False


# ─────────────────────────────────────────────────────────────────────
# Knowledge topics — filtering + cap
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_filters_invented_knowledge_topics(monkeypatch):
    """The LLM might invent topic names that aren't in the index — the
    planner must hard-filter them against the injected index so a
    downstream attach_active_bodies doesn't silently miss the load."""
    from app.conversation import query_planner as planner

    payload = {
        "standalone_query": "Explain Redis",
        "dense_query": "Redis avalanche",
        "sparse_query": "Redis",
        "needs_knowledge_retrieval": False,
        "knowledge_topics": ["Redis", "Kafka", "GraphQL"],  # only Redis is real
        "load_strategy": False,
        "load_habit": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        "Tell me about Redis",
        "",
        knowledge_index_lines=_INDEX_LINES,
    ))
    assert plan.knowledge_topics == ["Redis"]


def test_plan_query_caps_knowledge_topics_at_three(monkeypatch):
    """Even if the LLM returns five valid topics, the planner trims to 3."""
    from app.conversation import query_planner as planner

    index = [
        f"- [Topic{i}] strong | 1 facts | 上次 2026-05-21 — t{i}" for i in range(5)
    ]
    payload = {
        "standalone_query": "x",
        "dense_query": "x",
        "sparse_query": "x",
        "needs_knowledge_retrieval": False,
        "knowledge_topics": [f"Topic{i}" for i in range(5)],
        "load_strategy": False,
        "load_habit": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query("x", "", knowledge_index_lines=index))
    assert len(plan.knowledge_topics) == 3
    assert plan.knowledge_topics == ["Topic0", "Topic1", "Topic2"]


# ─────────────────────────────────────────────────────────────────────
# Privacy gate
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_with_recall_off_clears_memory_fields(monkeypatch):
    """When recall_on=False the planner MUST output empty memory
    selections, even if the LLM happened to suggest some — the
    post-parse guard enforces the privacy contract."""
    from app.conversation import query_planner as planner

    payload = {
        "standalone_query": "x",
        "dense_query": "x",
        "sparse_query": "x",
        "needs_knowledge_retrieval": True,
        "knowledge_topics": ["Redis"],   # LLM ignored our instruction
        "load_strategy": True,
        "load_habit": True,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        "x", "", knowledge_index_lines=_INDEX_LINES, recall_on=False,
    ))
    assert plan.knowledge_topics == []
    assert plan.load_strategy is False
    assert plan.load_habit is False


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
        "needs_knowledge_retrieval": True,
        "knowledge_topics": [],
        "load_strategy": False,
        "load_habit": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query("explain it", "Kafka consumer rebalance"))
    assert plan.dense_query == "Explain Kafka consumer rebalance"
    assert "Kafka" in plan.sparse_query or "kafka" in plan.sparse_query.lower()
    assert "rebalance" in plan.sparse_query.lower() or "rebalance" in plan.sparse_query


# ─────────────────────────────────────────────────────────────────────
# Failure → fallback (conservative: no RAG, no body loads)
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_falls_back_on_non_json_response(monkeypatch):
    """LLM returns plain prose with no JSON → planner returns its
    conservative fallback (no RAG, no memory bodies)."""
    from app.conversation import query_planner as planner

    _patch_llm(monkeypatch, _FakeLLM("sorry I cannot answer right now."))

    plan = asyncio.run(planner.plan_query(
        "Tell me about Redis caching.", "earlier discussed concurrency"
    ))
    assert plan.standalone_query == "Tell me about Redis caching."
    assert plan.needs_knowledge_retrieval is False
    assert plan.knowledge_topics == []
    assert plan.load_strategy is False
    assert plan.load_habit is False


def test_plan_query_falls_back_when_llm_raises(monkeypatch):
    """An async exception inside the LLM call must be caught silently."""
    from app.conversation import query_planner as planner

    class BoomLLM:
        async def acomplete(self, *args, **kwargs):
            raise RuntimeError("upstream provider 503")

    boom = BoomLLM()
    monkeypatch.setattr(planner, "agent_fast_llm", boom)

    plan = asyncio.run(planner.plan_query("anything", ""))
    # Conservative fallback — DO NOT trigger RAG on the LLM failure.
    assert plan.needs_knowledge_retrieval is False
    assert plan.knowledge_topics == []


def test_plan_query_falls_back_on_invalid_pydantic_payload(monkeypatch):
    """Valid JSON but missing required fields → fallback rather than crash."""
    from app.conversation import query_planner as planner

    bad = json.dumps({"some_unknown_field": "value"})  # missing standalone_query etc
    _patch_llm(monkeypatch, _FakeLLM(bad))

    plan = asyncio.run(planner.plan_query("hi there", ""))
    # Falls back, so we see the user message echoed.
    assert plan.standalone_query == "hi there"
    assert plan.needs_knowledge_retrieval is False


# ─────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────


def test_fallback_query_plan_returns_conservative_defaults():
    """The post-refactor fallback is conservative — no RAG, no memory
    bodies — so an LLM hiccup doesn't accidentally trigger an
    expensive turn against the user's intent."""
    from app.conversation.query_planner import fallback_query_plan

    plan = fallback_query_plan("How does HNSW work?")
    assert plan.standalone_query == "How does HNSW work?"
    assert plan.needs_knowledge_retrieval is False
    assert plan.knowledge_topics == []
    assert plan.load_strategy is False
    assert plan.load_habit is False
    # Sparse query still derived from the keyword extractor so the
    # fallback can at least produce a usable form.
    assert plan.sparse_query, "fallback should still backfill sparse_query"


def test_keyword_query_handles_mixed_lang_and_symbols():
    from app.conversation.query_planner import _keyword_query

    out = _keyword_query("Explain Redis 缓存雪崩 and C++ 多线程")
    assert "C++" in out
    assert "Redis" in out
    assert "缓存雪崩" in out or "多线程" in out
