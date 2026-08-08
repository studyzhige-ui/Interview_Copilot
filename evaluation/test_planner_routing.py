"""Layer 3 — planner routing quality.

Asserts ``app.conversation.query_planner.plan_query`` makes the right
RAG / memory-load decisions on the bundled evaluation dataset.

Knowledge rows, including corpus-unanswerable questions, should retrieve;
planner-only greeting, transformation and arithmetic rows should not.
Multi-hop rows additionally verify sub-query decomposition.
"""

from __future__ import annotations

from typing import Any

import pytest

MIN_ROUTING_ACCURACY = 0.90
MIN_RETRIEVAL_RECALL = 0.95
MIN_NO_RETRIEVAL_SPECIFICITY = 0.75
MIN_INTENT_POPULATED_RATE = 0.95
MIN_MULTI_INTENT_PLANNING_RATE = 0.66
MIN_INTENT_COUNT_ACCURACY = 0.90
MAX_SINGLE_INTENT_OVERDECOMPOSITION_RATE = 0.10
MAX_PLAN_CALL_FAILURE_RATE = 0.02


def test_routing_accuracy(
    trajectory_metrics: dict[str, Any],
) -> None:
    """Answerable and deliberately unanswerable queries should both route."""
    rate = trajectory_metrics.get("routing_accuracy")
    if rate is None:
        pytest.skip("No succeeded plan_query calls.")
    print(f"\n  Routing accuracy = {rate:.4f}")
    assert rate >= MIN_ROUTING_ACCURACY, (
        f"Routing accuracy = {rate:.4f}, expected ≥ {MIN_ROUTING_ACCURACY}"
    )


def test_retrieval_recall(trajectory_metrics: dict[str, Any]) -> None:
    rate = trajectory_metrics.get("retrieval_recall")
    if rate is None:
        pytest.skip("No answerable planner rows.")
    assert rate >= MIN_RETRIEVAL_RECALL


def test_no_retrieval_specificity(trajectory_metrics: dict[str, Any]) -> None:
    rate = trajectory_metrics.get("no_retrieval_specificity")
    if rate is None:
        pytest.skip("No negative planner rows.")
    assert rate >= MIN_NO_RETRIEVAL_SPECIFICITY


def test_intent_populated_rate(
    trajectory_metrics: dict[str, Any],
) -> None:
    rate = trajectory_metrics.get("intent_populated_rate")
    if rate is None:
        pytest.skip("No succeeded plan_query calls.")
    print(f"\n  Intent populated rate = {rate:.4f}")
    assert rate >= MIN_INTENT_POPULATED_RATE, (
        f"Intent populated rate = {rate:.4f}, expected ≥ {MIN_INTENT_POPULATED_RATE}"
    )


def test_plan_call_failure_rate(trajectory_metrics: dict[str, Any]) -> None:
    """plan_query should rarely raise.

    A 2% failure budget tolerates the occasional vendor timeout
    without forcing a quality-gate red. Beyond that, the planner
    prompt or the LLM client is degraded — block.
    """
    reliability = trajectory_metrics["planner_reliability"]
    samples = reliability["rows"]
    failures = reliability["first_attempt_failures"]
    rate = failures / samples if samples else 0.0
    print(f"\n  plan_query failure rate = {rate:.4f} ({failures}/{samples})")
    assert rate <= MAX_PLAN_CALL_FAILURE_RATE, (
        f"plan_query failure rate = {rate:.4f}, expected ≤ {MAX_PLAN_CALL_FAILURE_RATE}"
    )


def test_multi_intent_planning_rate(trajectory_metrics: dict[str, Any]) -> None:
    rate = trajectory_metrics.get("multi_intent_planning_rate")
    if rate is None:
        pytest.skip("No multi-intent planner rows.")
    assert rate >= MIN_MULTI_INTENT_PLANNING_RATE


def test_intent_count_accuracy(trajectory_metrics: dict[str, Any]) -> None:
    rate = trajectory_metrics.get("intent_count_accuracy")
    if rate is None:
        pytest.skip("No succeeded planner rows.")
    assert rate >= MIN_INTENT_COUNT_ACCURACY


def test_single_intent_overdecomposition_rate(
    trajectory_metrics: dict[str, Any],
) -> None:
    rate = trajectory_metrics.get("single_intent_overdecomposition_rate")
    if rate is None:
        pytest.skip("No single-intent retrieval rows.")
    assert rate <= MAX_SINGLE_INTENT_OVERDECOMPOSITION_RATE
