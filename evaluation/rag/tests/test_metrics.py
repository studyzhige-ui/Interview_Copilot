"""Unit tests for the pure RAG-eval metric functions (plan §3.3).

Run from the repo root: ``python -m pytest evaluation/rag/tests/ -q``. These are
NOT collected by the backend ``pytest.ini`` (eval is a separate domain).
"""
from __future__ import annotations

import math

from evaluation.rag import metrics as m


# ── content_coverage ──────────────────────────────────────────────────────────

def test_content_coverage_full_and_none():
    assert m.content_coverage("缓存雪崩", "缓存雪崩的解决方案") == 1.0  # all 3-grams present
    assert m.content_coverage("缓存雪崩", "完全无关的内容XYZ") < 0.5
    assert m.content_coverage("", "anything") == 0.0  # empty expectation
    assert m.content_coverage("abc", "") == 0.0       # empty actual


def test_content_coverage_partial_monotonic():
    full = m.content_coverage("redis cache avalanche", "redis cache avalanche mitigation")
    partial = m.content_coverage("redis cache avalanche", "redis only")
    assert full == 1.0
    assert 0.0 < partial < 1.0


def test_content_coverage_normalizes_case_and_whitespace():
    assert m.content_coverage("Redis  Cache", "redis cache") == 1.0


# ── relevance_scores ───────────────────────────────────────────────────────────

def _ranked(*pairs):
    return [{"chunk_id": cid, "text": txt} for cid, txt in pairs]

def test_relevance_scores_strong_hit_and_coverage():
    ranked = _ranked(("c1", "irrelevant"), ("c2", "缓存雪崩 解决"), ("c3", "缓存雪崩"))
    scores = m.relevance_scores(ranked, ["c1"], "缓存雪崩", min_content_coverage=0.75)
    assert scores[0] == (True, 1.0)            # strong hit by chunk_id
    assert scores[1][0] is False and scores[1][1] >= 0.75  # coverage hit
    assert scores[2][0] is False and scores[2][1] == 1.0   # full coverage, not strong


def test_relevance_scores_below_min_coverage_is_zero():
    ranked = _ranked(("x", "完全无关 abcdef"))
    scores = m.relevance_scores(ranked, ["c1"], "缓存雪崩限流降级", min_content_coverage=0.75)
    assert scores[0] == (False, 0.0)


# ── ranking metrics ─────────────────────────────────────────────────────────────

def test_hit_recall_precision_at_k():
    scores = [(True, 1.0), (False, 0.0), (False, 0.9)]  # relevant at rank 1 and 3
    assert m.hit_at_k(scores, 1) is True
    assert m.hit_at_k([(False, 0.0)], 1) is False
    assert m.recall_at_k(scores, 3, gold_count=2) == 1.0    # 2 relevant / 2 gold
    assert m.recall_at_k(scores, 1, gold_count=2) == 0.5
    assert m.recall_at_k(scores, 3, gold_count=0) == 0.0
    assert m.precision_at_k(scores, 2) == 0.5               # 1 relevant of top-2
    assert m.precision_at_k(scores, 0) == 0.0


def test_mrr_at_k():
    assert m.mrr_at_k([(False, 0.0), (True, 1.0)], 5) == 0.5  # first hit at rank 2
    assert m.mrr_at_k([(True, 1.0)], 5) == 1.0
    assert m.mrr_at_k([(False, 0.0)], 5) == 0.0


def test_ndcg_at_k_perfect_and_imperfect():
    perfect = [(True, 1.0), (True, 1.0)]
    assert m.ndcg_at_k(perfect, 2) == 1.0
    # A relevant item demoted below an irrelevant one → ndcg < 1.
    demoted = [(False, 0.0), (True, 1.0)]
    nd = m.ndcg_at_k(demoted, 2)
    assert 0.0 < nd < 1.0
    assert m.ndcg_at_k([(False, 0.0)], 2) == 0.0  # no gain


def test_gold_chunk_best_rank_strong_only():
    # Only a STRONG (chunk_id) hit counts — a coverage hit at rank 1 doesn't.
    scores = [(False, 1.0), (True, 1.0)]
    assert m.gold_chunk_best_rank(scores) == 2
    assert m.gold_chunk_best_rank([(False, 0.9)]) is None


def test_rerank_survival_rate():
    rin = [(True, 1.0), (False, 0.0), (True, 1.0)]   # 2 relevant in
    rout = [(True, 1.0), (False, 0.0)]                # 1 relevant out
    assert m.rerank_survival_rate(rin, rout) == 0.5
    assert m.rerank_survival_rate([(False, 0.0)], []) is None  # no relevant in


# ── planner / generation ────────────────────────────────────────────────────────

def test_contains_all_terms():
    assert m.contains_all_terms("Redis 缓存雪崩 缓存击穿", ["Redis", "缓存雪崩"]) is True
    assert m.contains_all_terms("Redis 缓存雪崩", ["Redis", "缓存击穿"]) is False
    assert m.contains_all_terms("anything", []) is True  # nothing required


def test_answer_completeness():
    answer = "可以用过期时间随机化，配合限流降级和多级缓存。"
    points = ["过期时间随机化", "限流降级", "多级缓存"]
    assert m.answer_completeness(answer, points) == 1.0
    assert m.answer_completeness(answer, ["过期时间随机化", "完全没提到的要点XYZ"]) == 0.5
    assert m.answer_completeness("", points) == 0.0
    assert m.answer_completeness(answer, []) == 0.0


# ── aggregation helpers ──────────────────────────────────────────────────────────

def test_mean_rate_none_on_empty():
    assert m.mean([1.0, 2.0, 3.0]) == 2.0
    assert m.mean([]) is None
    assert m.rate([True, False, True, False]) == 0.5
    assert m.rate([]) is None


def test_percentile():
    assert m.percentile([10], 95) == 10.0
    assert m.percentile([], 50) is None
    assert m.percentile([1, 2, 3, 4], 50) == 2.5   # interpolated median
    p95 = m.percentile(list(range(1, 101)), 95)
    assert math.isclose(p95, 95.05, rel_tol=1e-6)
