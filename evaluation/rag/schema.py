"""Dataset + detail/trace schema for the RAG eval subsystem (plan §3.1/§3.4).

Four versioned gold datasets (plan §5): ``retrieval_gold`` / ``planner_gold`` /
``generation_gold`` / ``bad_cases``. Each row is one JSON object per line. The
typed loaders here validate the required fields up front (a malformed dataset is
an operator error, not a silent skip) and return plain dicts the runners consume.

``empty_reason`` is NOT redefined here — it's imported from the single definition
site ``app.rag.retrieval_state.EMPTY_REASONS`` (plan §5 2026-06-10: online trace
and offline eval share one enum). ``query_type`` / ``failure_type`` /
``bad_case_status`` are eval-only vocabularies, fixed here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Single definition site for empty_reason — shared with the online retriever.
from app.rag.retrieval_state import EMPTY_REASONS  # noqa: F401 (re-exported)

QUERY_TYPES = frozenset({"single_query", "multi_query"})

# bad_cases.failure_type fixed enum (plan §3.1 Bad Cases).
FAILURE_TYPES = frozenset({
    "bad_rewrite",
    "missed_recall",
    "low_precision",
    "bad_rerank",
    "citation_error",
    "hallucination",
    "refusal_error",
    "stale_index",
    "latency_regression",
})

BAD_CASE_STATUSES = frozenset({"open", "fixed", "ignored"})

# Required keys on EVERY runner detail row (plan §3.2).
DETAIL_REQUIRED_FIELDS = ("sample_id", "query_type", "status", "trace_id", "latency_ms")


class DatasetError(ValueError):
    """A gold dataset row is missing required fields / has an invalid value.
    Raised eagerly at load time — a bad dataset must fail loudly, not skip rows."""


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read a ``.jsonl`` file into a list of dicts. Blank lines are skipped;
    a malformed line raises :class:`DatasetError` naming the 1-based line no."""
    rows: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        raise DatasetError(f"dataset not found: {p}")
    with p.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{p}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise DatasetError(f"{p}:{lineno}: expected a JSON object")
            rows.append(obj)
    return rows


def _require(row: dict, keys: Iterable[str], ctx: str) -> None:
    missing = [k for k in keys if k not in row or row[k] in (None, "")]
    if missing:
        raise DatasetError(f"{ctx} (id={row.get('id')!r}): missing fields {missing}")


def _check_query_type(row: dict, ctx: str) -> None:
    qt = row.get("query_type")
    if qt not in QUERY_TYPES:
        raise DatasetError(f"{ctx} (id={row.get('id')!r}): query_type={qt!r} not in {sorted(QUERY_TYPES)}")


@dataclass(frozen=True)
class RetrievalGold:
    """One retrieval-eval sample (plan §3.1 Retrieval Gold)."""
    id: str
    query: str
    user_id: str
    query_type: str
    expected_chunk_ids: list[str]
    expected_content: str
    min_content_coverage: float = 0.75
    expected_node_ids: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, row: dict, *, ctx: str = "retrieval_gold") -> "RetrievalGold":
        _require(row, ("id", "query", "user_id", "query_type", "expected_chunk_ids",
                       "expected_content"), ctx)
        _check_query_type(row, ctx)
        if not row.get("expected_chunk_ids"):
            raise DatasetError(f"{ctx} (id={row.get('id')!r}): expected_chunk_ids needs >=1 id")
        return cls(
            id=row["id"], query=row["query"], user_id=row["user_id"],
            query_type=row["query_type"], expected_chunk_ids=list(row["expected_chunk_ids"]),
            expected_content=row["expected_content"],
            min_content_coverage=float(row.get("min_content_coverage", 0.75)),
            expected_node_ids=list(row.get("expected_node_ids") or []),
            notes=row.get("notes", ""),
        )


@dataclass(frozen=True)
class PlannerGold:
    """One planner-eval sample (plan §3.1 Planner Gold)."""
    id: str
    user_message: str
    recent_turns: list[dict]
    query_type: str
    expected_needs_retrieval: bool
    expected_dense_contains: list[str]
    expected_sparse_terms: list[str]
    expected_sub_query_count: int

    @classmethod
    def from_dict(cls, row: dict, *, ctx: str = "planner_gold") -> "PlannerGold":
        _require(row, ("id", "user_message", "query_type"), ctx)
        _check_query_type(row, ctx)
        if "expected_needs_retrieval" not in row:
            raise DatasetError(f"{ctx} (id={row.get('id')!r}): expected_needs_retrieval required")
        return cls(
            id=row["id"], user_message=row["user_message"],
            recent_turns=list(row.get("recent_turns") or []),
            query_type=row["query_type"],
            expected_needs_retrieval=bool(row["expected_needs_retrieval"]),
            expected_dense_contains=list(row.get("expected_dense_contains") or []),
            expected_sparse_terms=list(row.get("expected_sparse_terms") or []),
            expected_sub_query_count=int(row.get("expected_sub_query_count", 0)),
        )


