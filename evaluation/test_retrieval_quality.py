"""Layer 1: Retrieval Quality Evaluation.

Tests the Milvus + BM25 + Reranker pipeline in isolation — no LLM generation.
Evaluates: Hit@K, Precision@K, Recall@K, MRR, nDCG@K, latency, multi-tenant isolation.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from evaluation.conftest import EVAL_USER_A, EVAL_USER_B
from evaluation.metrics import (
    aggregate_scores,
    chunk_relevance,
    hit_at_k,
    ndcg_at_k,
    overlap_score,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _retrieve(query: str, user_id: str, source_type: str | None = None) -> dict[str, Any]:
    """Call the production retrieval function."""
    from app.rag.retriever import query_knowledge_base

    return await query_knowledge_base(
        query_str=query,
        user_id=user_id,
        source_type=source_type,
    )


def _to_relevance_flags(
    reference: str,
    chunks: list[dict[str, Any]],
    threshold: float = 0.15,
) -> list[bool]:
    """Convert retrieved chunks into relevance flags against reference text."""
    return [chunk_relevance(reference, c.get("text", ""), threshold) for c in chunks]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRetrievalQuality:
    """Aggregate retrieval quality across the golden dataset."""

    def test_hit_rate_at_3(self, retrieval_dataset: list[dict[str, Any]]):
        """Hit@3 should be ≥ 0.80."""
        hits: list[int] = []
        for row in retrieval_dataset:
            result = asyncio.run(
                _retrieve(row["query"], row.get("user_id", EVAL_USER_A), row.get("source_type"))
            )
            chunks = result.get("chunks", [])
            flags = _to_relevance_flags(row.get("reference_answer", row["query"]), chunks)
            hits.append(hit_at_k(flags, k=3))

        hit_rate = sum(hits) / len(hits)
        print(f"\n  Hit@3 = {hit_rate:.4f} ({sum(hits)}/{len(hits)})")
        assert hit_rate >= 0.80, f"Hit@3 = {hit_rate:.4f}, expected ≥ 0.80"

    def test_mrr_at_5(self, retrieval_dataset: list[dict[str, Any]]):
        """MRR@5 should be ≥ 0.60."""
        rrs: list[float] = []
        for row in retrieval_dataset:
            result = asyncio.run(
                _retrieve(row["query"], row.get("user_id", EVAL_USER_A), row.get("source_type"))
            )
            chunks = result.get("chunks", [])[:5]
            flags = _to_relevance_flags(row.get("reference_answer", row["query"]), chunks)
            rrs.append(reciprocal_rank(flags))

        mrr = sum(rrs) / len(rrs)
        print(f"\n  MRR@5 = {mrr:.4f}")
        assert mrr >= 0.60, f"MRR@5 = {mrr:.4f}, expected ≥ 0.60"

    def test_precision_at_3(self, retrieval_dataset: list[dict[str, Any]]):
        """Precision@3 should be ≥ 0.50."""
        precisions: list[float] = []
        for row in retrieval_dataset:
            result = asyncio.run(
                _retrieve(row["query"], row.get("user_id", EVAL_USER_A), row.get("source_type"))
            )
            chunks = result.get("chunks", [])
            flags = _to_relevance_flags(row.get("reference_answer", row["query"]), chunks)
            precisions.append(precision_at_k(flags, k=3))

        avg = sum(precisions) / len(precisions)
        print(f"\n  Precision@3 = {avg:.4f}")
        assert avg >= 0.50, f"Precision@3 = {avg:.4f}, expected ≥ 0.50"

    def test_retrieval_latency(self, retrieval_dataset: list[dict[str, Any]]):
        """Retrieval P95 latency should be < 2000ms."""
        latencies: list[float] = []
        for row in retrieval_dataset:
            start = time.perf_counter()
            asyncio.run(
                _retrieve(row["query"], row.get("user_id", EVAL_USER_A), row.get("source_type"))
            )
            latencies.append((time.perf_counter() - start) * 1000)

        stats = aggregate_scores(latencies)
        print(f"\n  Latency — avg={stats['mean']:.0f}ms p50={stats['p50']:.0f}ms p95={stats['p95']:.0f}ms")
        assert stats["p95"] < 2000, f"P95 latency = {stats['p95']:.0f}ms, expected < 2000ms"


class TestMultiTenantIsolation:
    """Verify that user_A's queries never return user_B's chunks."""

    def test_no_cross_tenant_leakage(self, retrieval_dataset: list[dict[str, Any]]):
        """Chunks returned for user_A must all belong to user_A (or be unscoped)."""
        violations: list[dict[str, Any]] = []
        for row in retrieval_dataset:
            user_id = row.get("user_id", EVAL_USER_A)
            result = asyncio.run(_retrieve(row["query"], user_id, row.get("source_type")))
            for chunk in result.get("chunks", []):
                chunk_user = chunk.get("metadata", {}).get("user_id")
                if chunk_user and chunk_user != user_id:
                    violations.append({
                        "query": row["query"][:60],
                        "expected_user": user_id,
                        "actual_user": chunk_user,
                        "chunk_id": chunk.get("id"),
                    })

        print(f"\n  Multi-tenant violations: {len(violations)}")
        assert len(violations) == 0, f"Found {len(violations)} cross-tenant leakage(s): {violations[:3]}"
