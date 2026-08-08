"""Versioned planner snapshots for reproducible retrieval evaluations."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.conversation.query_planner import (
    QueryPlan,
    _extract_json_payload,
    _format_recent_turns,
    _keyword_terms,
    _validated_required_terms,
    fallback_query_plan,
    plan_query,
)
from app.core.internal_models import get_internal_model_profile
from app.core.llm_client_factory import LLM_TEMPERATURE
from app.prompts.chat import build_query_planner_system_prompt
from app.core.config import settings
from app.rag.policy import current_rag_policy

from evaluation.runners import (
    DEFAULT_PLANNER_CONCURRENCY,
    PlannerEvaluationResult,
    plan_evaluation_rows,
)

SCHEMA_VERSION = 3
DEFAULT_RETRIEVAL_SNAPSHOT = (
    Path(settings.APP_DATA_DIR) / "evaluation" / "planner" / "retrieval.json"
)
DEFAULT_GLOBAL_MEMORY_SNAPSHOT = (
    Path(settings.APP_DATA_DIR) / "evaluation" / "planner" / "global-memory-on.json"
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _planner_contract_sha256(*, global_memory_on: bool) -> str:
    policy = current_rag_policy().retrieval
    profile = get_internal_model_profile("router")
    contract = {
        "query_plan_schema": QueryPlan.model_json_schema(),
        "planner_source": "".join(
            inspect.getsource(value)
            for value in (
                plan_query,
                fallback_query_plan,
                _extract_json_payload,
                _format_recent_turns,
                _keyword_terms,
                _validated_required_terms,
                build_query_planner_system_prompt,
            )
        ),
        "rendered_system_prompt": build_query_planner_system_prompt(
            global_memory_on=global_memory_on,
            max_intents=policy.max_intents,
        ),
        "request": {
            "api_base": profile.api_base,
            "model": profile.model,
            "temperature": LLM_TEMPERATURE,
            "timeout_seconds": settings.LLM_REQUEST_TIMEOUT_SECONDS,
            "max_retries": 0,
            "max_output_tokens": profile.max_output_tokens,
            "context_window": profile.context_window,
            "response_format": {"type": "json_object"},
            "request_overrides": (
                {"extra_body": {"thinking": {"type": "disabled"}}}
                if profile.provider == "deepseek"
                else {}
            ),
        },
        "max_intents": policy.max_intents,
    }
    return _sha256_text(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, default=str)
    )


def _snapshot_identity(
    *,
    global_memory_on: bool,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "global_memory_on": global_memory_on,
        "planner_contract_sha256": _planner_contract_sha256(
            global_memory_on=global_memory_on
        ),
        "planner_model": f"{settings.INTERNAL_LLM_PROVIDER}/{settings.INTERNAL_LLM_MODEL}",
    }


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("id") or ""),
        _sha256_text(str(row["query"])),
    )


def planner_results_sha256(
    rows: list[dict[str, Any]],
    results: list[PlannerEvaluationResult],
) -> str:
    """Hash the ordered planner outputs, excluding timing and cache metadata."""
    if len(rows) != len(results):
        raise ValueError("planner rows and results must have the same length")
    serialized = []
    for row, result in zip(rows, results):
        if (
            result.error is not None
            or result.plan is None
            or result.plan.planner_failed
        ):
            raise ValueError("planner result is not suitable for a frozen evaluation")
        row_id, query_sha = _row_key(row)
        serialized.append(
            {
                "id": row_id,
                "query_sha256": query_sha,
                "plan": result.plan.model_dump(mode="json"),
            }
        )
    return _sha256_text(json.dumps(serialized, ensure_ascii=False, sort_keys=True))


def _load_matching_snapshot(
    path: Path,
    *,
    global_memory_on: bool,
) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = _snapshot_identity(global_memory_on=global_memory_on)
    if any(payload.get(key) != value for key, value in expected.items()):
        return {}
    serialized = payload.get("plans")
    if not isinstance(serialized, list):
        return {}
    return {(str(item["id"]), str(item["query_sha256"])): item for item in serialized}


def _persist_snapshot(
    path: Path,
    cached: dict[tuple[str, str], dict[str, Any]],
    *,
    global_memory_on: bool,
) -> None:
    payload = {
        **_snapshot_identity(global_memory_on=global_memory_on),
        "updated_at": datetime.now(UTC).isoformat(),
        "cached_sample_count": len(cached),
        "plans": [cached[key] for key in sorted(cached)],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    _write_json_fsync(temporary, payload)
    temporary.replace(path)


def _write_json_fsync(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def _append_attempts(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def planner_attempt_metrics(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    global_memory_on: bool,
) -> dict[str, Any]:
    """Report actual first-attempt reliability, including rejected fallbacks."""
    attempts_path = path.with_suffix(path.suffix + ".attempts.jsonl")
    identity = _snapshot_identity(global_memory_on=global_memory_on)
    wanted = {_row_key(row) for row in rows}
    attempts: list[dict[str, Any]] = []
    if attempts_path.is_file():
        for line in attempts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            key = (str(record.get("id")), str(record.get("query_sha256")))
            if record.get("snapshot_identity") == identity and key in wanted:
                attempts.append(record)
    by_row: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in attempts:
        by_row.setdefault((str(record["id"]), str(record["query_sha256"])), []).append(
            record
        )
    missing = wanted - set(by_row)
    if missing:
        raise RuntimeError("Planner attempt ledger is incomplete for this evaluation")
    first = [by_row[key][0] for key in wanted]
    latencies = [float(record["latency_ms"]) for record in attempts]
    ordered = sorted(latencies)
    p95_index = max(0, int(round((len(ordered) - 1) * 0.95)))
    return {
        "rows": len(wanted),
        "attempts": len(attempts),
        "first_attempt_failures": sum(
            bool(record.get("error_type")) for record in first
        ),
        "first_attempt_fallbacks": sum(
            bool(record.get("planner_failed")) for record in first
        ),
        "retried_rows": sum(len(by_row[key]) > 1 for key in wanted),
        "attempt_latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 4),
            "p95": round(ordered[p95_index], 4),
        },
    }


async def _load_or_create_planner_snapshot(
    rows: list[dict[str, Any]],
    *,
    path: Path = DEFAULT_RETRIEVAL_SNAPSHOT,
    concurrency: int = DEFAULT_PLANNER_CONCURRENCY,
    global_memory_on: bool = False,
    retry_unknown_paid_calls: bool = False,
) -> list[PlannerEvaluationResult]:
    """Reuse matching rows and plan only missing rows, preserving input order."""
    cached = _load_matching_snapshot(
        path,
        global_memory_on=global_memory_on,
    )
    missing_rows = [row for row in rows if _row_key(row) not in cached]
    in_flight = path.with_suffix(path.suffix + ".inflight.json")
    if in_flight.is_file() and not retry_unknown_paid_calls:
        raise RuntimeError(
            "Planner snapshot has requests with unknown payment state; pass "
            "--retry-unknown-paid-calls only after checking provider usage"
        )
    in_flight.unlink(missing_ok=True)
    failures: list[tuple[str, BaseException | None]] = []
    attempts_path = path.with_suffix(path.suffix + ".attempts.jsonl")
    snapshot_identity = _snapshot_identity(global_memory_on=global_memory_on)
    for offset in range(0, len(missing_rows), concurrency):
        batch = missing_rows[offset : offset + concurrency]
        _write_json_fsync(
            in_flight,
            {
                "rows": [
                    {"id": row_id, "query_sha256": query_sha}
                    for row_id, query_sha in map(_row_key, batch)
                ]
            },
        )
        generated = await plan_evaluation_rows(
            batch,
            concurrency=concurrency,
            global_memory_on=global_memory_on,
        )
        _append_attempts(
            attempts_path,
            [
                {
                    "snapshot_identity": snapshot_identity,
                    "id": _row_key(row)[0],
                    "query_sha256": _row_key(row)[1],
                    "attempted_at": datetime.now(UTC).isoformat(),
                    "latency_ms": round(result.latency_ms, 4),
                    "planner_failed": bool(
                        result.plan is not None and result.plan.planner_failed
                    ),
                    "error_type": type(result.error).__name__
                    if result.error is not None
                    else None,
                }
                for row, result in zip(batch, generated)
            ],
        )
        batch_added = False
        for row, result in zip(batch, generated):
            if (
                result.error is not None
                or result.plan is None
                or result.plan.planner_failed
            ):
                failures.append((str(row.get("id") or ""), result.error))
                continue
            row_id, query_sha = _row_key(row)
            cached[(row_id, query_sha)] = {
                "id": row_id,
                "query_sha256": query_sha,
                "latency_ms": round(result.latency_ms, 4),
                "generated_at": datetime.now(UTC).isoformat(),
                "planner_concurrency": concurrency,
                "plan": result.plan.model_dump(mode="json"),
            }
            batch_added = True
        if batch_added:
            _persist_snapshot(
                path,
                cached,
                global_memory_on=global_memory_on,
            )
        in_flight.unlink(missing_ok=True)

    if failures:
        failed_ids = ", ".join(row_id for row_id, _error in failures)
        cause = next((error for _row_id, error in failures if error is not None), None)
        raise RuntimeError(
            "Planner snapshot kept successful rows but rejected fallback/failed "
            f"rows: {failed_ids}"
        ) from cause

    results = [
        PlannerEvaluationResult(
            plan=QueryPlan.model_validate(cached[_row_key(row)]["plan"]),
            error=None,
            latency_ms=float(cached[_row_key(row)]["latency_ms"]),
        )
        for row in rows
    ]

    return results


async def load_or_create_planner_snapshot(
    rows: list[dict[str, Any]],
    *,
    path: Path = DEFAULT_RETRIEVAL_SNAPSHOT,
    concurrency: int = DEFAULT_PLANNER_CONCURRENCY,
    global_memory_on: bool = False,
    retry_unknown_paid_calls: bool = False,
) -> list[PlannerEvaluationResult]:
    """Create or extend one snapshot without concurrent paid planner calls."""
    from filelock import FileLock, Timeout

    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path.with_suffix(path.suffix + ".lock")))
    try:
        with lock.acquire(timeout=0):
            return await _load_or_create_planner_snapshot(
                rows,
                path=path,
                concurrency=concurrency,
                global_memory_on=global_memory_on,
                retry_unknown_paid_calls=retry_unknown_paid_calls,
            )
    except Timeout as exc:
        raise RuntimeError(
            f"Planner snapshot is already being updated by another process: {path}"
        ) from exc


__all__ = [
    "DEFAULT_GLOBAL_MEMORY_SNAPSHOT",
    "DEFAULT_RETRIEVAL_SNAPSHOT",
    "load_or_create_planner_snapshot",
    "planner_attempt_metrics",
    "planner_results_sha256",
]
