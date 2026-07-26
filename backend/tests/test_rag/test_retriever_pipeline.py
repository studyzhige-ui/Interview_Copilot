"""Orchestration tests for ``app.rag.retriever.query_knowledge_base``.

The pipeline's external edges (embedding, Milvus hybrid search, reranker,
Postgres hydrate, principal resolution) are monkeypatched so each branch of
the retrieval flow can be asserted as BEHAVIOUR:

  * reranker branch — threshold gate + ``score_source=reranker``;
  * retriever-fallback branch — ``RerankerUnavailableError`` → RRF order,
    ``score_source=retriever_fallback``, NO threshold (RRF-scale scores
    survive);
  * every ``empty_reason`` the retriever itself emits;
  * the facade's ``planner_failed`` stamping and the L2 tool's output shape.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from llama_index.core.schema import NodeWithScore

from app.core.config import settings
from app.rag import retriever
from app.rag.reranker_registry import RerankerUnavailableError
from app.rag.retrieval_state import RetrievalResult, RetrievalState


class _FakeEmbed:
    def get_query_embedding(self, query: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _RaisingReranker:
    """Simulates a remote reranker whose call fails (transport / bad body)."""

    def postprocess_nodes(self, nodes, query_bundle=None):
        raise RerankerUnavailableError("simulated remote failure")


class _ScoringReranker:
    """Returns the nodes re-scored with fixed cross-encoder-scale scores."""

    def __init__(self, scores: list[float]):
        self._scores = scores

    def postprocess_nodes(self, nodes, query_bundle=None):
        return [
            NodeWithScore(node=n.node, score=s) for n, s in zip(nodes, self._scores)
        ]


def _hit(node_id: str, text: str, score: float, *, user_id: int = 1) -> dict:
    return {
        "id": node_id,
        "text": text,
        "score": score,
        "user_id": user_id,
        "source_kind": "user_upload",
        "document_id": "kdoc_1",
    }


@pytest.fixture
def pipeline(monkeypatch):
    """Patch the pipeline's edges; returns a control object tests tweak.

    Defaults: principal resolves to pk=1, hydrate mirrors the requested node
    ids (all live), no reranker installed (tests set one explicitly).
    """
    ctl = SimpleNamespace(
        hits=[],
        user_pk=1,
        search_exc=None,
        hydrated=None,
        hits_by_sparse=None,
        search_calls=[],
        fail_on_sparse=None,
    )

    monkeypatch.setattr(
        retriever,
        "Settings",
        SimpleNamespace(embed_model=_FakeEmbed()),
    )
    monkeypatch.setattr(
        retriever,
        "resolve_user_pk",
        lambda db, uid: ctl.user_pk,
    )

    from app.rag import milvus_hybrid

    def fake_search(coll, *, query_text, query_dense, user_pk, top_k, filters=None):
        ctl.last_query_text = query_text
        ctl.search_calls.append({"query_text": query_text, "top_k": top_k})
        if ctl.search_exc is not None:
            raise ctl.search_exc
        if ctl.fail_on_sparse is not None and query_text == ctl.fail_on_sparse:
            raise RuntimeError(f"milvus down for {query_text!r}")
        if ctl.hits_by_sparse is not None:
            return list(ctl.hits_by_sparse.get(query_text, []))
        return list(ctl.hits)

    monkeypatch.setattr(milvus_hybrid, "hybrid_search", fake_search)

    def fake_hydrate(node_ids: list[str]) -> list[dict]:
        if ctl.hydrated is not None:
            by_node = {h["node_id"]: h for h in ctl.hydrated}
            return [by_node[nid] for nid in node_ids if nid in by_node]
        return [
            {"chunk_id": f"dch_{nid}", "node_id": nid, "text": f"text-{nid}"}
            for nid in node_ids
        ]

    monkeypatch.setattr(retriever, "_hydrate_node_ids", fake_hydrate)
    monkeypatch.setattr(retriever, "_reranker", None)
    ctl.set_reranker = lambda r: monkeypatch.setattr(retriever, "_reranker", r)
    return ctl


async def _run(**kwargs):
    defaults = {
        "dense_query": "Redis 缓存雪崩怎么解决",
        "sparse_query": "Redis 雪崩",
        "user_id": "alice",
    }
    defaults.update(kwargs)
    return await retriever.query_knowledge_base(**defaults)


# ─────────────────────────────────────────────────────────────────────
# Fallback branch — the headline A1 behaviour
# ─────────────────────────────────────────────────────────────────────


async def test_fallback_keeps_rrf_order_and_skips_threshold(pipeline):
    """Remote reranker failure → RRF-ordered top-N with RRF-scale scores
    that the reranker threshold must NOT filter."""
    pipeline.hits = [_hit("n1", "雪崩", 0.032), _hit("n2", "击穿", 0.016)]
    pipeline.set_reranker(_RaisingReranker())

    result = await _run()

    assert result.state.retrieval_hit is True
    assert result.state.fallback_used is True
    assert [c["node_id"] for c in result.chunks] == ["n1", "n2"]
    assert all(c["score_source"] == "retriever_fallback" for c in result.chunks)
    # RRF-scale scores survive untouched (0.032 << RAG_MIN_SCORE=0.5).
    assert result.chunks[0]["score"] == pytest.approx(0.032)


async def test_fallback_when_reranker_never_initialised(pipeline):
    """Defensive path: _reranker is None → same explicit fallback."""
    pipeline.hits = [_hit("n1", "雪崩", 0.03)]

    result = await _run()

    assert result.state.fallback_used is True
    assert result.chunks[0]["score_source"] == "retriever_fallback"


# ─────────────────────────────────────────────────────────────────────
# Reranker branch — threshold gate + score_source
# ─────────────────────────────────────────────────────────────────────


async def test_reranker_branch_filters_below_threshold(pipeline):
    pipeline.hits = [_hit("n1", "相关", 0.03), _hit("n2", "无关", 0.02)]
    pipeline.set_reranker(_ScoringReranker([0.9, 0.2]))

    result = await _run()

    assert result.state.retrieval_hit is True
    assert result.state.fallback_used is False
    assert [c["node_id"] for c in result.chunks] == ["n1"]
    assert result.chunks[0]["score_source"] == "reranker"
    assert result.chunks[0]["score"] == pytest.approx(0.9)


async def test_all_below_threshold_returns_empty(pipeline):
    pipeline.hits = [_hit("n1", "a", 0.03), _hit("n2", "b", 0.02)]
    pipeline.set_reranker(_ScoringReranker([0.2, 0.1]))

    result = await _run()

    assert result.chunks == []
    assert result.state.retrieval_hit is False
    assert result.state.empty_reason == "all_below_threshold"


# ─────────────────────────────────────────────────────────────────────
# Empty reasons from the surrounding stages
# ─────────────────────────────────────────────────────────────────────


async def test_milvus_unavailable(pipeline):
    pipeline.search_exc = RuntimeError("milvus down")

    result = await _run()

    assert result.chunks == []
    assert result.state.empty_reason == "milvus_unavailable"


async def test_principal_unresolved(pipeline):
    pipeline.user_pk = None

    result = await _run()

    assert result.chunks == []
    assert result.state.empty_reason == "principal_unresolved"


async def test_no_candidates(pipeline):
    pipeline.hits = []

    result = await _run()

    assert result.state.empty_reason == "no_candidates"


async def test_cross_tenant_hits_are_dropped(pipeline):
    """Defence-in-depth: a hit with another user's pk never survives, even
    if the server-side expr let it through."""
    pipeline.hits = [_hit("n-evil", "bob's secret", 0.9, user_id=2)]
    pipeline.set_reranker(_ScoringReranker([0.9]))

    result = await _run()

    assert result.chunks == []
    assert result.state.empty_reason == "no_candidates"


async def test_live_check_filtering_all_yields_empty_reason(pipeline):
    """Hydrate dropping every candidate (stale Milvus rows) → explicit
    all_filtered_live_check, with fallback_used passed through."""
    pipeline.hits = [_hit("n1", "a", 0.03)]
    pipeline.hydrated = []  # everything failed the live check
    pipeline.set_reranker(_RaisingReranker())

    result = await _run()

    assert result.chunks == []
    assert result.state.empty_reason == "all_filtered_live_check"
    assert result.state.fallback_used is True


async def test_sparse_query_drives_bm25_input(pipeline):
    pipeline.hits = [_hit("n1", "a", 0.03)]
    pipeline.set_reranker(_ScoringReranker([0.9]))

    await _run(dense_query="自然语言完整问题", sparse_query="关键词 串")

    assert pipeline.last_query_text == "关键词 串"


async def test_single_query_uses_fusion_top_k(pipeline):
    pipeline.hits = [_hit("n1", "a", 0.03)]
    pipeline.set_reranker(_ScoringReranker([0.9]))

    await _run()

    # One Milvus pass at the single-query budget.
    assert len(pipeline.search_calls) == 1
    assert pipeline.search_calls[0]["top_k"] == settings.FUSION_TOP_K


# ─────────────────────────────────────────────────────────────────────
# Multi-sub-query map-reduce
# ─────────────────────────────────────────────────────────────────────


async def test_sub_queries_fan_out_merge_and_dedup(pipeline):
    """Each sub-query is one Milvus pass at the smaller budget; the merged
    pool is deduped, then a single rerank picks the final top-N."""
    pipeline.hits_by_sparse = {
        "雪崩 kw": [_hit("n1", "雪崩内容", 0.03)],
        "击穿 kw": [
            _hit("n2", "击穿内容", 0.03),
            _hit("n1", "雪崩内容", 0.02),
        ],  # n1 dup
    }
    pipeline.set_reranker(_ScoringReranker([0.9, 0.8]))

    result = await _run(
        dense_query="缓存雪崩和击穿的区别",
        sparse_query="缓存 雪崩 击穿",
        sub_queries=[
            {"dense_query": "缓存雪崩怎么解决", "sparse_query": "雪崩 kw"},
            {"dense_query": "缓存击穿怎么解决", "sparse_query": "击穿 kw"},
        ],
    )

    # Two sub-query passes, each at the per-sub-query budget.
    assert len(pipeline.search_calls) == 2
    assert {c["top_k"] for c in pipeline.search_calls} == {
        settings.SUB_QUERY_FUSION_TOP_K
    }
    assert {c["query_text"] for c in pipeline.search_calls} == {"雪崩 kw", "击穿 kw"}
    # n1 hit by both sub-queries → deduped to one candidate; 2 unique total.
    assert [c["node_id"] for c in result.chunks] == ["n1", "n2"]
    assert result.state.retrieval_hit is True


async def test_sub_queries_capped_at_max(pipeline):
    pipeline.hits = [_hit("n1", "a", 0.03)]
    pipeline.set_reranker(_ScoringReranker([0.9]))

    # More sub-queries supplied than MAX_SUB_QUERIES — fan-out is capped.
    await _run(
        sub_queries=[
            {"dense_query": f"q{i}", "sparse_query": f"kw{i}"}
            for i in range(settings.MAX_SUB_QUERIES + 2)
        ]
    )

    assert len(pipeline.search_calls) == settings.MAX_SUB_QUERIES


async def test_empty_sub_queries_falls_back_to_single(pipeline):
    pipeline.hits = [_hit("n1", "a", 0.03)]
    pipeline.set_reranker(_ScoringReranker([0.9]))

    await _run(sub_queries=[])

    # Empty sub-queries collapse to a single top-level pass.
    assert len(pipeline.search_calls) == 1
    assert pipeline.search_calls[0]["top_k"] == settings.FUSION_TOP_K


async def test_sub_queries_fallback_keeps_higher_scored_dup(pipeline):
    """Multi-query + reranker down: the merged pool is sorted by score before
    dedup, so the higher-scored copy of a cross-sub-query dup survives and
    carries through as the fallback score (§2.6 retention rule)."""
    pipeline.hits_by_sparse = {
        "low kw": [_hit("n1", "dup chunk", 0.02)],
        "high kw": [_hit("n1", "dup chunk", 0.05)],  # same chunk, higher score
    }
    pipeline.set_reranker(_RaisingReranker())

    result = await _run(
        dense_query="overall",
        sparse_query="overall kw",
        sub_queries=[
            {"dense_query": "a", "sparse_query": "low kw"},
            {"dense_query": "b", "sparse_query": "high kw"},
        ],
    )

    assert result.state.fallback_used is True
    assert [c["node_id"] for c in result.chunks] == ["n1"]
    assert result.chunks[0]["score_source"] == "retriever_fallback"
    # The higher-scored (0.05) copy won the dedup, not the spec-order-first.
    assert result.chunks[0]["score"] == pytest.approx(0.05)


async def test_one_sub_query_milvus_failure_degrades_whole_turn(pipeline):
    """gather propagates a single sub-query's Milvus failure → the whole turn
    degrades to milvus_unavailable (no partial-success semantics)."""
    pipeline.hits_by_sparse = {"ok kw": [_hit("n1", "x", 0.03)]}
    pipeline.fail_on_sparse = "bad kw"
    pipeline.set_reranker(_ScoringReranker([0.9]))

    result = await _run(
        sub_queries=[
            {"dense_query": "a", "sparse_query": "ok kw"},
            {"dense_query": "b", "sparse_query": "bad kw"},
        ]
    )

    assert result.chunks == []
    assert result.state.empty_reason == "milvus_unavailable"


def test_retrieval_specs_helper():
    """Unit-level: spec building caps, blank-side fallback, single fallback."""
    specs = retriever._retrieval_specs("D", "S", None)
    assert specs == [("D", "S")]
    specs = retriever._retrieval_specs("D", "S", [])
    assert specs == [("D", "S")]
    # Blank dense side falls back to sparse; blank sub-query dropped.
    specs = retriever._retrieval_specs(
        "D",
        "S",
        [
            {"dense_query": "a", "sparse_query": ""},
            {"dense_query": "", "sparse_query": ""},
        ],
    )
    assert specs == [("a", "a")]


# ─────────────────────────────────────────────────────────────────────
# Facade stamping + L2 tool output shape
# ─────────────────────────────────────────────────────────────────────


async def test_facade_stamps_planner_failed(monkeypatch):
    from app.rag import knowledge_retriever as facade_mod

    async def fake_query(**kwargs):
        return RetrievalResult(
            chunks=[{"chunk_id": "dch_1", "node_id": "n1", "text": "t"}],
            state=RetrievalState(retrieval_hit=True),
        )

    monkeypatch.setattr(facade_mod, "query_knowledge_base", fake_query)

    result = await facade_mod.knowledge_retriever.retrieve(
        dense_query="q",
        sparse_query="kw",
        user_id="alice",
        planner_failed=True,
    )
    assert result.state.planner_failed is True
    assert result.retrieval_hit is True


async def test_search_knowledge_tool_output_shape(monkeypatch):
    from app.agent_runtime.tools import knowledge as tool_mod
    from app.rag.knowledge_retriever import knowledge_retriever

    async def fake_retrieve(**kwargs):
        return RetrievalResult(
            chunks=[
                {
                    "chunk_id": "dch_1",
                    "node_id": "n1",
                    "text": "Redis 缓存雪崩……",
                    "source_kind": "user_upload",
                    "document_title": "Redis 笔记",
                    "score": 0.91,
                }
            ],
            state=RetrievalState(retrieval_hit=True),
        )

    monkeypatch.setattr(knowledge_retriever, "retrieve", fake_retrieve)

    out = await tool_mod._search_knowledge_handler(
        tool_mod.SearchKnowledgeArgs(query="redis"),
        SimpleNamespace(user_id="alice"),
    )

    assert out["retrieval_hit"] is True
    assert out["count"] == 1
    chunk = out["chunks"][0]
    assert chunk == {
        "text": "Redis 缓存雪崩……",
        "source": "user_upload",
        "document_title": "Redis 笔记",
        "chunk_id": "dch_1",
        "score": 0.91,
    }