@dataclass(frozen=True)
class GenerationGold:
    """One end-to-end generation-eval sample (plan §3.1 Generation Gold)."""
    id: str
    query: str
    query_type: str
    expected_chunk_ids: list[str]
    expected_content: str
    reference_answer_points: list[str]
    expected_citation_required: bool
    expected_refusal: bool
    min_content_coverage: float = 0.75
    expected_node_ids: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, row: dict, *, ctx: str = "generation_gold") -> "GenerationGold":
        _require(row, ("id", "query", "query_type", "expected_chunk_ids",
                       "expected_content", "reference_answer_points"), ctx)
        _check_query_type(row, ctx)
        # End-to-end gold must name >=1 chunk to expect recalled + cited (symmetric
        # with RetrievalGold — _require's truthiness check lets [] through).
        if not row.get("expected_chunk_ids"):
            raise DatasetError(f"{ctx} (id={row.get('id')!r}): expected_chunk_ids needs >=1 id")
        return cls(
            id=row["id"], query=row["query"], query_type=row["query_type"],
            expected_chunk_ids=list(row["expected_chunk_ids"]),
            expected_content=row["expected_content"],
            reference_answer_points=list(row["reference_answer_points"]),
            expected_citation_required=bool(row.get("expected_citation_required", False)),
            expected_refusal=bool(row.get("expected_refusal", False)),
            min_content_coverage=float(row.get("min_content_coverage", 0.75)),
            expected_node_ids=list(row.get("expected_node_ids") or []),
            notes=row.get("notes", ""),
        )


@dataclass(frozen=True)
class BadCase:
    """One regression bad case (plan §3.1 Bad Cases)."""
    id: str
    query: str
    query_type: str
    failure_type: str
    expected_behavior: str
    status: str = "open"
    actual_trace_id: str = ""
    actual_behavior: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, row: dict, *, ctx: str = "bad_cases") -> "BadCase":
        _require(row, ("id", "query", "query_type", "failure_type", "expected_behavior",
                       "status"), ctx)
        _check_query_type(row, ctx)
        if row["failure_type"] not in FAILURE_TYPES:
            raise DatasetError(f"{ctx} (id={row['id']!r}): failure_type={row['failure_type']!r} invalid")
        if row["status"] not in BAD_CASE_STATUSES:
            raise DatasetError(f"{ctx} (id={row['id']!r}): status={row['status']!r} invalid")
        return cls(
            id=row["id"], query=row["query"], query_type=row["query_type"],
            failure_type=row["failure_type"], expected_behavior=row["expected_behavior"],
            status=row["status"], actual_trace_id=row.get("actual_trace_id", ""),
            actual_behavior=row.get("actual_behavior", ""), notes=row.get("notes", ""),
        )


_LOADERS = {
    "retrieval": RetrievalGold,
    "planner": PlannerGold,
    "generation": GenerationGold,
    "bad_cases": BadCase,
}


def load_dataset(kind: str, path: str | Path) -> list:
    """Load + validate a typed gold dataset. ``kind`` ∈ retrieval/planner/
    generation/bad_cases. Raises :class:`DatasetError` on the first bad row."""
    if kind not in _LOADERS:
        raise DatasetError(f"unknown dataset kind {kind!r}; expected one of {sorted(_LOADERS)}")
    model = _LOADERS[kind]
    return [model.from_dict(row) for row in load_jsonl(path)]


def base_detail(*, sample_id: str, query_type: str, status: str, trace_id: str,
                latency_ms: float, **extra: Any) -> dict[str, Any]:
    """Build a runner detail row carrying the §3.2 required fields plus ``extra``.
    Every runner's detail JSONL row must start from this so cross-runner trace
    correlation + grouping work uniformly. Keyed off DETAIL_REQUIRED_FIELDS so the
    contract has a single source of truth (no drift between the constant and here)."""
    values = {
        "sample_id": sample_id, "query_type": query_type, "status": status,
        "trace_id": trace_id, "latency_ms": latency_ms,
    }
    row = {field_name: values[field_name] for field_name in DETAIL_REQUIRED_FIELDS}
    row.update(extra)
    return row


__all__ = [
    "QUERY_TYPES", "FAILURE_TYPES", "BAD_CASE_STATUSES", "EMPTY_REASONS",
    "DETAIL_REQUIRED_FIELDS", "DatasetError",
    "RetrievalGold", "PlannerGold", "GenerationGold", "BadCase",
    "load_jsonl", "load_dataset", "base_detail",
]
