"""Layer 2 — end-to-end RAG generation quality (RAGAS v0.4.3).

Asserts the full retrieve → DeepSeek answer → RAGAS scoring chain on
the bundled golden dataset. LLM-heavy: each run hits DeepSeek twice
per row (once for the answer, once per RAGAS metric × 4 = 4 more).

Reads ``generation_metrics`` from a session fixture so the whole
dataset is traversed exactly once regardless of how many assertions
this file declares.
"""
from __future__ import annotations

from typing import Any

import pytest


# Quality bars. Calibrated against a healthy DeepSeek-V4 deployment;
# raise them as your retrieval improves, lower them if a vendor swap
# legitimately moves the floor.
MIN_FAITHFULNESS = 0.70
MIN_CONTEXT_PRECISION = 0.60
MIN_CONTEXT_RECALL = 0.60
MIN_FACTUAL_CORRECTNESS = 0.50
MAX_HALLUCINATION_GATE_RATE = 0.30
MAX_EMPTY_ANSWER_RATE = 0.10


def _required(metrics: dict[str, Any], key: str) -> float:
    """Pull a metric, skipping the test if RAGAS couldn't score it."""
    value = metrics.get(key)
    if value is None:
        pytest.skip(f"{key!r} not scored — RAGAS returned no values.")
    return float(value)


def test_faithfulness(generation_metrics: dict[str, Any]) -> None:
    value = _required(generation_metrics, "faithfulness")
    print(f"\n  Faithfulness = {value:.4f}")
    assert value >= MIN_FAITHFULNESS, (
        f"Faithfulness = {value:.4f}, expected ≥ {MIN_FAITHFULNESS}"
    )


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


def test_factual_correctness(generation_metrics: dict[str, Any]) -> None:
    value = _required(generation_metrics, "factual_correctness")
    print(f"\n  Factual Correctness = {value:.4f}")
    assert value >= MIN_FACTUAL_CORRECTNESS, (
        f"Factual Correctness = {value:.4f}, expected ≥ {MIN_FACTUAL_CORRECTNESS}"
    )


def test_hallucination_gate_rate(generation_metrics: dict[str, Any]) -> None:
    """How often retrieval came back empty.

    When the retriever finds nothing useful, the engine's hallucination
    gate kicks in and refuses to answer. A high rate here means either
    the corpus doesn't cover the dataset or retrieval is missing real
    hits — investigate L1 first before touching the gate threshold.
    """
    rate = generation_metrics["hallucination_gate_rate"]
    print(f"\n  Hallucination Gate Rate = {rate:.4f}")
    assert rate <= MAX_HALLUCINATION_GATE_RATE, (
        f"Hallucination gate rate = {rate:.4f}, "
        f"expected ≤ {MAX_HALLUCINATION_GATE_RATE}"
    )


def test_empty_answer_rate(generation_metrics: dict[str, Any]) -> None:
    rate = generation_metrics["empty_answer_rate"]
    print(f"\n  Empty Answer Rate = {rate:.4f}")
    assert rate <= MAX_EMPTY_ANSWER_RATE, (
        f"Empty answer rate = {rate:.4f}, "
        f"expected ≤ {MAX_EMPTY_ANSWER_RATE}"
    )
