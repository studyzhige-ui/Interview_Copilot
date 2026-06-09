"""Unit tests for the unified query planner (``app.conversation.query_planner``).

After the v3 memory cutover the planner emits the RAG routing + a single
memory-body decision (``load_strategy``) in one LLM call. The old
``knowledge_topics`` / ``load_habit`` fields are gone (knowledge/ability now
lives in ``memory_ability_states`` and is always loaded by the universal pass;
habit folded into the two markdown docs). The planner's only memory input is
``learning_strategy_description`` (the universal-pass one-liner).

These tests stub the LLM proxy with deterministic JSON / exception responses
to exercise:
  * JSON / JSON-in-prose parsing
  * RAG routing (dense/sparse backfill + drop when RAG off)
  * the single ``load_strategy`` memory decision
  * global_memory_on=False privacy gate (memory section omitted + forced off)
  * conservative fallback on parse / vendor failure
  * the prompt-assembly order: user_message ends up exactly ONCE at the end.
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


# ─────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_parses_full_json_response(monkeypatch):
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": True,
        "dense_query": "Redis cache avalanche interview explanation",
        "sparse_query": "Redis cache avalanche",
        "load_strategy": True,
    }
    fake = _FakeLLM(json.dumps(payload))
    _patch_llm(monkeypatch, fake)

    plan = asyncio.run(planner.plan_query(
        user_message="那这个怎么答？",
        recent_turns=[{"role": "User", "content": "Redis cache avalanche"}],
        learning_strategy_description="先分析根因",
    ))

    assert plan.needs_knowledge_retrieval is True
    assert plan.dense_query == payload["dense_query"]
    assert plan.sparse_query == payload["sparse_query"]
    assert plan.load_strategy is True
    # No retired fields on the model.
    assert not hasattr(plan, "knowledge_topics")
    assert not hasattr(plan, "load_habit")
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
        "load_strategy": False,
    }
    wrapped = "Sure! Here's the plan:\n" + json.dumps(payload) + "\nLet me know if you need more."
    _patch_llm(monkeypatch, _FakeLLM(wrapped))

    plan = asyncio.run(planner.plan_query(
        user_message="How does HNSW work?",
        recent_turns=[],
    ))
    assert plan.needs_knowledge_retrieval is True
    assert plan.load_strategy is False


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
        "load_strategy": False,
    }
    fake = _FakeLLM(json.dumps(payload))
    _patch_llm(monkeypatch, fake)

    user_msg = "Explain Redis cache avalanche please"
    asyncio.run(planner.plan_query(
        user_message=user_msg,
        recent_turns=[{"role": "User", "content": "something earlier"}],
        learning_strategy_description="先分析根因",
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
        "load_strategy": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="hi",
        recent_turns=[],
    ))
    assert plan.needs_knowledge_retrieval is False
    assert plan.dense_query == ""
    assert plan.sparse_query == ""
    assert plan.load_strategy is False


# ─────────────────────────────────────────────────────────────────────
# Memory body selection — load_strategy
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_honours_load_strategy_true(monkeypatch):
    """When the LLM asks for the strategy body and memory is on, the planner
    surfaces ``load_strategy=True``."""
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": False,
        "dense_query": "",
        "sparse_query": "",
        "load_strategy": True,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="我该怎么准备行为面？",
        recent_turns=[],
        learning_strategy_description="STAR 法",
        global_memory_on=True,
    ))
    assert plan.load_strategy is True


def test_plan_query_prompt_includes_strategy_oneliner_when_memory_on(monkeypatch):
    """In normal (memory-on) mode the planner injects the learning_strategy
    one-liner into the [Available Memory Files] slot so the LLM can decide
    whether the full body is worth loading."""
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": False,
        "dense_query": "",
        "sparse_query": "",
        "load_strategy": False,
    }
    fake = _FakeLLM(json.dumps(payload))
    _patch_llm(monkeypatch, fake)

    asyncio.run(planner.plan_query(
        user_message="hi",
        recent_turns=[],
        learning_strategy_description="STAR 法已内化",
        global_memory_on=True,
    ))
    sent_prompt = fake.calls[0][0][0]
    assert "[Available Memory Files]" in sent_prompt
    assert "STAR 法已内化" in sent_prompt


# ─────────────────────────────────────────────────────────────────────
# Privacy gate
# ─────────────────────────────────────────────────────────────────────


def test_plan_query_with_recall_off_clears_memory_fields(monkeypatch):
    """When global_memory_on=False the planner MUST force ``load_strategy``
    off, even if the LLM happened to ask for it — the post-parse guard
    enforces the privacy contract."""
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": True,
        "dense_query": "x",
        "sparse_query": "x",
        "load_strategy": True,   # LLM ignored our instruction
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="x",
        recent_turns=[],
        learning_strategy_description="STAR 法",
        global_memory_on=False,
    ))
    assert plan.load_strategy is False


def test_plan_query_with_recall_off_omits_memory_section_from_prompt(monkeypatch):
    """In privacy mode the prompt should NOT leak the user's memory
    description — leave the slot out entirely."""
    from app.conversation import query_planner as planner

    payload = {
        "needs_knowledge_retrieval": False,
        "dense_query": "",
        "sparse_query": "",
        "load_strategy": False,
    }
    fake = _FakeLLM(json.dumps(payload))
    _patch_llm(monkeypatch, fake)

    asyncio.run(planner.plan_query(
        user_message="hi",
        recent_turns=[],
        learning_strategy_description="STAR (5) ...",
        global_memory_on=False,
    ))

    sent_prompt = fake.calls[0][0][0]
    assert "[Available Memory Files]" not in sent_prompt
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
        "load_strategy": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="Explain Kafka consumer rebalance",
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
        "load_strategy": False,
    }
    _patch_llm(monkeypatch, _FakeLLM(json.dumps(payload)))

    plan = asyncio.run(planner.plan_query(
        user_message="how are you",
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
        recent_turns=[{"role": "User", "content": "earlier discussed concurrency"}],
    ))
    assert plan.needs_knowledge_retrieval is False
    assert plan.load_strategy is False


def test_plan_query_falls_back_when_llm_raises(monkeypatch):
    """An async exception inside the LLM call must be caught silently."""
    from app.conversation import query_planner as planner

    class BoomLLM:
        async def acomplete(self, *args, **kwargs):
            raise RuntimeError("upstream provider 503")

    monkeypatch.setattr(planner, "agent_fast_llm", BoomLLM())

    plan = asyncio.run(planner.plan_query(
        user_message="anything",
        recent_turns=[],
    ))
    # Conservative fallback — DO NOT trigger RAG on the LLM failure.
    assert plan.needs_knowledge_retrieval is False
    assert plan.load_strategy is False


def test_plan_query_falls_back_on_invalid_pydantic_payload(monkeypatch):
    """Valid JSON but unparseable shape → fallback rather than crash."""
    from app.conversation import query_planner as planner

    # Pydantic will accept this and just default everything to False.
    # Confirm we don't crash and behavior is conservative.
    bad = json.dumps({"some_unknown_field": "value"})
    _patch_llm(monkeypatch, _FakeLLM(bad))

    plan = asyncio.run(planner.plan_query(
        user_message="hi there",
        recent_turns=[],
    ))
    assert plan.needs_knowledge_retrieval is False
    assert plan.load_strategy is False


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
    assert plan.load_strategy is False


def test_keyword_query_handles_mixed_lang_and_symbols():
    from app.conversation.query_planner import _keyword_query

    out = _keyword_query("Explain Redis 缓存雪崩 and C++ 多线程")
    assert "C++" in out
    assert "Redis" in out
    assert "缓存雪崩" in out or "多线程" in out
