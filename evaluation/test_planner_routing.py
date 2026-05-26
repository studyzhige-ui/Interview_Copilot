"""Layer 3 — planner routing quality.

Asserts ``app.conversation.query_planner.plan_query`` makes the right
RAG / memory-load decisions on the bundled golden dataset.

Post-planner-merge, the ``QueryPlan`` shape is:

  needs_knowledge_retrieval : bool
  dense_query               : str  # only meaningful when needs_kr=True
  sparse_query              : str  # only meaningful when needs_kr=True
  knowledge_topics          : list[str]
  load_strategy             : bool
  load_habit                : bool

The pre-P8 ``answer_mode`` / ``knowledge_sources`` / ``standalone_query``
fields are gone, so we don't try to assert on them. The golden dataset
also doesn't carry per-row ``expected_plan`` rows (and never did under
the new shape), so the meaningful signal is aggregate behaviour.

Every dataset row is tagged ``["knowledge", "qa"]`` — these are
unambiguously interview-knowledge questions, so a healthy planner
should turn RAG on for ≥ 80% of them.
"""
from __future__ import annotations

from typing import Any

import pytest


MIN_KNOWLEDGE_TRIGGER_RATE = 0.80
MIN_DENSE_QUERY_POPULATED_RATE = 0.95
MAX_PLAN_CALL_FAILURE_RATE = 0.02


def test_knowledge_retrieval_trigger_rate(
    trajectory_metrics: dict[str, Any],
) -> None:
    """QA-tagged queries should turn RAG on."""
    rate = trajectory_metrics.get("knowledge_retrieval_trigger_rate")
    if rate is None:
        pytest.skip("No succeeded plan_query calls.")
    print(
        f"\n  Knowledge trigger rate = {rate:.4f} "
        f"({trajectory_metrics['knowledge_triggered']}/{trajectory_metrics['succeeded']})"
    )
    assert rate >= MIN_KNOWLEDGE_TRIGGER_RATE, (
        f"Knowledge trigger rate = {rate:.4f}, "
        f"expected ≥ {MIN_KNOWLEDGE_TRIGGER_RATE}"
    )


def test_dense_query_populated_rate(
    trajectory_metrics: dict[str, Any],
) -> None:
    """When RAG is on, dense_query should be non-empty.

    An empty dense_query short-circuits retrieval upstream — even a
    correct ``needs_knowledge_retrieval=True`` decision is useless if
    no query string makes it through to Milvus.
    """
    rate = trajectory_metrics.get("dense_query_populated_rate")
    if rate is None:
        pytest.skip("No succeeded plan_query calls.")
    print(f"\n  Dense-query populated rate = {rate:.4f}")
    assert rate >= MIN_DENSE_QUERY_POPULATED_RATE, (
        f"Dense-query populated rate = {rate:.4f}, "
        f"expected ≥ {MIN_DENSE_QUERY_POPULATED_RATE}"
    )


def test_plan_call_failure_rate(trajectory_metrics: dict[str, Any]) -> None:
    """plan_query should rarely raise.

    A 2% failure budget tolerates the occasional vendor timeout
    without forcing a quality-gate red. Beyond that, the planner
    prompt or the LLM client is degraded — block.
    """
    samples = trajectory_metrics["samples"]
    failures = trajectory_metrics["plan_call_failures"]
    rate = failures / samples if samples else 0.0
    print(f"\n  plan_query failure rate = {rate:.4f} ({failures}/{samples})")
    assert rate <= MAX_PLAN_CALL_FAILURE_RATE, (
        f"plan_query failure rate = {rate:.4f}, "
        f"expected ≤ {MAX_PLAN_CALL_FAILURE_RATE}"
    )
