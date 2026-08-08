"""Tests for the user-scoped retrieval primitives in ``app.rag.retriever``.

The full RAG pipeline (Milvus + reranker + hydrate) is integration territory
and lives under ``@pytest.mark.slow``. These unit tests cover the pure
helpers that gate scope, dedup and scoring:

  * ``_hit_in_scope`` — tenant (+ optional source_kind) defence-in-depth.
  * ``milvus_hybrid._scope_expr`` — the Milvus server-side tenant filter expr.
  * ``_dedup_hits`` / ``_normalized_text_hash`` — deterministic dedup.
  * ``_score_passes`` — calibrated cross-encoder score gate.
  * ``RetrievalState`` / ``RetrievalResult`` — the structured-state contract
    that replaced the ``[SYSTEM_EMPTY_WARNING]`` sentinel protocol.
"""

from __future__ import annotations

import pytest

# ─────────────────────────────────────────────────────────────────────
# Scope helpers
# ─────────────────────────────────────────────────────────────────────


def test_hit_in_scope_enforces_tenant():
    from app.rag import retriever

    assert retriever._hit_in_scope({"user_id": 1, "source_kind": "user_upload"}, 1)
    # Cross-user leak must never survive, even past the server-side expr.
    assert not retriever._hit_in_scope({"user_id": 2, "source_kind": "user_upload"}, 1)
    # Missing user_id on the hit fails closed.
    assert not retriever._hit_in_scope({"source_kind": "user_upload"}, 1)


def test_hit_in_scope_optional_source_kind():
    from app.rag import retriever

    hit = {"user_id": 1, "source_kind": "improved_qa"}
    # Default: no source filter — the reranker is the relevance authority.
    assert retriever._hit_in_scope(hit, 1, None)
    assert retriever._hit_in_scope(hit, 1, "improved_qa")
    assert not retriever._hit_in_scope(hit, 1, "user_upload")


def test_hit_in_scope_blocks_cross_user_leak():
    """User A's query must never surface user B's chunks even if they slip
    through the vector-store filter."""
    from app.rag import retriever

    candidates = [
        {"user_id": 1, "source_kind": "user_upload", "text": "alice's note"},
        {"user_id": 2, "source_kind": "user_upload", "text": "bob's secret"},
        {"user_id": 1, "source_kind": "improved_qa", "text": "alice's QA"},
    ]
    survivors = [h for h in candidates if retriever._hit_in_scope(h, 1)]
    texts = {h["text"] for h in survivors}
    assert texts == {"alice's note", "alice's QA"}


# ─────────────────────────────────────────────────────────────────────
# Milvus 2.6 hybrid scope expression (the server-side tenant filter)
# ─────────────────────────────────────────────────────────────────────


def test_scope_expr_filters_by_user_pk():
    from app.rag import milvus_hybrid

    # Scope key is the stable users.id pk; no source_kind -> user filter only.
    assert milvus_hybrid._scope_expr(7, None) == "user_id == 7"


def test_scope_expr_adds_source_kind():
    from app.rag import milvus_hybrid

    expr = milvus_hybrid._scope_expr(7, {"source_kind": "interview_qa"})
    assert expr == 'user_id == 7 && source_kind == "interview_qa"'


def test_eq_rejects_injection():
    from app.rag import milvus_hybrid

    with pytest.raises(ValueError):
        milvus_hybrid._eq("source_kind", 'x" or user_id == 1 or "')


def test_hybrid_search_uses_strong_read_after_write_consistency(monkeypatch):
    from app.rag import milvus_hybrid

    class Client:
        kwargs = None

        def has_collection(self, _name):
            return True

        def hybrid_search(self, *_args, **kwargs):
            self.kwargs = kwargs
            return [[]]

    client = Client()
    monkeypatch.setattr(milvus_hybrid, "_get_client", lambda: client)

    assert (
        milvus_hybrid.hybrid_search(
            milvus_hybrid.KNOWLEDGE,
            query_text="redis",
            query_dense=[0.1] * 4,
            user_pk=7,
            top_k=3,
        )
        == []
    )
    assert client.kwargs["consistency_level"] == "Strong"


