"""Single source of truth for retrieval release thresholds."""

from __future__ import annotations

from typing import Any, Literal

MIN_CANDIDATE_GOLD_HIT_RATE = 0.98
MIN_CANDIDATE_SOURCE_HIT_RATE = 0.99
MIN_CANDIDATE_EVIDENCE_GROUP_RECALL = 0.98
MIN_CALIBRATED_RERANK_SCORE = 0.80
MIN_RERANKED_HIT_AT_1 = 0.80
MIN_RERANKED_HIT_AT_3 = 0.95
MIN_PASSAGE_HIT_AT_3 = 0.92
MIN_SOURCE_HIT_AT_3 = 0.95
MIN_PASSAGE_MRR_AT_3 = 0.85
MIN_PASSAGE_NDCG_AT_3 = 0.87
MIN_MACRO_CONTEXT_EVIDENCE_PRECISION = 0.65
MIN_DEPLOYED_EVIDENCE_PRECISION = 0.55
MIN_EVIDENCE_GROUP_RECALL_AT_3 = 0.90
MIN_DOCUMENT_RECALL_AT_3 = 0.95
MIN_DEPLOYED_QUERY_PRECISION = 0.95
MIN_DEPLOYED_QUERY_RECALL = 0.90
MIN_RERANKER_AUROC = 0.85
MAX_P95_LATENCY_MS = 1500
MAX_UNANSWERABLE_FALSE_POSITIVE_RATE = 0.05
MIN_FORMAT_RERANKED_HIT_AT_3 = 0.85
MIN_FORMAT_RECALL = 0.75
MIN_FORMAT_EVIDENCE_PRECISION = 0.45
MIN_LANGUAGE_RERANKED_HIT_AT_3 = 0.90
MIN_LANGUAGE_RECALL = 0.85


