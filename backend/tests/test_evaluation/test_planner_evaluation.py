from __future__ import annotations

import asyncio
import hashlib

import pytest

from app.conversation.query_planner import QueryPlan
from app.rag.contracts import SearchIntent
from evaluation.planner_snapshot import (
    load_or_create_planner_snapshot,
    planner_results_sha256,
)
from evaluation.runners import run_trajectory


@pytest.mark.asyncio
async def test_trajectory_planner_uses_bounded_concurrency(monkeypatch) -> None:
    active = 0
    peak = 0

    async def fake_plan_query(**kwargs) -> QueryPlan:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return QueryPlan(
            needs_knowledge_retrieval=True,
            intents=[SearchIntent(query=kwargs["user_message"])],
        )

    monkeypatch.setattr(
        "app.conversation.query_planner.plan_query",
        fake_plan_query,
    )
    rows = [
        {
            "id": f"sample-{index}",
            "query": f"question {index}",
            "expected_intent_count": 1,
        }
        for index in range(8)
    ]

    result = await run_trajectory(rows, concurrency=4)

    assert peak == 4
    assert result["planner_concurrency"] == 4
    assert result["routing_accuracy"] == 1.0
    assert [item["id"] for item in result["per_sample_details"]] == [
        row["id"] for row in rows
    ]


@pytest.mark.asyncio
async def test_trajectory_planner_rejects_invalid_concurrency() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await run_trajectory([{"query": "question"}], concurrency=0)


@pytest.mark.asyncio
async def test_planner_snapshot_is_reused(monkeypatch, tmp_path) -> None:
    calls = 0

    async def fake_plan_rows(rows, **kwargs):
        nonlocal calls
        from evaluation.runners import PlannerEvaluationResult

        calls += 1
        return [
            PlannerEvaluationResult(
                plan=QueryPlan(
                    needs_knowledge_retrieval=True,
                    intents=[SearchIntent.from_query(row["query"])],
                ),
                error=None,
                latency_ms=12.5,
            )
            for row in rows
        ]

    monkeypatch.setattr(
        "evaluation.planner_snapshot.plan_evaluation_rows",
        fake_plan_rows,
    )
    rows = [{"id": "one", "query": "What is asyncio?"}]
    path = tmp_path / "planner.json"

    first = await load_or_create_planner_snapshot(rows, path=path)
    first_file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    second = await load_or_create_planner_snapshot(rows, path=path)

    assert calls == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == first_file_hash
    assert first[0].plan == second[0].plan
    assert first[0].latency_ms == second[0].latency_ms == 12.5
    assert planner_results_sha256(rows, first) == planner_results_sha256(rows, second)


@pytest.mark.asyncio
async def test_planner_snapshot_adds_only_missing_rows(monkeypatch, tmp_path) -> None:
    planned_ids: list[list[str]] = []

    async def fake_plan_rows(rows, **kwargs):
        from evaluation.runners import PlannerEvaluationResult

        planned_ids.append([row["id"] for row in rows])
        return [
            PlannerEvaluationResult(
                plan=QueryPlan(
                    needs_knowledge_retrieval=True,
                    intents=[SearchIntent.from_query(row["query"])],
                ),
                error=None,
                latency_ms=10.0,
            )
            for row in rows
        ]

    monkeypatch.setattr(
        "evaluation.planner_snapshot.plan_evaluation_rows",
        fake_plan_rows,
    )
    first_row = {"id": "one", "query": "question one"}
    second_row = {"id": "two", "query": "question two"}
    path = tmp_path / "planner.json"

    await load_or_create_planner_snapshot([first_row], path=path)
    results = await load_or_create_planner_snapshot([first_row, second_row], path=path)

    assert planned_ids == [["one"], ["two"]]
    assert [result.plan.intents[0].query for result in results] == [
        "question one",
        "question two",
    ]


@pytest.mark.asyncio
async def test_planner_snapshot_rejects_fallback_plan(monkeypatch, tmp_path) -> None:
    async def fake_plan_rows(rows, **kwargs):
        from evaluation.runners import PlannerEvaluationResult

        return [
            PlannerEvaluationResult(
                plan=QueryPlan(
                    needs_knowledge_retrieval=True,
                    intents=[SearchIntent.from_query(row["query"])],
                    planner_failed=True,
                ),
                error=None,
                latency_ms=10.0,
            )
            for row in rows
        ]

    monkeypatch.setattr(
        "evaluation.planner_snapshot.plan_evaluation_rows",
        fake_plan_rows,
    )
    path = tmp_path / "planner.json"

    with pytest.raises(RuntimeError, match="fallback/failed"):
        await load_or_create_planner_snapshot(
            [{"id": "one", "query": "question one"}],
            path=path,
        )

    assert not path.exists()


@pytest.mark.asyncio
async def test_planner_snapshot_persists_success_before_retry(
    monkeypatch, tmp_path
) -> None:
    planned_ids: list[list[str]] = []

    async def fake_plan_rows(rows, **kwargs):
        from evaluation.runners import PlannerEvaluationResult

        planned_ids.append([row["id"] for row in rows])
        return [
            PlannerEvaluationResult(
                plan=QueryPlan(
                    needs_knowledge_retrieval=True,
                    intents=[SearchIntent.from_query(row["query"])],
                    planner_failed=row["id"] == "retry" and len(planned_ids) == 1,
                ),
                error=None,
                latency_ms=10.0,
            )
            for row in rows
        ]

    monkeypatch.setattr(
        "evaluation.planner_snapshot.plan_evaluation_rows",
        fake_plan_rows,
    )
    rows = [
        {"id": "success", "query": "question one"},
        {"id": "retry", "query": "question two"},
    ]
    path = tmp_path / "planner.json"

    with pytest.raises(RuntimeError, match="retry"):
        await load_or_create_planner_snapshot(rows, path=path, concurrency=2)
    results = await load_or_create_planner_snapshot(rows, path=path, concurrency=2)

    assert planned_ids == [["success", "retry"], ["retry"]]
    assert len(results) == 2


@pytest.mark.asyncio
async def test_planner_snapshot_stops_on_unknown_paid_state(
    monkeypatch, tmp_path
) -> None:
    calls = 0

    async def fake_plan_rows(rows, **kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(
        "evaluation.planner_snapshot.plan_evaluation_rows",
        fake_plan_rows,
    )
    path = tmp_path / "planner.json"
    path.with_suffix(".json.inflight.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unknown payment state"):
        await load_or_create_planner_snapshot(
            [{"id": "one", "query": "question"}],
            path=path,
        )

    assert calls == 0
