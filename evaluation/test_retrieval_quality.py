"""Layer 1 — retrieval quality thresholds.

Asserts the production retriever (Milvus + BM25 + BGE reranker) meets
quality bars on the bundled golden dataset. No LLM cost.

Reads ``retrieval_metrics`` from the session fixture, which means every
assertion below runs against the SAME single traversal of the dataset.
"""
from __future__ import annotations

from typing import Any

import pytest


# Thresholds — tune against your production deployment's empirical
# numbers, not theoretical bests. A failure here means quality
# regressed, NOT that the system is broken.
MIN_HIT_AT_3 = 0.80
MIN_MRR_AT_5 = 0.60
MIN_PRECISION_AT_3 = 0.50
MAX_P95_LATENCY_MS = 2000


def test_hit_at_3(retrieval_metrics: dict[str, Any]) -> None:
    value = retrieval_metrics["hit_at_3"]
    print(f"\n  Hit@3 = {value:.4f}")
    assert value >= MIN_HIT_AT_3, f"Hit@3 = {value:.4f}, expected ≥ {MIN_HIT_AT_3}"


def test_mrr_at_5(retrieval_metrics: dict[str, Any]) -> None:
    value = retrieval_metrics["mrr_at_5"]
    print(f"\n  MRR@5 = {value:.4f}")
    assert value >= MIN_MRR_AT_5, f"MRR@5 = {value:.4f}, expected ≥ {MIN_MRR_AT_5}"


def test_precision_at_3(retrieval_metrics: dict[str, Any]) -> None:
    value = retrieval_metrics["precision_at_3"]
    print(f"\n  Precision@3 = {value:.4f}")
    assert value >= MIN_PRECISION_AT_3, (
        f"Precision@3 = {value:.4f}, expected ≥ {MIN_PRECISION_AT_3}"
    )


def test_latency_p95(retrieval_metrics: dict[str, Any]) -> None:
    stats = retrieval_metrics["latency_ms"]
    print(
        f"\n  Latency — mean={stats['mean']:.0f}ms "
        f"p50={stats['p50']:.0f}ms p95={stats['p95']:.0f}ms"
    )
    assert stats["p95"] < MAX_P95_LATENCY_MS, (
        f"P95 latency = {stats['p95']:.0f}ms, expected < {MAX_P95_LATENCY_MS}ms"
    )


def test_no_cross_tenant_leakage(retrieval_metrics: dict[str, Any]) -> None:
    """A chunk returned for user_A must never carry user_B's metadata."""
    violations = retrieval_metrics["isolation_violations"]
    print(f"\n  Multi-tenant violations: {violations}")
    assert violations == 0, (
        f"Found {violations} cross-tenant leakage(s) — see runner logs"
    )