def retrieval_release_gates(
    metrics: dict[str, Any],
    *,
    threshold_mode: Literal["calibrated", "deployed"],
) -> dict[str, bool]:
    calibration = metrics.get("threshold_calibration") or {}
    if threshold_mode == "calibrated":
        threshold = calibration.get("calibration_metrics") or {}
        by_format = calibration.get("calibration_by_source_format") or {}
        by_language = calibration.get("calibration_by_language") or {}
    else:
        threshold = metrics.get("deployed_threshold_metrics") or {}
        by_format = metrics.get("deployed_threshold_by_source_format") or {}
        by_language = metrics.get("deployed_threshold_by_language") or {}
    ranking = threshold if threshold_mode == "calibrated" else metrics
    raw_formats = metrics.get("reranked_passage_hit_at_3_by_source_format") or {}
    raw_languages = metrics.get("reranked_passage_hit_at_3_by_language") or {}
    score_separation = metrics.get("reranker_score_separation") or {}
    latency = metrics.get("latency_ms") or {}
    return {
        "candidate_gold_hit_rate": float(
            metrics.get("candidate_gold_chunk_hit_rate_at_budget") or 0.0
        )
        >= MIN_CANDIDATE_GOLD_HIT_RATE,
        "candidate_source_hit_rate": float(
            metrics.get("candidate_source_hit_rate_at_budget") or 0.0
        )
        >= MIN_CANDIDATE_SOURCE_HIT_RATE,
        "candidate_evidence_group_recall": float(
            metrics.get("candidate_evidence_group_recall_at_budget") or 0.0
        )
        >= MIN_CANDIDATE_EVIDENCE_GROUP_RECALL,
        "reranked_hit_at_1": float(metrics.get("reranked_passage_hit_at_1") or 0.0)
        >= MIN_RERANKED_HIT_AT_1,
        "reranked_hit_at_3": float(metrics.get("reranked_passage_hit_at_3") or 0.0)
        >= MIN_RERANKED_HIT_AT_3,
        "passage_hit_at_3": float(ranking.get("passage_hit_at_3") or 0.0)
        >= MIN_PASSAGE_HIT_AT_3,
        "source_hit_at_3": float(ranking.get("source_hit_at_3") or 0.0)
        >= MIN_SOURCE_HIT_AT_3,
        "passage_mrr_at_3": float(ranking.get("passage_mrr_at_3") or 0.0)
        >= MIN_PASSAGE_MRR_AT_3,
        "passage_ndcg_at_3": float(ranking.get("passage_ndcg_at_3") or 0.0)
        >= MIN_PASSAGE_NDCG_AT_3,
        "macro_context_evidence_precision": float(
            ranking.get("macro_context_evidence_precision") or 0.0
        )
        >= MIN_MACRO_CONTEXT_EVIDENCE_PRECISION,
        "evidence_group_recall_at_3": float(
            ranking.get("evidence_group_recall_at_3") or 0.0
        )
        >= MIN_EVIDENCE_GROUP_RECALL_AT_3,
        "document_recall_at_3": float(ranking.get("document_recall_at_3") or 0.0)
        >= MIN_DOCUMENT_RECALL_AT_3,
        "query_precision": float(threshold.get("precision") or 0.0)
        >= MIN_DEPLOYED_QUERY_PRECISION,
        "query_recall": float(threshold.get("recall") or 0.0)
        >= MIN_DEPLOYED_QUERY_RECALL,
        "evidence_precision": float(threshold.get("evidence_precision") or 0.0)
        >= MIN_DEPLOYED_EVIDENCE_PRECISION,
        "negative_false_positive_rate": float(
            threshold.get("negative_false_positive_rate") or 0.0
        )
        <= MAX_UNANSWERABLE_FALSE_POSITIVE_RATE,
        "reranker_auroc": float(score_separation.get("auroc") or 0.0)
        >= MIN_RERANKER_AUROC,
        "latency_p95": float(latency.get("p95") or float("inf")) < MAX_P95_LATENCY_MS,
        "format_hit_at_3": bool(raw_formats)
        and min(float(value) for value in raw_formats.values())
        >= MIN_FORMAT_RERANKED_HIT_AT_3,
        "format_recall": bool(by_format)
        and min(float(value.get("recall") or 0.0) for value in by_format.values())
        >= MIN_FORMAT_RECALL,
        "format_evidence_precision": bool(by_format)
        and min(
            float(value.get("evidence_precision") or 0.0)
            for value in by_format.values()
        )
        >= MIN_FORMAT_EVIDENCE_PRECISION,
        "language_hit_at_3": bool(raw_languages)
        and min(float(value) for value in raw_languages.values())
        >= MIN_LANGUAGE_RERANKED_HIT_AT_3,
        "language_recall": bool(by_language)
        and min(float(value.get("recall") or 0.0) for value in by_language.values())
        >= MIN_LANGUAGE_RECALL,
    }


__all__ = [
    "MAX_P95_LATENCY_MS",
    "MAX_UNANSWERABLE_FALSE_POSITIVE_RATE",
    "MIN_CANDIDATE_GOLD_HIT_RATE",
    "MIN_CANDIDATE_EVIDENCE_GROUP_RECALL",
    "MIN_CANDIDATE_SOURCE_HIT_RATE",
    "MIN_CALIBRATED_RERANK_SCORE",
    "MIN_DEPLOYED_EVIDENCE_PRECISION",
    "MIN_DEPLOYED_QUERY_PRECISION",
    "MIN_DOCUMENT_RECALL_AT_3",
    "MIN_EVIDENCE_GROUP_RECALL_AT_3",
    "MIN_FORMAT_EVIDENCE_PRECISION",
    "MIN_FORMAT_RECALL",
    "MIN_FORMAT_RERANKED_HIT_AT_3",
    "MIN_LANGUAGE_RECALL",
    "MIN_LANGUAGE_RERANKED_HIT_AT_3",
    "MIN_MACRO_CONTEXT_EVIDENCE_PRECISION",
    "MIN_PASSAGE_HIT_AT_3",
    "MIN_PASSAGE_MRR_AT_3",
    "MIN_PASSAGE_NDCG_AT_3",
    "MIN_RERANKED_HIT_AT_1",
    "MIN_RERANKED_HIT_AT_3",
    "MIN_RERANKER_AUROC",
    "MIN_SOURCE_HIT_AT_3",
    "retrieval_release_gates",
]
