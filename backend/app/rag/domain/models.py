"""Domain models shared by ingestion, retrieval, grounding, and generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator


# Retrieval outcome values are part of the online/offline telemetry contract.
EMPTY_PLANNER_NO_RETRIEVAL = "planner_no_retrieval"
EMPTY_NO_CANDIDATES = "no_candidates"
EMPTY_ALL_BELOW_THRESHOLD = "all_below_threshold"
EMPTY_ALL_FILTERED_LIVE_CHECK = "all_filtered_live_check"
EMPTY_MILVUS_UNAVAILABLE = "milvus_unavailable"
EMPTY_RERANKER_UNAVAILABLE = "reranker_unavailable"
EMPTY_PRINCIPAL_UNRESOLVED = "principal_unresolved"

EMPTY_REASONS = frozenset(
    {
        EMPTY_PLANNER_NO_RETRIEVAL,
        EMPTY_NO_CANDIDATES,
        EMPTY_ALL_BELOW_THRESHOLD,
        EMPTY_ALL_FILTERED_LIVE_CHECK,
        EMPTY_MILVUS_UNAVAILABLE,
        EMPTY_RERANKER_UNAVAILABLE,
        EMPTY_PRINCIPAL_UNRESOLVED,
    }
)

SCORE_SOURCE_RERANKER = "reranker"


class SearchIntent(BaseModel):
    """One independently answerable information need.

    ``intent_id`` is assigned deterministically when omitted.  It travels with
    candidates through grounding so a multi-intent query can prove coverage
    instead of merely returning a globally relevant top-k list.
    """

    intent_id: str = ""
    query: str
    alternate_query: str = ""
    keywords: list[str] = Field(default_factory=list)
    required_terms: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)

    @field_validator("intent_id", "query", "alternate_query", mode="before")
    @classmethod
    def _clean_query(cls, value: object) -> str:
        return " ".join(str(value or "").split())

    @field_validator("keywords", "required_terms", "document_ids", mode="before")
    @classmethod
    def _clean_terms(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(
            dict.fromkeys(
                " ".join(str(term).split()) for term in value if str(term or "").strip()
            )
        )

    @property
    def dense_queries(self) -> tuple[str, ...]:
        values = [self.query, self.alternate_query]
        return tuple(dict.fromkeys(value for value in values if value))

    @property
    def sparse_query(self) -> str:
        return " ".join(self.keywords) or self.query

    @classmethod
    def from_query(cls, query: str) -> "SearchIntent":
        return cls(query=query, keywords=[query])


@dataclass
class RetrievalState:
    retrieval_hit: bool = False
    empty_reason: str | None = None
    planner_failed: bool = False
    fallback_used: bool = False

    # ``degraded`` is the precise domain term. ``fallback_used`` stays in the
    # wire contract until clients migrate, but both names refer to one value.
    @property
    def degraded(self) -> bool:
        return self.fallback_used

    @degraded.setter
    def degraded(self, value: bool) -> None:
        self.fallback_used = bool(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "retrieval_hit": self.retrieval_hit,
            "empty_reason": self.empty_reason,
            "planner_failed": self.planner_failed,
            "fallback_used": self.fallback_used,
        }


@dataclass
class RetrievalResult:
    """Ranked facts plus the provenance needed by the grounding stage."""

    chunks: list[dict[str, Any]] = field(default_factory=list)
    state: RetrievalState = field(default_factory=RetrievalState)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    intents: list[SearchIntent] = field(default_factory=list)

    @property
    def retrieval_hit(self) -> bool:
        return self.state.retrieval_hit


@dataclass
class CitationReport:
    cited_refs: list[str] = field(default_factory=list)
    valid_refs: list[str] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)
    missing_citation: bool = False

    @property
    def ok(self) -> bool:
        return not self.invalid_refs and not self.missing_citation


@dataclass
class GroundingBundle:
    """The exact evidence delivered to the answer model.

    Evidence checks and citations must use ``included_chunks`` only.  This
    prevents a qualifier in a budget-trimmed chunk from authorising an answer.
    """

    context_text: str = ""
    included_chunks: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    covered_intent_ids: list[str] = field(default_factory=list)
    missing_intent_ids: list[str] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)
    supported: bool = True
    token_count: int = 0


__all__ = [
    "CitationReport",
    "EMPTY_ALL_BELOW_THRESHOLD",
    "EMPTY_ALL_FILTERED_LIVE_CHECK",
    "EMPTY_MILVUS_UNAVAILABLE",
    "EMPTY_NO_CANDIDATES",
    "EMPTY_PLANNER_NO_RETRIEVAL",
    "EMPTY_PRINCIPAL_UNRESOLVED",
    "EMPTY_REASONS",
    "EMPTY_RERANKER_UNAVAILABLE",
    "GroundingBundle",
    "RetrievalResult",
    "RetrievalState",
    "SCORE_SOURCE_RERANKER",
    "SearchIntent",
]
