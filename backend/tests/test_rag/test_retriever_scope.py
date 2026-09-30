"""Tests for canonical user-scoped retrieval primitives.

The full RAG pipeline (Milvus + reranker + hydrate) is integration territory
and lives under ``@pytest.mark.slow``. These unit tests cover the pure
helpers that gate scope, dedup and scoring:

  * candidate scope checks — tenant (+ optional source_kind) defence-in-depth.
  * ``hybrid_index._scope_expr`` — the Milvus server-side tenant filter expr.
  * RRF fusion / normalized text hashing — deterministic dedup.
  * ``RetrievalState`` / ``RetrievalResult`` — the structured-state contract
    that replaced the ``[SYSTEM_EMPTY_WARNING]`` sentinel protocol.
"""

from __future__ import annotations

import pytest

from app.rag.retrieval.candidates import _in_scope
from app.rag.retrieval.fusion import normalized_text_hash, reciprocal_rank_fusion


def _hit_in_scope(hit, user_pk, source_kind=None):
    return _in_scope(
        hit,
        user_pk=user_pk,
        source_kind=source_kind,
        document_ids=set(),
    )


def _dedup_hits(hits):
    return reciprocal_rank_fusion(
        [hits],
        weights=[1.0],
        rrf_k=60,
        limit=len(hits),
    )


# ─────────────────────────────────────────────────────────────────────
# Scope helpers
# ─────────────────────────────────────────────────────────────────────


def test_hit_in_scope_enforces_tenant():
    assert _hit_in_scope({"user_id": 1, "source_kind": "user_upload"}, 1)
    # Cross-user leak must never survive, even past the server-side expr.
    assert not _hit_in_scope({"user_id": 2, "source_kind": "user_upload"}, 1)
    # Missing user_id on the hit fails closed.
    assert not _hit_in_scope({"source_kind": "user_upload"}, 1)


def test_hit_in_scope_optional_source_kind():
    hit = {"user_id": 1, "source_kind": "improved_qa"}
    # Default: no source filter — the reranker is the relevance authority.
    assert _hit_in_scope(hit, 1, None)
    assert _hit_in_scope(hit, 1, "improved_qa")
    assert not _hit_in_scope(hit, 1, "user_upload")


def test_hit_in_scope_blocks_cross_user_leak():
    """User A's query must never surface user B's chunks even if they slip
    through the vector-store filter."""
    candidates = [
        {"user_id": 1, "source_kind": "user_upload", "text": "alice's note"},
        {"user_id": 2, "source_kind": "user_upload", "text": "bob's secret"},
        {"user_id": 1, "source_kind": "improved_qa", "text": "alice's QA"},
    ]
    survivors = [h for h in candidates if _hit_in_scope(h, 1)]
    texts = {h["text"] for h in survivors}
    assert texts == {"alice's note", "alice's QA"}


# ─────────────────────────────────────────────────────────────────────
# Milvus 2.6 hybrid scope expression (the server-side tenant filter)
# ─────────────────────────────────────────────────────────────────────


def test_sql_scope_uses_canonical_owners_before_ranking():
    from app.rag.hybrid_index import _scope
    from sqlalchemy.dialects import postgresql

    query = _scope(
        7, {"document_id": ["a", "b"], "source_kind": "manual_text"}
    ).compile(dialect=postgresql.dialect())
    sql = str(query)
    assert (
        "knowledge_documents" in sql
        and "document_chunks" in sql
        and "file_assets" in sql
    )
    assert (
        "retrieval_entries.user_id =" in sql and "knowledge_documents.user_id =" in sql
    )
    assert "document_chunks.user_id =" in sql
    assert ["a", "b"] in query.params.values() and 7 in query.params.values()


def test_filter_injection_is_data_not_sql():
    from app.rag.hybrid_index import _scope

    malicious = "x' OR 1=1 --"
    compiled = _scope(7, {"document_id": [malicious]}).compile()
    assert malicious not in str(compiled) and [malicious] in compiled.params.values()


def test_explicit_empty_scope_cannot_become_a_global_search():
    from app.rag.hybrid_index import _scope

    compiled = _scope(7, {"document_id": []}).compile()
    assert [] in compiled.params.values()


# ─────────────────────────────────────────────────────────────────────
# Deterministic dedup
# ─────────────────────────────────────────────────────────────────────


def test_normalized_text_hash_collapses_whitespace():
    a = normalized_text_hash("Redis  缓存\n雪崩")
    b = normalized_text_hash("Redis 缓存 雪崩")
    assert a == b
    assert a != normalized_text_hash("Redis 缓存 击穿")


def test_dedup_hits_drops_same_id_keeps_first():
    hits = [
        {"id": "n1", "text": "first copy", "score": 0.9},
        {"id": "n1", "text": "ignored duplicate", "score": 0.5},
        {"id": "n2", "text": "second", "score": 0.4},
    ]
    out = _dedup_hits(hits)
    assert [h["id"] for h in out] == ["n1", "n2"]
    # Hits arrive in RRF order — the first (better-ranked) copy survives.
    assert out[0]["text"] == "first copy"


def test_dedup_hits_drops_same_normalized_text_across_rows():
    hits = [
        {"id": "n1", "text": "Redis 缓存雪崩", "score": 0.9},
        {"id": "n2", "text": " Redis  缓存雪崩 ", "score": 0.8},  # same text, other row
        {"id": "n3", "text": "完全不同的内容", "score": 0.7},
    ]
    out = _dedup_hits(hits)
    assert [h["id"] for h in out] == ["n1", "n3"]


# ─────────────────────────────────────────────────────────────────────
# Structured retrieval-state contract
# ─────────────────────────────────────────────────────────────────────


def test_retrieval_state_defaults_and_dict_shape():
    from app.rag.domain.models import RetrievalState

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
    additions belong in domain.models + the evaluation plan, nowhere else."""
    from app.rag.domain import models as rs

    assert rs.EMPTY_REASONS == {
        "planner_no_retrieval",
        "no_candidates",
        "all_below_threshold",
        "all_filtered_live_check",
        "index_unavailable",
        "reranker_unavailable",
        "principal_unresolved",
        "capacity_exhausted",
        "retrieval_incomplete",
        "canonical_unavailable",
    }


def test_score_source_enum_values():
    from app.rag.domain import models as rs

    assert rs.SCORE_SOURCE_RERANKER == "reranker"


def test_retrieval_result_hit_property():
    from app.rag.domain.models import RetrievalResult, RetrievalState

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
def test_retrieval_pipeline_requires_real_local_models():
    """Marker test — the full integration is exercised in slow CI only.

    Kept here so ``pytest -m slow`` discovers it; the body is intentionally
    a noop because the unit suite cannot rely on a live Milvus / reranker.
    """
    pytest.skip(
        "Requires actual local embedding/reranker models; not executed by unit or database-only CI."
    )
