"""Tests for user-scoped retrieval logic in ``app.rag.retriever``.

The full RAG pipeline (Milvus + Reranker) is integration territory and
lives under ``@pytest.mark.slow``. These unit tests focus on the
scope-gating primitives that decide *which user's nodes are visible
to a given query*:

  * ``_allowed_user_ids`` — strict private-only scoping.
  * ``_metadata_matches_scope`` — node-level visibility check.
  * ``_build_metadata_filters`` — Milvus MetadataFilter construction.
  * ``_query_terms`` / ``_lexical_overlap`` — Chinese + English term
    extraction and lexical-overlap scoring (debug / source signal only).
  * ``_score_passes`` — single absolute score threshold, no fallback.

Plus a behavioural assertion that *user A's query never returns user B's
documents* by routing fake nodes through the same filter helpers used by
``query_knowledge_base``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


# ─────────────────────────────────────────────────────────────────────
# Scope helpers
# ─────────────────────────────────────────────────────────────────────


def test_allowed_user_ids_is_strictly_private():
    from app.rag import retriever

    assert retriever._allowed_user_ids("alice", "interview_qa") == ["alice"]
    assert retriever._allowed_user_ids("alice", "personal_memory") == ["alice"]
    # Empty user_id → empty allowlist (caller should bail).
    assert retriever._allowed_user_ids("", "interview_qa") == []


def test_metadata_scope_requires_user_and_source_match():
    from app.rag import retriever

    matches = retriever._metadata_matches_scope

    assert matches(
        {"user_id": "alice", "source_type": "interview_qa"},
        ["alice"],
        "interview_qa",
    )
    # Wrong user
    assert not matches(
        {"user_id": "bob", "source_type": "interview_qa"},
        ["alice"],
        "interview_qa",
    )
    # Wrong source_type
    assert not matches(
        {"user_id": "alice", "source_type": "personal_memory"},
        ["alice"],
        "interview_qa",
    )
    # source_type=None disables source filter, but user_id still enforced.
    assert matches(
        {"user_id": "alice", "source_type": "anything"}, ["alice"], None,
    )
    # Empty allowed list disables user filter entirely.
    assert matches(
        {"user_id": "bob", "source_type": "interview_qa"}, [], "interview_qa",
    )


# ─────────────────────────────────────────────────────────────────────
# Milvus MetadataFilter construction
# ─────────────────────────────────────────────────────────────────────


def test_build_metadata_filters_uses_eq_for_single_user():
    from llama_index.core.vector_stores import FilterOperator
    from app.rag import retriever

    flt = retriever._build_metadata_filters(["alice"], "interview_qa")
    keys = {(f.key, f.operator) for f in flt.filters}
    assert ("user_id", FilterOperator.EQ) in keys
    assert ("source_type", FilterOperator.EQ) in keys
    # Find the user_id filter and check the literal value.
    user_filter = next(f for f in flt.filters if f.key == "user_id")
    assert user_filter.value == "alice"


def test_build_metadata_filters_uses_in_for_multiple_users():
    from llama_index.core.vector_stores import FilterOperator
    from app.rag import retriever

    flt = retriever._build_metadata_filters(["alice", "shared"], "interview_qa")
    user_filter = next(f for f in flt.filters if f.key == "user_id")
    assert user_filter.operator == FilterOperator.IN
    assert list(user_filter.value) == ["alice", "shared"]


def test_build_metadata_filters_skips_source_when_none():
    from app.rag import retriever

    flt = retriever._build_metadata_filters(["alice"], None)
    keys = {f.key for f in flt.filters}
    assert "user_id" in keys
    assert "source_type" not in keys


def test_build_metadata_filters_empty_when_no_user_no_source():
    from app.rag import retriever

    flt = retriever._build_metadata_filters([], None)
    assert flt.filters == []


# ─────────────────────────────────────────────────────────────────────
# Lexical overlap & query terms
# ─────────────────────────────────────────────────────────────────────


def test_query_terms_extracts_english_and_chinese():
    from app.rag import retriever

    terms = retriever._query_terms("Redis 雪崩 击穿 cache penetration")
    # English tokens lowercased; Chinese kept as 2-char runs.
    assert "redis" in terms
    assert "cache" in terms
    assert "penetration" in terms
    assert "雪崩" in terms
    assert "击穿" in terms


def test_query_terms_dedupes():
    from app.rag import retriever

    terms = retriever._query_terms("redis redis redis")
    assert terms == ["redis"]


def test_lexical_overlap_high_for_close_query():
    from app.rag import retriever

    query = "Redis 雪崩 击穿 穿透"
    content = "Redis 缓存雪崩、缓存击穿、缓存穿透分别是什么？"
    assert retriever._lexical_overlap(query, content) >= 0.75


def test_lexical_overlap_low_for_unrelated():
    from app.rag import retriever

    assert retriever._lexical_overlap("Kafka rebalance protocol", "今天天气真好") < 0.3


def test_lexical_overlap_zero_for_empty_query():
    from app.rag import retriever

    assert retriever._lexical_overlap("", "anything") == 0.0


# ─────────────────────────────────────────────────────────────────────
# Score threshold
# ─────────────────────────────────────────────────────────────────────


def test_score_passes_meets_threshold():
    from app.rag import retriever

    assert retriever._score_passes(0.6, min_score=0.5)
    assert not retriever._score_passes(0.3, min_score=0.5)


def test_score_passes_no_relaxation_below_threshold():
    """No fallback: the same RAG_MIN_SCORE applies whether or not a reranker
    ran. A low RRF / vector score (0.03) that used to slip through the old
    ``RAG_FALLBACK_MIN_SCORE`` relaxation is now rejected — retrieval returns
    an empty result instead of admitting a low-relevance chunk."""
    from app.rag import retriever

    assert not retriever._score_passes(0.03, min_score=0.5)
    assert not retriever._score_passes(None, min_score=0.5)


# ─────────────────────────────────────────────────────────────────────
# End-to-end scope leak guard
# ─────────────────────────────────────────────────────────────────────


def _fake_node(user_id: str, source_type: str, text: str):
    """Build a fake retrieved node compatible with the metadata-scope helper."""
    return SimpleNamespace(
        node=SimpleNamespace(
            metadata={"user_id": user_id, "source_type": source_type},
            get_content=lambda: text,
        ),
        score=0.9,
    )


def test_metadata_scope_blocks_cross_user_leak():
    """The post-retrieval scope filter (same logic that ``query_knowledge_base``
    applies to ``raw_nodes``) must drop nodes belonging to another user even
    if they slip through the vector store filter."""
    from app.rag import retriever

    candidates = [
        _fake_node("alice", "interview_qa", "alice's private note"),
        _fake_node("bob",   "interview_qa", "bob's confidential file"),
        _fake_node("alice", "interview_qa", "alice's second note"),
        _fake_node("alice", "official_docs", "wrong source type"),
    ]
    survivors = [
        n for n in candidates
        if retriever._metadata_matches_scope(
            n.node.metadata, ["alice"], "interview_qa"
        )
    ]
    contents = {n.node.get_content() for n in survivors}
    assert "alice's private note" in contents
    assert "alice's second note" in contents
    # The cross-user leak and the wrong-source-type node must be gone.
    assert "bob's confidential file" not in contents
    assert "wrong source type" not in contents


@pytest.mark.slow
def test_query_knowledge_base_requires_live_milvus():
    """Marker test — the full integration is exercised in slow CI only.

    Kept here so ``pytest -m slow`` discovers it; the body is intentionally
    a noop because the unit suite cannot rely on a live Milvus / reranker.
    """
    pytest.skip("Requires live Milvus + reranker; covered in nightly CI.")
