"""Capacity and canonical authority failures must not claim absent evidence."""

from types import SimpleNamespace

import pytest

from app.core.bounded_work import WorkCapacityExceeded
from app.rag.retrieval import pipeline as module
from app.rag.retrieval.candidates import IntentCandidates


@pytest.fixture
def pipeline(monkeypatch):
    policy = SimpleNamespace(
        retrieval=SimpleNamespace(
            max_intents=4,
            candidate_count=10,
            final_count=3,
            min_score=0.5,
            score_margin=None,
            search_timeout_seconds=1,
        )
    )
    monkeypatch.setattr(module, "current_rag_policy", lambda: policy)
    monkeypatch.setattr(
        module, "current_index_identity", lambda: SimpleNamespace(fingerprint="test")
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(module, "SessionLocal", Session)
    monkeypatch.setattr(module, "resolve_user_pk", lambda *_args: 7)
    instance = module.KnowledgeRetrievalPipeline()
    instance._reranker = object()
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["search", "rerank", "hydrate"])
async def test_capacity_is_not_no_candidates(pipeline, monkeypatch, stage):
    async def search(intent, **_kwargs):
        if stage == "search":
            raise WorkCapacityExceeded("busy")
        return IntentCandidates(
            intent, [{"id": "n1", "text": "evidence", "document_id": "d1"}]
        )

    async def rerank(_reranker, groups):
        if stage == "rerank":
            raise WorkCapacityExceeded("busy")
        return [
            [{**g.hits[0], "score": 0.9, "intent_ids": [g.intent.intent_id]}]
            for g in groups
        ]

    def hydrate(*_args, **_kwargs):
        raise WorkCapacityExceeded("busy")

    monkeypatch.setattr(module, "search_intent_candidates", search)
    monkeypatch.setattr(module, "rerank_groups", rerank)
    monkeypatch.setattr(pipeline, "_hydrate", hydrate)
    result = await pipeline.retrieve(intents=[{"query": "redis"}], user_id="alice")
    assert result.chunks == []
    assert result.state.degraded
    assert result.state.empty_reason == "capacity_exhausted"


@pytest.mark.asyncio
async def test_successful_empty_channel_does_not_hide_an_unavailable_channel(
    pipeline, monkeypatch
):
    async def search(intent, **_kwargs):
        return IntentCandidates(intent, [], ["TimeoutError"])

    monkeypatch.setattr(module, "search_intent_candidates", search)
    result = await pipeline.retrieve(intents=[{"query": "redis"}], user_id="alice")
    assert result.state.degraded
    assert result.state.empty_reason == "retrieval_incomplete"


@pytest.mark.asyncio
async def test_canonical_database_failure_never_falls_back_to_index_text(
    pipeline, monkeypatch
):
    async def search(intent, **_kwargs):
        return IntentCandidates(
            intent,
            [{"id": "n1", "text": "unauthorized index text", "document_id": "d1"}],
        )

    async def rerank(_reranker, groups):
        return [
            [{**g.hits[0], "score": 0.9, "intent_ids": [g.intent.intent_id]}]
            for g in groups
        ]

    def hydrate(*_args, **_kwargs):
        raise ConnectionError("canonical database unreachable")

    monkeypatch.setattr(module, "search_intent_candidates", search)
    monkeypatch.setattr(module, "rerank_groups", rerank)
    monkeypatch.setattr(pipeline, "_hydrate", hydrate)
    result = await pipeline.retrieve(intents=[{"query": "redis"}], user_id="alice")
    assert result.chunks == []
    assert result.state.degraded
    assert result.state.empty_reason == "canonical_unavailable"
