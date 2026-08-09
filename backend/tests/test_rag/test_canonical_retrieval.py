"""Canonical candidate and retrieval orchestration contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.rag.domain.models import SearchIntent
from app.rag.retrieval.candidates import IntentCandidates
from app.rag.retrieval.reranking import select_coverage_aware


@pytest.mark.asyncio
async def test_candidate_search_runs_lexical_once_and_dense_per_variant(monkeypatch):
    from app.rag import milvus_hybrid
    from app.rag.retrieval import candidates

    calls: list[tuple[str, str]] = []

    class EmbedModel:
        def get_query_embedding(self, query):
            calls.append(("embed", query))
            return [0.1, 0.2]

    monkeypatch.setattr(
        candidates,
        "Settings",
        SimpleNamespace(embed_model=EmbedModel()),
    )
    monkeypatch.setattr(
        candidates,
        "current_index_identity",
        lambda: SimpleNamespace(embedding_dim=2),
    )
    monkeypatch.setattr(
        candidates,
        "current_rag_policy",
        lambda: SimpleNamespace(
            retrieval=SimpleNamespace(
                search_timeout_seconds=1,
                sparse_weight=1.0,
                dense_weight=1.0,
                rrf_k=60,
            )
        ),
    )

    def sparse(_collection, *, query_text, **_kwargs):
        calls.append(("sparse", query_text))
        return [
            {
                "id": "s",
                "text": "lexical",
                "user_id": 7,
                "document_id": "doc",
            }
        ]

    def dense(_collection, *, query_dense, **_kwargs):
        calls.append(("dense", str(query_dense)))
        return [
            {
                "id": "d",
                "text": "semantic",
                "user_id": 7,
                "document_id": "doc",
            }
        ]

    monkeypatch.setattr(milvus_hybrid, "sparse_search", sparse)
    monkeypatch.setattr(milvus_hybrid, "dense_search", dense)
    intent = SearchIntent(
        intent_id="I1",
        query="缓存雪崩",
        alternate_query="cache avalanche",
        keywords=["缓存雪崩", "cache avalanche"],
    )

    result = await candidates.search_intent_candidates(
        intent,
        user_pk=7,
        source_kind=None,
        candidate_count=10,
    )

    assert calls.count(("sparse", intent.sparse_query)) == 1
    assert [call for call in calls if call[0] == "embed"] == [
        ("embed", "缓存雪崩"),
        ("embed", "cache avalanche"),
    ]
    assert len([call for call in calls if call[0] == "dense"]) == 2
    assert {hit["id"] for hit in result.hits} == {"s", "d"}
    assert all(hit["intent_ids"] == ["I1"] for hit in result.hits)


@pytest.mark.asyncio
async def test_pipeline_preserves_missing_intent_for_grounding_gate(monkeypatch):
    from app.rag.grounding.builder import grounding_builder
    from app.rag.retrieval import pipeline as pipeline_module

    policy = SimpleNamespace(
        retrieval=SimpleNamespace(
            max_intents=4,
            candidate_count=10,
            final_count=3,
            min_score=0.5,
            score_margin=0.1,
        )
    )
    monkeypatch.setattr(pipeline_module, "current_rag_policy", lambda: policy)
    monkeypatch.setattr(
        pipeline_module,
        "current_index_identity",
        lambda: SimpleNamespace(fingerprint="fingerprint-v2"),
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(pipeline_module, "SessionLocal", Session)
    monkeypatch.setattr(pipeline_module, "resolve_user_pk", lambda _db, _user: 7)

    async def search(intent, **_kwargs):
        if intent.query == "second":
            raise RuntimeError("one intent unavailable")
        return IntentCandidates(
            intent=intent,
            hits=[
                {
                    "id": "n1",
                    "text": "first evidence",
                    "user_id": 7,
                    "document_id": "doc",
                }
            ],
        )

    async def rerank(_reranker, groups):
        return [
            [
                {
                    **group.hits[0],
                    "score": 0.95,
                    "intent_ids": [group.intent.intent_id],
                }
            ]
            for group in groups
        ]

    monkeypatch.setattr(pipeline_module, "search_intent_candidates", search)
    monkeypatch.setattr(pipeline_module, "rerank_groups", rerank)
    instance = pipeline_module.KnowledgeRetrievalPipeline()
    instance._reranker = object()
    monkeypatch.setattr(
        instance,
        "_hydrate",
        lambda _ids: [{"node_id": "n1", "text": "first evidence"}],
    )

    result = await instance.retrieve(
        intents=[SearchIntent(query="first"), SearchIntent(query="second")],
        user_id="alice",
        include_diagnostics=True,
    )
    grounding = grounding_builder.build(result, token_budget=200)

    assert result.retrieval_hit is True
    assert [intent.intent_id for intent in result.intents] == ["I1", "I2"]
    assert grounding.supported is False
    assert grounding.missing_intent_ids == ["I2"]
    assert result.state.degraded is True
    assert result.diagnostics["search_failed_intents"] == 1
    assert set(result.diagnostics["timings_ms"]) >= {
        "principal",
        "candidate_search",
        "rerank",
        "hydrate",
        "total",
    }


def test_coverage_selection_reserves_each_intent_before_global_fill():
    intents = [
        SearchIntent(intent_id="I1", query="first"),
        SearchIntent(intent_id="I2", query="second"),
    ]
    groups = [
        [
            {"id": "a", "text": "A", "score": 0.99, "intent_ids": ["I1"]},
            {"id": "b", "text": "B", "score": 0.98, "intent_ids": ["I1"]},
        ],
        [
            {"id": "c", "text": "C", "score": 0.90, "intent_ids": ["I2"]},
        ],
    ]

    selected = select_coverage_aware(
        groups,
        intents,
        min_score=0.8,
        final_count=3,
        score_margin=0.01,
    )

    assert [row["id"] for row in selected] == ["a", "b", "c"]
    assert {intent_id for row in selected for intent_id in row["intent_ids"]} == {
        "I1",
        "I2",
    }


@pytest.mark.asyncio
async def test_pipeline_reranker_failure_fails_closed(monkeypatch):
    from app.rag.retrieval import pipeline as pipeline_module

    policy = SimpleNamespace(
        retrieval=SimpleNamespace(
            max_intents=4,
            candidate_count=10,
            final_count=3,
            min_score=0.5,
            score_margin=0.1,
        )
    )
    monkeypatch.setattr(pipeline_module, "current_rag_policy", lambda: policy)
    monkeypatch.setattr(
        pipeline_module,
        "current_index_identity",
        lambda: SimpleNamespace(fingerprint="fingerprint-v2"),
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(pipeline_module, "SessionLocal", Session)
    monkeypatch.setattr(pipeline_module, "resolve_user_pk", lambda _db, _user: 7)

    async def search(intent, **_kwargs):
        return IntentCandidates(
            intent=intent,
            hits=[
                {
                    "id": "n1",
                    "text": "evidence",
                    "user_id": 7,
                    "document_id": "doc",
                }
            ],
        )

    async def fail_rerank(_reranker, _groups):
        raise TimeoutError("reranker timeout")

    monkeypatch.setattr(pipeline_module, "search_intent_candidates", search)
    monkeypatch.setattr(pipeline_module, "rerank_groups", fail_rerank)
    instance = pipeline_module.KnowledgeRetrievalPipeline()
    instance._reranker = object()

    result = await instance.retrieve(
        intents=[SearchIntent.from_query("redis")],
        user_id="alice",
    )

    assert result.retrieval_hit is False
    assert result.state.empty_reason == "reranker_unavailable"
    assert result.state.degraded is True
