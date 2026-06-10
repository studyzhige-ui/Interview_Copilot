"""Structured retrieval-state contract for the RAG read path.

Single home for the retrieval-state shape and its fixed enums
(``empty_reason``, ``score_source``) — the retriever produces it, the engine
forwards it, telemetry/trace and the evaluation runners consume it. Defined
ONCE here so online metrics and offline eval reports share identical values
(docs/zh/rag-evaluation-optimization-plan.md §2.4); do not redeclare these
strings elsewhere.

This replaces the old ``[SYSTEM_EMPTY_WARNING]`` sentinel-string protocol:
emptiness is now an explicit ``retrieval_hit=False`` + ``empty_reason`` pair
instead of a magic substring inside a context string.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── empty_reason 固定枚举（线上 trace 与离线评测共用，唯一定义处）──────────
EMPTY_PLANNER_NO_RETRIEVAL = "planner_no_retrieval"
EMPTY_NO_CANDIDATES = "no_candidates"
EMPTY_ALL_BELOW_THRESHOLD = "all_below_threshold"
EMPTY_ALL_FILTERED_LIVE_CHECK = "all_filtered_live_check"
EMPTY_MILVUS_UNAVAILABLE = "milvus_unavailable"
EMPTY_PRINCIPAL_UNRESOLVED = "principal_unresolved"

EMPTY_REASONS = frozenset({
    EMPTY_PLANNER_NO_RETRIEVAL,
    EMPTY_NO_CANDIDATES,
    EMPTY_ALL_BELOW_THRESHOLD,
    EMPTY_ALL_FILTERED_LIVE_CHECK,
    EMPTY_MILVUS_UNAVAILABLE,
    EMPTY_PRINCIPAL_UNRESOLVED,
})

# ── score_source 固定枚举（sources/trace 中只允许这两个值）─────────────────
SCORE_SOURCE_RERANKER = "reranker"
SCORE_SOURCE_RETRIEVER_FALLBACK = "retriever_fallback"


@dataclass
class RetrievalState:
    """Per-retrieval outcome flags — the light state travelling next to the
    chunks (retriever → engine → SSE/trace)."""

    retrieval_hit: bool = False
    empty_reason: str | None = None
    # Set by the engine/facade from the QueryPlan — the retriever itself
    # doesn't know whether the planner LLM failed.
    planner_failed: bool = False
    # Remote reranker transport failure → unranked RRF top-N with
    # score_source=retriever_fallback. Never mixed with reranker scores.
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "retrieval_hit": self.retrieval_hit,
            "empty_reason": self.empty_reason,
            "planner_failed": self.planner_failed,
            "fallback_used": self.fallback_used,
        }


@dataclass
class RetrievalResult:
    """One retrieval pass: hydrated top-N chunks + structured state.

    ``chunks`` are fully attributed dicts hydrated from Postgres facts (see
    ``app.services.knowledge.chunk_hydration``), in final rank order. The
    ``[K#]`` numbering and the final sources array are NOT assigned here —
    context assembly owns those, on the post-budget-trim chunk list
    (retrieval plan §2.7).
    """

    chunks: list[dict[str, Any]] = field(default_factory=list)
    state: RetrievalState = field(default_factory=RetrievalState)

    @property
    def retrieval_hit(self) -> bool:
        return self.state.retrieval_hit


__all__ = [
    "EMPTY_PLANNER_NO_RETRIEVAL",
    "EMPTY_NO_CANDIDATES",
    "EMPTY_ALL_BELOW_THRESHOLD",
    "EMPTY_ALL_FILTERED_LIVE_CHECK",
    "EMPTY_MILVUS_UNAVAILABLE",
    "EMPTY_PRINCIPAL_UNRESOLVED",
    "EMPTY_REASONS",
    "SCORE_SOURCE_RERANKER",
    "SCORE_SOURCE_RETRIEVER_FALLBACK",
    "RetrievalState",
    "RetrievalResult",
]
