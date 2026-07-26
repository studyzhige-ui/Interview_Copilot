"""Engine-glue tests for the L1 RAG sources channel.

The retrieval → context-assembly → answer plumbing is covered by its own unit
tests; here we pin the ENGINE's three responsibilities for sources:

  * emit a single ``sources`` SSE event before generation (RAG turns only);
  * NOT emit it for non-RAG turns (empty sources);
  * persist a ``{"type": "sources"}`` content block alongside the answer.

``_prepare`` is stubbed to inject a ready ``StrategyContext`` so the test
doesn't drag in the planner / retriever / memory / transcript stack.
"""

from __future__ import annotations

import asyncio

from app.agent_runtime.harness_events import HarnessEventType
from app.conversation.engine import ConversationEngine
from app.conversation.strategy import StrategyContext


class _NoopStrategy:
    """Stands in for the L1 chat strategy — writes an answer, yields nothing."""

    name = "chat"

    async def execute(self, ctx, result):
        result.final_answer = "缓存击穿的解法见 [K1]。"
        result.assistant_blocks = [{"type": "text", "text": result.final_answer}]
        if False:  # pragma: no cover — make this an async generator
            yield


def _engine(monkeypatch, *, sources, capture: dict):
    engine = ConversationEngine(
        user_id="alice",
        session_id="s1",
        user_message="缓存击穿怎么办",
        strategy=_NoopStrategy(),
    )

    async def fake_prepare(self):
        self._ctx = StrategyContext(
            user_id="alice",
            session_id="s1",
            user_message="缓存击穿怎么办",
            sources=sources,
            retrieval_hit=bool(sources),
            needs_knowledge_retrieval=bool(sources),
        )
        self._retrieval_attempted = bool(sources)
        self._retrieval_hit = bool(sources)

    monkeypatch.setattr(ConversationEngine, "_prepare", fake_prepare, raising=True)

    # Capture what would be persisted; skip the real DB write + side effects.
    import app.conversation.engine as engine_mod

    def fake_append_turn(*, ai_blocks, **kwargs):
        capture["ai_blocks"] = ai_blocks

    monkeypatch.setattr(engine_mod.transcript_service, "append_turn", fake_append_turn)
    monkeypatch.setattr(
        ConversationEngine, "_fire_post_turn_maintenance", lambda self: None
    )
    monkeypatch.setattr(ConversationEngine, "_fire_telemetry", lambda self: None)
    return engine


async def _collect(engine) -> list:
    return [ev async for ev in engine.submit_message()]


def test_rag_turn_emits_sources_event_and_persists_block(monkeypatch):
    sources = [{"ref": "K1", "chunk_id": "dch_1", "text_preview": "缓存击穿……"}]
    capture: dict = {}
    engine = _engine(monkeypatch, sources=sources, capture=capture)

    events = asyncio.run(_collect(engine))

    source_events = [e for e in events if e.type == HarnessEventType.SOURCES]
    assert len(source_events) == 1
    assert source_events[0].data["sources"] == sources

    # Persisted blocks: the answer text + a trailing sources block.
    blocks = capture["ai_blocks"]
    assert blocks[0]["type"] == "text"
    assert blocks[-1] == {"type": "sources", "sources": sources}


def test_non_rag_turn_emits_no_sources_event(monkeypatch):
    capture: dict = {}
    engine = _engine(monkeypatch, sources=[], capture=capture)

    events = asyncio.run(_collect(engine))

    assert not any(e.type == HarnessEventType.SOURCES for e in events)
    # No sources block appended — just the answer text.
    assert all(b.get("type") != "sources" for b in capture["ai_blocks"])


def test_sources_event_serializes_to_wire_shape():
    from app.agent_runtime.harness_events import HarnessEvent

    ev = HarnessEvent.sources([{"ref": "K1"}], step=0, elapsed_ms=1.0)
    wire = ev.to_dict()
    assert wire["type"] == "sources"
    assert wire["data"]["sources"] == [{"ref": "K1"}]
