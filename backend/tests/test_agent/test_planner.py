"""Unit tests for the unified query planner (``app.conversation.query_planner``).

After the planner-merge refactor the planner emits the RAG routing +
memory selection decisions in a single LLM call. ``standalone_query``
is no longer in the schema — the answer LLM resolves pronouns itself
using the [Recent Turns] slot it already sees.

These tests stub the LLM proxy with deterministic JSON / exception
responses to exercise:
  * JSON / JSON-in-prose parsing
  * topic-name filtering against the injected index
  * global_memory_on=False privacy gate
  * conservative fallback on parse / vendor failure
  * structured inputs (session_state + recent_turns instead of
    a pre-rendered ``rewrite_context`` string)
  * the prompt-assembly order: user_message ends up exactly ONCE at
    the end of the planner's prompt.
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
    from app.conversation import query_planner as planner
    monkeypatch.setattr(planner, "agent_fast_llm", fake_llm)


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
        "needs_knowledge_retrieval": True,
        "dense_query": "Redis cache avalanche interview explanation",
        "sparse_query": "Redis cache avalanche",
        "knowledge_topics": ["Redis"],
        "load_strategy": False,
        "load_habit": False,
    }
    fake = _FakeLLM(json.dumps(payload))
    _patch_llm(monkeypatch, fake)

    plan = asyncio.run(planner.plan_query(
        user_message="那这个怎么答？",
        session_state={"mode": "general"},
        recent_turns=[{"role": "User", "content": "Redis cache avalanche"}],
        knowledge_index_lines=_INDEX_LINES,
    ))

    assert plan.needs_knowledge_retrieval is True
    assert plan.dense_query == payload["dense_query"]
    assert plan.sparse_query == payload["sparse_query"]
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
        "needs_knowledge_retrieval": True,
        "dense_query": "HNSW indexing graph nearest neighbour",
        "sparse_query": "HNSW indexing graph nearest neighbour",
        "knowledge_topics": [],
        "load_strategy": False,
        "load_habit": False,
    }
    wrapped = "Sure! Here's the plan:\n" + json.dumps(payload) + "\nLet me know if you need more."
    _patch_llm(monkeypatch, _FakeLLM(wrapped))

    plan = asyncio.run(planner.plan_query(
        user_message="How does HNSW work?",
        session_state={},
        recent_turns=[],
    ))
    assert plan.needs_knowledge_retrieval is True
    assert plan.knowledge_topics == []


# ─────────────────────────────────────────────────────────────────────
# Prompt assembly: user message appears exactly ONCE at the END
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_prompt_has_user_message_exactly_once_at_end(monkeypatch):
    """The user's actual message must NOT be duplicated in the prompt
    (pre-refactor it appeared twice — once in rewrite_context's
    [Current Query] slot and once as a separate trailing line). The
    new planner puts it exactly once, as the final slot, where the
    LLM attends most strongly."""
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": False,
        "dense_query": "",
        "sparse_query": "",
        "knowledge_topics": [],
        "load_strategy": False,
        "load_habit": False,
    }
    fake = _FakeLLM(json.dumps(payload))
    _patch_llm(monkeypatch, fake)

    user_msg = "Explain Redis cache avalanche please"
    asyncio.run(planner.plan_query(
        user_message=user_msg,
        session_state={"mode": "general"},
        recent_turns=[{"role": "User", "content": "something earlier"}],
    ))

    sent_prompt = fake.calls[0][0][0]  # first positional arg = the prompt string
    assert sent_prompt.count(user_msg) == 1, (
        f"user_message must appear exactly once in the planner prompt, "
        f"got {sent_prompt.count(user_msg)} occurrences"
    )
    # And it must be the LAST slot.
    current_query_idx = sent_prompt.rfind("[Current Query]")
    last_user_msg_idx = sent_prompt.rfind(user_msg)
    assert current_query_idx >= 0, "[Current Query] slot missing"
    assert last_user_msg_idx > current_query_idx, (
        "user_message should appear under the [Current Query] slot"
    )


# ─────────────────────────────────────────────────────────────────────
# Direct chat — no retrieval, no body loads
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_handles_direct_chat_mode(monkeypatch):
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": False,
        "dense_query": "",
        "sparse_query": "",
        "knowledge_topics": [],
        "load_strategy": False,
        "load_habit": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="hi",
        session_state={},
        recent_turns=[],
    ))
    assert plan.needs_knowledge_retrieval is False
    assert plan.dense_query == ""
    assert plan.sparse_query == ""
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
        "needs_knowledge_retrieval": False,
        "dense_query": "",
        "sparse_query": "",
        "knowledge_topics": ["Redis", "Kafka", "GraphQL"],  # only Redis is real
        "load_strategy": False,
        "load_habit": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="Tell me about Redis",
        session_state={},
        recent_turns=[],
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
        "needs_knowledge_retrieval": False,
        "dense_query": "",
        "sparse_query": "",
        "knowledge_topics": [f"Topic{i}" for i in range(5)],
        "load_strategy": False,
        "load_habit": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="x",
        session_state={},
        recent_turns=[],
        knowledge_index_lines=index,
    ))
    assert len(plan.knowledge_topics) == 3
    assert plan.knowledge_topics == ["Topic0", "Topic1", "Topic2"]


# ─────────────────────────────────────────────────────────────────────
# Privacy gate
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_with_recall_off_clears_memory_fields(monkeypatch):
    """When global_memory_on=False the planner MUST output empty memory
    selections, even if the LLM happened to suggest some — the
    post-parse guard enforces the privacy contract."""
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": True,
        "dense_query": "x",
        "sparse_query": "x",
        "knowledge_topics": ["Redis"],   # LLM ignored our instruction
        "load_strategy": True,
        "load_habit": True,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="x",
        session_state={},
        recent_turns=[],
        knowledge_index_lines=_INDEX_LINES,
        global_memory_on=False,
    ))
    assert plan.knowledge_topics == []
    assert plan.load_strategy is False
    assert plan.load_habit is False


def test_plan_query_with_recall_off_omits_memory_section_from_prompt(monkeypatch):
    """In privacy mode the prompt should NOT leak the user's memory
    indexes / descriptions — leave the slot out entirely."""
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": False,
        "dense_query": "",
        "sparse_query": "",
        "knowledge_topics": [],
        "load_strategy": False,
        "load_habit": False,
    }
    fake = _FakeLLM(json.dumps(payload))
    _patch_llm(monkeypatch, fake)

    asyncio.run(planner.plan_query(
        user_message="hi",
        session_state={},
        recent_turns=[],
        knowledge_index_lines=_INDEX_LINES,
        strategy_description="STAR (5) ...",
        habit_description="weekly mocks",
        global_memory_on=False,
    ))

    sent_prompt = fake.calls[0][0][0]
    assert "[Available Memory Files]" not in sent_prompt
    assert "Redis" not in sent_prompt
    assert "STAR" not in sent_prompt


# ─────────────────────────────────────────────────────────────────────
# Empty / partial JSON → planner backfills
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_backfills_missing_dense_and_sparse(monkeypatch):
    """If the LLM returns blank dense/sparse but says
    needs_knowledge_retrieval=True, the planner derives them from
    user_message."""
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": True,
        "dense_query": "   ",
        "sparse_query": "",
        "knowledge_topics": [],
        "load_strategy": False,
        "load_habit": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="Explain Kafka consumer rebalance",
        session_state={},
        recent_turns=[],
    ))
    assert plan.dense_query == "Explain Kafka consumer rebalance"
    assert "Kafka" in plan.sparse_query


def test_plan_query_drops_dense_sparse_when_rag_off(monkeypatch):
    """When the LLM says needs_knowledge_retrieval=False the planner
    drops dense_query / sparse_query (even if the LLM emitted them
    by accident). The engine never reads these in that branch."""
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": False,
        "dense_query": "lingering text",
        "sparse_query": "lingering text",
        "knowledge_topics": [],
        "load_strategy": False,
        "load_habit": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="how are you",
        session_state={},
        recent_turns=[],
    ))
    assert plan.dense_query == ""
    assert plan.sparse_query == ""


# ─────────────────────────────────────────────────────────────────────
# Failure → fallback (conservative: no RAG, no body loads)
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_falls_back_on_non_json_response(monkeypatch):
    """LLM returns plain prose with no JSON → planner returns its
    conservative fallback (no RAG, no memory bodies)."""
    from app.conversation import query_planner as planner

    _patch_llm(monkeypatch, _FakeLLM("sorry I cannot answer right now."))

    plan = asyncio.run(planner.plan_query(
        user_message="Tell me about Redis caching.",
        session_state={},
        recent_turns=[{"role": "User", "content": "earlier discussed concurrency"}],
    ))
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

    monkeypatch.setattr(planner, "agent_fast_llm", BoomLLM())

    plan = asyncio.run(planner.plan_query(
        user_message="anything",
        session_state={},
        recent_turns=[],
    ))
    # Conservative fallback — DO NOT trigger RAG on the LLM failure.
    assert plan.needs_knowledge_retrieval is False
    assert plan.knowledge_topics == []


def test_plan_query_falls_back_on_invalid_pydantic_payload(monkeypatch):
    """Valid JSON but unparseable shape → fallback rather than crash."""
    from app.conversation import query_planner as planner

    # Pydantic will accept this and just default everything to False/[].
    # Confirm we don't crash and behavior is conservative.
    bad = json.dumps({"some_unknown_field": "value"})
    _patch_llm(monkeypatch, _FakeLLM(bad))

    plan = asyncio.run(planner.plan_query(
        user_message="hi there",
        session_state={},
        recent_turns=[],
    ))
    assert plan.needs_knowledge_retrieval is False
    assert plan.knowledge_topics == []


# ─────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────


def test_fallback_query_plan_returns_conservative_defaults():
    """The fallback is conservative — no RAG, no memory bodies — so
    an LLM hiccup doesn't accidentally trigger an expensive turn
    against the user's intent."""
    from app.conversation.query_planner import fallback_query_plan

    plan = fallback_query_plan("How does HNSW work?")
    assert plan.needs_knowledge_retrieval is False
    assert plan.dense_query == ""
    assert plan.sparse_query == ""
    assert plan.knowledge_topics == []
    assert plan.load_strategy is False
    assert plan.load_habit is False


def test_keyword_query_handles_mixed_lang_and_symbols():
    from app.conversation.query_planner import _keyword_query

    out = _keyword_query("Explain Redis 缓存雪崩 and C++ 多线程")
    assert "C++" in out
    assert "Redis" in out
    assert "缓存雪崩" in out or "多线程" in out
