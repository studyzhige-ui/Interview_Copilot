"""Layer 2 — end-to-end RAG generation quality (RAGAS v0.4.3).

Asserts the full retrieve → evaluator answer → RAGAS scoring chain on
the configured evaluation dataset. Each row triggers one answer call and
several RAGAS judge calls.

Reads ``generation_metrics`` from a session fixture so the whole
dataset is traversed exactly once regardless of how many assertions
this file declares.
"""

from __future__ import annotations

from typing import Any

import pytest

# Quality bars. Calibrate them against the selected evaluator and corpus;
# raise them as your retrieval improves, lower them if a vendor swap
# legitimately moves the floor.
MIN_FAITHFULNESS = 0.70
MIN_ANSWER_RELEVANCY = 0.70
MIN_CONTEXT_PRECISION = 0.60
MIN_CONTEXT_RECALL = 0.60
MIN_ANSWER_CORRECTNESS = 0.50
MAX_RETRIEVAL_MISS_RATE = 0.15
MAX_EMPTY_ANSWER_RATE = 0.01
MIN_REFUSAL_ACCURACY = 0.90
MIN_CITATION_VALIDITY = 0.95
MIN_CITATION_COVERAGE = 0.90
MIN_RAGAS_VALID_SAMPLE_RATE = 1.00
MIN_LIVE_LATENCY_SAMPLES = 40


def test_formal_release_contract(
    evaluation_report: dict[str, Any],
    generation_metrics: dict[str, Any],
) -> None:
    run = evaluation_report["run"]
    assert run["ragas_profile"] == "formal"
    assert run["ragas_sample_size"] == 50
    assert generation_metrics["ragas_judged_samples"] == 50
    assert generation_metrics["ragas_completed_samples"] == 50
    assert generation_metrics["ragas_error_count"] == 0
    assert generation_metrics["judge_relationship"] == "independent_model"
    assert generation_metrics["answerable_samples"] == 50
    assert generation_metrics["unanswerable_samples"] == 30
    assert generation_metrics["tenant_isolation_probe"]["passed"] is True
    assert generation_metrics["reused_check_answer"] is True
    assert generation_metrics["reused_check_metric_count"] == 5
    assert generation_metrics["planner_results_sha256"]
    assert generation_metrics["index_provenance"]["fingerprint"]


def _required(metrics: dict[str, Any], key: str) -> float:
    """Pull a metric and fail when an attempted judge run lost coverage."""
    value = metrics.get(key)
    judged = int(metrics.get("ragas_judged_samples") or 0)
    if value is None:
        if not judged:
            pytest.skip("RAGAS judging was explicitly disabled.")
        pytest.fail(f"{key!r} was not scored for any of {judged} judge samples.")
    valid_samples = metrics.get("ragas_metric_valid_samples") or {}
    valid = int(valid_samples.get(key) or 0)
    if key in valid_samples and judged and valid / judged < MIN_RAGAS_VALID_SAMPLE_RATE:
        pytest.fail(f"{key!r} has only {valid}/{judged} valid judge samples.")
    return float(value)


def test_faithfulness(generation_metrics: dict[str, Any]) -> None:
    value = _required(generation_metrics, "faithfulness")
    print(f"\n  Faithfulness = {value:.4f}")
    assert value >= MIN_FAITHFULNESS, (
        f"Faithfulness = {value:.4f}, expected ≥ {MIN_FAITHFULNESS}"
    )


def test_answer_relevancy(generation_metrics: dict[str, Any]) -> None:
    value = _required(generation_metrics, "answer_relevancy")
    assert value >= MIN_ANSWER_RELEVANCY


def test_context_precision(generation_metrics: dict[str, Any]) -> None:
    value = _required(generation_metrics, "context_precision_with_reference")
    print(f"\n  Context Precision = {value:.4f}")
    assert value >= MIN_CONTEXT_PRECISION, (
        f"Context Precision = {value:.4f}, expected ≥ {MIN_CONTEXT_PRECISION}"
    )


def test_context_recall(generation_metrics: dict[str, Any]) -> None:
    value = _required(generation_metrics, "context_recall")
    print(f"\n  Context Recall = {value:.4f}")
    assert value >= MIN_CONTEXT_RECALL, (
        f"Context Recall = {value:.4f}, expected ≥ {MIN_CONTEXT_RECALL}"
    )


def test_answer_correctness(generation_metrics: dict[str, Any]) -> None:
    value = _required(generation_metrics, "answer_correctness")
    assert value >= MIN_ANSWER_CORRECTNESS


def test_answerable_retrieval_miss_rate(generation_metrics: dict[str, Any]) -> None:
    rate = generation_metrics["answerable_retrieval_miss_rate"]
    print(f"\n  Retrieval Miss Rate = {rate:.4f}")
    assert rate <= MAX_RETRIEVAL_MISS_RATE, (
        f"Retrieval miss rate = {rate:.4f}, expected ≤ {MAX_RETRIEVAL_MISS_RATE}"
    )


def test_empty_answer_rate(generation_metrics: dict[str, Any]) -> None:
    rate = generation_metrics["empty_answer_rate"]
    print(f"\n  Empty Answer Rate = {rate:.4f}")
    assert rate <= MAX_EMPTY_ANSWER_RATE, (
        f"Empty answer rate = {rate:.4f}, expected ≤ {MAX_EMPTY_ANSWER_RATE}"
    )


def test_unanswerable_refusal_accuracy(generation_metrics: dict[str, Any]) -> None:
    if not generation_metrics.get("unanswerable_samples"):
        pytest.skip("The selected generation sample has no unanswerable rows.")
    rate = _required(generation_metrics, "unanswerable_refusal_accuracy")
    assert rate >= MIN_REFUSAL_ACCURACY


def test_citation_coverage(generation_metrics: dict[str, Any]) -> None:
    rate = _required(generation_metrics, "citation_coverage")
    assert rate >= MIN_CITATION_COVERAGE


def test_citation_validity(generation_metrics: dict[str, Any]) -> None:
    rate = _required(generation_metrics, "citation_validity")
    assert rate >= MIN_CITATION_VALIDITY


def test_stream_latency_metrics_are_measured(
    generation_metrics: dict[str, Any],
) -> None:
    assert (
        generation_metrics["live_generation_measurement_samples"]
        >= MIN_LIVE_LATENCY_SAMPLES
    )
    assert generation_metrics["model_ttft_ms"]["p50"] > 0
    assert generation_metrics["tpot_ms"]["p50"] > 0
    assert generation_metrics["output_throughput_tokens_per_second"]["p50"] > 0
