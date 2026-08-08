"""Layer 1 — retrieval quality thresholds.

Asserts the production hybrid retriever meets quality bars on the
configured evaluation dataset. No LLM cost.

Reads ``retrieval_metrics`` from the session fixture, which means every
assertion below runs against the SAME single traversal of the dataset.
"""

from __future__ import annotations

from typing import Any

from evaluation.retrieval_gates import (
    MAX_P95_LATENCY_MS,
    MAX_UNANSWERABLE_FALSE_POSITIVE_RATE,
    MIN_CANDIDATE_GOLD_HIT_RATE,
    MIN_CANDIDATE_EVIDENCE_GROUP_RECALL,
    MIN_CANDIDATE_SOURCE_HIT_RATE,
    MIN_DEPLOYED_EVIDENCE_PRECISION,
    MIN_DEPLOYED_QUERY_PRECISION,
    MIN_DOCUMENT_RECALL_AT_3,
    MIN_EVIDENCE_GROUP_RECALL_AT_3,
    MIN_MACRO_CONTEXT_EVIDENCE_PRECISION,
    MIN_PASSAGE_HIT_AT_3,
    MIN_PASSAGE_MRR_AT_3,
    MIN_RERANKED_HIT_AT_1,
    MIN_RERANKED_HIT_AT_3,
    MIN_RERANKER_AUROC,
    MIN_SOURCE_HIT_AT_3,
    retrieval_release_gates,
)


def test_retrieval_release_contract(
    evaluation_report: dict[str, Any],
    retrieval_metrics: dict[str, Any],
) -> None:
    run = evaluation_report["run"]
    assert run["retrieval_query_mode"] == "planned"
    assert run["rag_device"] == "cuda"
    assert run["index_provenance"]["fingerprint"]
    assert retrieval_metrics["planner_fallbacks"] == 0
    assert retrieval_metrics["planner_results_sha256"]
    gates = retrieval_release_gates(retrieval_metrics, threshold_mode="deployed")
    assert all(gates.values()), {
        key: passed for key, passed in gates.items() if not passed
    }


def test_candidate_stage_recall(retrieval_metrics: dict[str, Any]) -> None:
    assert (
        retrieval_metrics["candidate_gold_chunk_hit_rate_at_budget"]
        >= MIN_CANDIDATE_GOLD_HIT_RATE
    )
    assert (
        retrieval_metrics["candidate_source_hit_rate_at_budget"]
        >= MIN_CANDIDATE_SOURCE_HIT_RATE
    )
    assert (
        retrieval_metrics["candidate_evidence_group_recall_at_budget"]
        >= MIN_CANDIDATE_EVIDENCE_GROUP_RECALL
    )


def test_threshold_free_reranker_quality(retrieval_metrics: dict[str, Any]) -> None:
    assert retrieval_metrics["reranked_passage_hit_at_1"] >= MIN_RERANKED_HIT_AT_1
    assert retrieval_metrics["reranked_passage_hit_at_3"] >= MIN_RERANKED_HIT_AT_3


def test_passage_hit_at_3(retrieval_metrics: dict[str, Any]) -> None:
    value = retrieval_metrics["passage_hit_at_3"]
    print(f"\n  Passage Hit@3 = {value:.4f}")
    assert value >= MIN_PASSAGE_HIT_AT_3, (
        f"Passage Hit@3 = {value:.4f}, expected ≥ {MIN_PASSAGE_HIT_AT_3}"
    )


def test_source_hit_at_3(retrieval_metrics: dict[str, Any]) -> None:
    value = retrieval_metrics["source_hit_at_3"]
    print(f"\n  Source Hit@3 = {value:.4f}")
    assert value >= MIN_SOURCE_HIT_AT_3, (
        f"Source Hit@3 = {value:.4f}, expected ≥ {MIN_SOURCE_HIT_AT_3}"
    )


def test_mrr_at_3(retrieval_metrics: dict[str, Any]) -> None:
    value = retrieval_metrics["passage_mrr_at_3"]
    print(f"\n  Passage MRR@3 = {value:.4f}")
    assert value >= MIN_PASSAGE_MRR_AT_3, (
        f"Passage MRR@3 = {value:.4f}, expected ≥ {MIN_PASSAGE_MRR_AT_3}"
    )


def test_precision_at_3(retrieval_metrics: dict[str, Any]) -> None:
    value = retrieval_metrics["passage_precision_at_3"]
    print(f"\n  Passage Precision@3 = {value:.4f}")
    assert 0.0 <= value <= 1.0


def test_actual_context_purity(retrieval_metrics: dict[str, Any]) -> None:
    assert (
        retrieval_metrics["macro_context_evidence_precision"]
        >= MIN_MACRO_CONTEXT_EVIDENCE_PRECISION
    )


def test_document_recall_at_3(retrieval_metrics: dict[str, Any]) -> None:
    value = retrieval_metrics["document_recall_at_3"]
    assert value >= MIN_DOCUMENT_RECALL_AT_3


def test_evidence_group_recall_at_3(retrieval_metrics: dict[str, Any]) -> None:
    value = retrieval_metrics["evidence_group_recall_at_3"]
    assert value >= MIN_EVIDENCE_GROUP_RECALL_AT_3


def test_deployed_threshold_precision(retrieval_metrics: dict[str, Any]) -> None:
    metrics = retrieval_metrics["deployed_threshold_metrics"]
    assert metrics["precision"] >= MIN_DEPLOYED_QUERY_PRECISION
    assert metrics["evidence_precision"] >= MIN_DEPLOYED_EVIDENCE_PRECISION


def test_reranker_score_separation(retrieval_metrics: dict[str, Any]) -> None:
    metrics = retrieval_metrics["reranker_score_separation"]
    assert metrics["auroc"] >= MIN_RERANKER_AUROC


def test_unanswerable_false_positive_rate(retrieval_metrics: dict[str, Any]) -> None:
    value = retrieval_metrics["unanswerable_retrieval_false_positive_rate"]
    assert value <= MAX_UNANSWERABLE_FALSE_POSITIVE_RATE


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
    probe = retrieval_metrics.get("tenant_isolation_probe") or {}
    assert probe.get("passed") is True
    assert probe.get("owner_hit") is True
    assert probe.get("foreign_leak") is False
