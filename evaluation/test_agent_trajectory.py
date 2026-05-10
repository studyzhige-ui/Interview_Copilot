"""Layer 3: Agent Trajectory Evaluation.

Tests the Planner's routing accuracy and the ReAct Agent's tool selection.
Evaluates: Planner routing accuracy, tool selection F1, completion rate.

All LLM calls use DeepSeek V4.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from evaluation.conftest import EVAL_USER_A


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _plan(query: str, rewrite_context: str = "") -> dict[str, Any]:
    """Call the production planner."""
    from app.agent.planner import plan_query

    plan = await plan_query(user_message=query, rewrite_context=rewrite_context)
    return {
        "standalone_query": plan.standalone_query,
        "dense_query": plan.dense_query,
        "sparse_query": plan.sparse_query,
        "needs_memory_retrieval": plan.needs_memory_retrieval,
        "memory_types": list(plan.memory_types),
        "needs_knowledge_retrieval": plan.needs_knowledge_retrieval,
        "knowledge_sources": list(plan.knowledge_sources),
        "answer_mode": plan.answer_mode,
        "reasoning": plan.reasoning,
    }


def _compare_plan(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Compare an actual plan against expected fields.

    Returns a dict of {field: (expected, actual)} for mismatched fields.
    """
    mismatches = {}
    for field, expected_value in expected.items():
        actual_value = actual.get(field)
        if isinstance(expected_value, list):
            # For lists, check that expected is a subset of actual
            if not set(expected_value).issubset(set(actual_value or [])):
                mismatches[field] = (expected_value, actual_value)
        elif isinstance(expected_value, bool):
            if actual_value != expected_value:
                mismatches[field] = (expected_value, actual_value)
        elif isinstance(expected_value, str):
            if actual_value != expected_value:
                mismatches[field] = (expected_value, actual_value)
    return mismatches


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlannerRouting:
    """Evaluate the query planner's routing decisions."""

    def test_routing_accuracy(self, trajectory_dataset: list[dict[str, Any]]):
        """Planner routing accuracy should be ≥ 0.70."""
        correct = 0
        total = 0
        mismatches_log: list[dict[str, Any]] = []

        for row in trajectory_dataset:
            expected_plan = row.get("expected_plan")
            if not expected_plan:
                continue

            actual = asyncio.run(_plan(row["query"]))
            diffs = _compare_plan(actual, expected_plan)
            total += 1

            if not diffs:
                correct += 1
            else:
                mismatches_log.append({
                    "query": row["query"][:60],
                    "mismatches": diffs,
                })

        if total == 0:
            pytest.skip("No trajectory rows with expected_plan field.")

        accuracy = correct / total
        print(f"\n  Planner Routing Accuracy = {accuracy:.4f} ({correct}/{total})")
        if mismatches_log:
            print(f"  Sample mismatches: {mismatches_log[:3]}")
        assert accuracy >= 0.70, f"Routing accuracy = {accuracy:.4f}, expected ≥ 0.70"

    def test_knowledge_routing_for_qa_queries(self, trajectory_dataset: list[dict[str, Any]]):
        """QA-tagged queries should trigger knowledge retrieval."""
        qa_rows = [
            r for r in trajectory_dataset
            if "qa" in r.get("tags", []) or "knowledge" in r.get("tags", [])
        ]
        if not qa_rows:
            pytest.skip("No QA-tagged trajectory rows.")

        triggered = 0
        for row in qa_rows:
            plan = asyncio.run(_plan(row["query"]))
            if plan["needs_knowledge_retrieval"]:
                triggered += 1

        rate = triggered / len(qa_rows)
        print(f"\n  Knowledge Retrieval Trigger Rate (QA queries) = {rate:.4f} ({triggered}/{len(qa_rows)})")
        assert rate >= 0.80, f"Knowledge trigger rate = {rate:.4f}, expected ≥ 0.80"

    def test_direct_chat_for_casual_queries(self, trajectory_dataset: list[dict[str, Any]]):
        """Casual-tagged queries should use direct_chat mode."""
        casual_rows = [
            r for r in trajectory_dataset
            if "casual" in r.get("tags", []) or "chat" in r.get("tags", [])
        ]
        if not casual_rows:
            pytest.skip("No casual-tagged trajectory rows.")

        correct = 0
        for row in casual_rows:
            plan = asyncio.run(_plan(row["query"]))
            if plan["answer_mode"] == "direct_chat":
                correct += 1

        rate = correct / len(casual_rows)
        print(f"\n  Direct Chat Mode Rate (casual queries) = {rate:.4f} ({correct}/{len(casual_rows)})")
        assert rate >= 0.70, f"Direct chat rate = {rate:.4f}, expected ≥ 0.70"
