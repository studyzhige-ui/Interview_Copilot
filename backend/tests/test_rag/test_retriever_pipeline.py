"""Intent expansion, hybrid fusion, reranking, and evidence-gate tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from llama_index.core.schema import NodeWithScore

from app.rag import retriever
from app.rag.contracts import SearchIntent
from app.rag.reranker_registry import RerankerUnavailableError


class _Embedding:
    def __init__(self, calls):
        self.calls = calls

    def get_query_embedding(self, query):
        self.calls.append(query)
        return [0.1, 0.2]


class _Reranker:
    def __init__(self, scores):
        self.scores = scores

    def postprocess_nodes(self, nodes, query_bundle=None):
        return sorted(
            [
                NodeWithScore(
                    node=node.node,
                    score=self.scores.get(node.node.node_id, 0.0),
                )
                for node in nodes
            ],
            key=lambda node: node.score,
            reverse=True,
        )


class _BrokenReranker:
    def postprocess_nodes(self, nodes, query_bundle=None):
        raise RerankerUnavailableError("offline")


class _LanguageReranker:
    def postprocess_nodes(self, nodes, query_bundle=None):
        scores = (
            {"a": 0.9, "b": 0.2}
            if query_bundle.query_str == "中文问题"
            else {"a": 0.1, "b": 0.95}
        )
        return sorted(
            [
                NodeWithScore(node=node.node, score=scores[node.node.node_id])
                for node in nodes
            ],
            key=lambda node: node.score,
            reverse=True,
        )


def _hit(node_id, text, *, user_id=1, document_id="doc"):
    return {
        "id": node_id,
        "text": text,
        "score": 0.03,
        "user_id": user_id,
        "source_kind": "user_upload",
        "document_id": document_id,
    }


@pytest.fixture
def pipeline(monkeypatch):
    ctl = SimpleNamespace(
        user_pk=1,
        embedding_calls=[],
        search_calls=[],
        hits_by_query={},
        failing_queries=set(),
        hydrated=None,
    )
    monkeypatch.setattr(
        retriever,
        "Settings",
        SimpleNamespace(embed_model=_Embedding(ctl.embedding_calls)),
    )
    monkeypatch.setattr(retriever, "resolve_user_pk", lambda _db, _user: ctl.user_pk)
    monkeypatch.setattr(
        retriever,
        "current_rag_policy",
        lambda: SimpleNamespace(
            tokens=SimpleNamespace(query_reserve=96),
            retrieval=SimpleNamespace(
                candidate_count=4,
                final_count=3,
                max_intents=2,
                min_score=0.8,
                score_margin=0.02,
            ),
        ),
    )

    from app.rag import milvus_hybrid

    def search(
        _collection,
        *,
        query_text,
        query_dense,
        user_pk,
        top_k,
        filters=None,
    ):
        ctl.search_calls.append(
            {
                "query_text": query_text,
                "query_dense": query_dense,
                "user_pk": user_pk,
                "top_k": top_k,
                "filters": filters,
            }
        )
        if query_text in ctl.failing_queries:
            raise RuntimeError("milvus unavailable")
        return ctl.hits_by_query.get(query_text, [])[:top_k]

    monkeypatch.setattr(milvus_hybrid, "hybrid_search", search)

    def hydrate(node_ids):
        if ctl.hydrated is not None:
            rows = {row["node_id"]: row for row in ctl.hydrated}
            return [rows[node_id] for node_id in node_ids if node_id in rows]
        return [
            {"chunk_id": f"chunk-{node_id}", "node_id": node_id, "text": node_id}
            for node_id in node_ids
        ]

    monkeypatch.setattr(retriever, "_hydrate_node_ids", hydrate)
    monkeypatch.setattr(retriever, "_reranker", None)
    ctl.set_reranker = lambda value: monkeypatch.setattr(retriever, "_reranker", value)
    return ctl


async def _query(intents, **kwargs):
    return await retriever.query_knowledge_base(
        intents=intents,
        user_id="alice",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_dense_variants_share_one_precise_lexical_query(pipeline):
    intent = SearchIntent(
        query="缓存雪崩怎么处理",
        alternate_query="How to prevent cache avalanche",
        keywords=["缓存雪崩", "cache avalanche"],
    )
    pipeline.hits_by_query[intent.sparse_query] = [_hit("n1", "answer")]
    pipeline.set_reranker(_Reranker({"n1": 0.95}))
    result = await _query([intent])

    assert pipeline.embedding_calls == list(intent.dense_queries)
    assert len(pipeline.search_calls) == 2
    assert {call["query_text"] for call in pipeline.search_calls} == {
        intent.sparse_query
    }
    assert all(call["top_k"] == 4 for call in pipeline.search_calls)
    assert result.retrieval_hit is True


def test_reranker_matches_query_language_to_passage_language() -> None:
    from llama_index.core.schema import TextNode

    raw_nodes = [
        NodeWithScore(node=TextNode(id_="a", text="中文证据内容"), score=0.1),
        NodeWithScore(node=TextNode(id_="b", text="English evidence"), score=0.1),
    ]
    reranked = retriever._rerank_for_intents(
        _LanguageReranker(),
        [raw_nodes],
        [SearchIntent(query="中文问题", alternate_query="English question")],
    )

    assert [(node.node.node_id, node.score) for node in reranked] == [
        ("b", 0.95),
        ("a", 0.9),
    ]


@pytest.mark.asyncio
async def test_multi_intent_keeps_one_bounded_pool_per_intent(pipeline):
    first = SearchIntent(query="first", keywords=["first"])
    second = SearchIntent(query="second", keywords=["second"])
    pipeline.hits_by_query = {
        "first": [_hit("a", "same"), _hit("b", "B"), _hit("c", "C")],
        "second": [_hit("x", "same"), _hit("d", "D"), _hit("e", "E")],
    }
    pipeline.set_reranker(
        _Reranker({"a": 0.99, "b": 0.96, "c": 0.94, "d": 0.93, "e": 0.92})
    )
    result = await _query([first, second], include_diagnostics=True)

    per_intent = result.diagnostics["candidate_node_ids_by_intent"]
    assert len(per_intent) == 2
    assert all(len(group) <= 4 for group in per_intent)
    assert {"b", "c"} <= set(per_intent[0])
    assert {"d", "e"} <= set(per_intent[1])
    assert not ({"a", "x"} <= set(result.diagnostics["candidate_node_ids"]))
    assert not ({"a", "x"} <= {chunk["node_id"] for chunk in result.chunks})
    assert len(result.chunks) <= 3


@pytest.mark.asyncio
async def test_intent_count_is_capped_by_policy(pipeline):
    intents = [SearchIntent.from_query(f"q{index}") for index in range(4)]
    for index in range(2):
        pipeline.hits_by_query[f"q{index}"] = [_hit(f"n{index}", f"text {index}")]
    pipeline.set_reranker(_Reranker({"n0": 0.95, "n1": 0.94}))
    result = await _query(intents, include_diagnostics=True)
    assert result.diagnostics["intent_count"] == 2
    assert len(pipeline.search_calls) == 2


@pytest.mark.asyncio
async def test_failed_variant_does_not_discard_successful_intent(pipeline):
    intent = SearchIntent(
        query="中文查询",
        alternate_query="English query",
        keywords=["shared"],
    )
    pipeline.failing_queries = {"shared"}
    original = retriever.Settings.embed_model

    class _PartialEmbedding:
        def get_query_embedding(self, query):
            if query == "中文查询":
                raise RuntimeError("one variant failed")
            return original.get_query_embedding(query)

    retriever.Settings.embed_model = _PartialEmbedding()
    pipeline.failing_queries.clear()
    pipeline.hits_by_query["shared"] = [_hit("n1", "answer")]
    pipeline.set_reranker(_Reranker({"n1": 0.95}))
    assert (await _query([intent])).retrieval_hit is True


@pytest.mark.asyncio
async def test_cross_tenant_candidates_are_dropped(pipeline):
    pipeline.hits_by_query["redis"] = [_hit("foreign", "secret", user_id=2)]
    pipeline.set_reranker(_Reranker({"foreign": 0.99}))
    result = await _query([SearchIntent.from_query("redis")])
    assert result.state.empty_reason == "no_candidates"


@pytest.mark.asyncio
async def test_reranker_score_gate_and_margin_keep_pure_evidence(pipeline):
    pipeline.hits_by_query["redis"] = [
        _hit("a", "best"),
        _hit("b", "close"),
        _hit("c", "weak"),
    ]
    pipeline.set_reranker(_Reranker({"a": 0.95, "b": 0.94, "c": 0.81}))
    result = await _query([SearchIntent.from_query("redis")])
    assert [chunk["node_id"] for chunk in result.chunks] == ["a", "b"]
    assert all(chunk["score_source"] == "reranker" for chunk in result.chunks)


@pytest.mark.asyncio
async def test_explicit_calibration_threshold_disables_live_margin(pipeline):
    pipeline.hits_by_query["redis"] = [_hit("a", "best"), _hit("b", "other")]
    pipeline.set_reranker(_Reranker({"a": 0.95, "b": 0.5}))
    result = await _query([SearchIntent.from_query("redis")], min_score=0.0)
    assert [chunk["node_id"] for chunk in result.chunks] == ["a", "b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reranker", [None, _BrokenReranker()])
async def test_unavailable_reranker_fails_closed(pipeline, reranker):
    pipeline.hits_by_query["redis"] = [_hit("a", "answer")]
    pipeline.set_reranker(reranker)
    result = await _query([SearchIntent.from_query("redis")])
    assert result.state.empty_reason == "reranker_unavailable"
    assert result.state.fallback_used is True


@pytest.mark.asyncio
async def test_unresolved_user_and_all_search_failures_are_distinct(pipeline):
    pipeline.user_pk = None
    unresolved = await _query([SearchIntent.from_query("redis")])
    assert unresolved.state.empty_reason == "principal_unresolved"

    pipeline.user_pk = 1
    pipeline.failing_queries = {"redis"}
    failed = await _query([SearchIntent.from_query("redis")])
    assert failed.state.empty_reason == "milvus_unavailable"


@pytest.mark.asyncio
async def test_live_hydration_failure_is_explicit(pipeline):
    pipeline.hits_by_query["redis"] = [_hit("a", "answer")]
    pipeline.hydrated = []
    pipeline.set_reranker(_Reranker({"a": 0.95}))
    result = await _query([SearchIntent.from_query("redis")])
    assert result.state.empty_reason == "all_filtered_live_check"


@pytest.mark.asyncio
async def test_facade_attaches_planner_failure(monkeypatch):
    from app.rag.knowledge_retriever import knowledge_retriever
    from app.rag.retrieval_state import RetrievalResult

    async def fake_query(**kwargs):
        assert kwargs["intents"][0].query == "redis"
        return RetrievalResult()

    monkeypatch.setattr("app.rag.knowledge_retriever.query_knowledge_base", fake_query)
    result = await knowledge_retriever.retrieve(
        intents=[SearchIntent.from_query("redis")],
        user_id="alice",
        planner_failed=True,
    )
    assert result.state.planner_failed is True