# ─────────────────────────────────────────────────────────────────────
# Deterministic dedup
# ─────────────────────────────────────────────────────────────────────


def test_normalized_text_hash_collapses_whitespace():
    from app.rag import retriever

    a = retriever._normalized_text_hash("Redis  缓存\n雪崩")
    b = retriever._normalized_text_hash("Redis 缓存 雪崩")
    assert a == b
    assert a != retriever._normalized_text_hash("Redis 缓存 击穿")


def test_dedup_hits_drops_same_id_keeps_first():
    from app.rag import retriever

    hits = [
        {"id": "n1", "text": "first copy", "score": 0.9},
        {"id": "n1", "text": "ignored duplicate", "score": 0.5},
        {"id": "n2", "text": "second", "score": 0.4},
    ]
    out = retriever._dedup_hits(hits)
    assert [h["id"] for h in out] == ["n1", "n2"]
    # Hits arrive in RRF order — the first (better-ranked) copy survives.
    assert out[0]["text"] == "first copy"


def test_dedup_hits_drops_same_normalized_text_across_rows():
    from app.rag import retriever

    hits = [
        {"id": "n1", "text": "Redis 缓存雪崩", "score": 0.9},
        {"id": "n2", "text": " Redis  缓存雪崩 ", "score": 0.8},  # same text, other row
        {"id": "n3", "text": "完全不同的内容", "score": 0.7},
    ]
    out = retriever._dedup_hits(hits)
    assert [h["id"] for h in out] == ["n1", "n3"]


# ─────────────────────────────────────────────────────────────────────
# Score gate (reranker branch only)
# ─────────────────────────────────────────────────────────────────────


def test_score_passes_meets_threshold():
    from app.rag import retriever

    assert retriever._score_passes(0.6, min_score=0.5)
    assert not retriever._score_passes(0.3, min_score=0.5)


def test_score_passes_rejects_none_and_rrf_scale():
    """The gate itself stays strict — RRF-scale scores (~0.03) never pass.
    The retriever's FALLBACK branch bypasses this gate entirely instead of
    relaxing it (score scales must not be mixed)."""
    from app.rag import retriever

    assert not retriever._score_passes(0.03, min_score=0.5)
    assert not retriever._score_passes(None, min_score=0.5)


# ─────────────────────────────────────────────────────────────────────
# Structured retrieval-state contract
# ─────────────────────────────────────────────────────────────────────


def test_retrieval_state_defaults_and_dict_shape():
    from app.rag.retrieval_state import RetrievalState

    state = RetrievalState()
    assert state.retrieval_hit is False
    assert state.empty_reason is None
    assert state.planner_failed is False
    assert state.fallback_used is False
    assert set(state.to_dict()) == {
        "retrieval_hit",
        "empty_reason",
        "planner_failed",
        "fallback_used",
    }


def test_empty_reason_enum_is_frozen():
    """The fixed values shared by online trace and offline eval —
    additions belong in retrieval_state.py + the evaluation plan, nowhere else."""
    from app.rag import retrieval_state as rs

    assert rs.EMPTY_REASONS == {
        "planner_no_retrieval",
        "no_candidates",
        "all_below_threshold",
        "all_filtered_live_check",
        "milvus_unavailable",
        "reranker_unavailable",
        "principal_unresolved",
    }


def test_score_source_enum_values():
    from app.rag import retrieval_state as rs

    assert rs.SCORE_SOURCE_RERANKER == "reranker"


def test_retrieval_result_hit_property():
    from app.rag.retrieval_state import RetrievalResult, RetrievalState

    assert RetrievalResult().retrieval_hit is False
    hit = RetrievalResult(
        chunks=[{"chunk_id": "dch_x"}],
        state=RetrievalState(retrieval_hit=True),
    )
    assert hit.retrieval_hit is True


# ─────────────────────────────────────────────────────────────────────
# Integration marker
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.slow
def test_query_knowledge_base_requires_live_milvus():
    """Marker test — the full integration is exercised in slow CI only.

    Kept here so ``pytest -m slow`` discovers it; the body is intentionally
    a noop because the unit suite cannot rely on a live Milvus / reranker.
    """
    pytest.skip("Requires live Milvus + reranker; covered in nightly CI.")
