"""Central RAG budgets and retrieval policy.

No ingestion or retrieval module reads the related settings directly. This
keeps parameter ablations reproducible and prevents format-specific constants.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class TokenBudget:
    chunk_target: int
    chunk_overlap: int
    rerank_input: int
    query_reserve: int

    @property
    def passage_limit(self) -> int:
        return self.rerank_input - self.query_reserve


@dataclass(frozen=True)
class RetrievalPolicy:
    candidate_count: int
    final_count: int
    max_intents: int
    min_score: float
    score_margin: float | None
    dense_weight: float
    sparse_weight: float
    rrf_k: int
    search_timeout_seconds: float
    rerank_timeout_seconds: float


@dataclass(frozen=True)
class RagPolicy:
    device: str
    tokens: TokenBudget
    retrieval: RetrievalPolicy


def current_rag_policy() -> RagPolicy:
    return RagPolicy(
        device=settings.RAG_DEVICE,
        tokens=TokenBudget(
            chunk_target=settings.RAG_CHUNK_TOKENS,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,
            rerank_input=settings.RAG_RERANK_INPUT_TOKENS,
            query_reserve=settings.RAG_QUERY_TOKEN_RESERVE,
        ),
        retrieval=RetrievalPolicy(
            candidate_count=settings.RAG_CANDIDATE_COUNT,
            final_count=settings.RAG_FINAL_COUNT,
            max_intents=settings.RAG_MAX_INTENTS,
            min_score=settings.RAG_MIN_SCORE,
            score_margin=settings.RAG_SCORE_MARGIN,
            dense_weight=settings.RAG_DENSE_WEIGHT,
            sparse_weight=settings.RAG_SPARSE_WEIGHT,
            rrf_k=settings.RAG_RRF_K,
            search_timeout_seconds=settings.RAG_SEARCH_TIMEOUT_SECONDS,
            rerank_timeout_seconds=settings.RAG_RERANK_TIMEOUT_SECONDS,
        ),
    )


def resolve_rag_device() -> str:
    configured = current_rag_policy().device
    if configured != "auto":
        return configured
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


__all__ = [
    "RagPolicy",
    "RetrievalPolicy",
    "TokenBudget",
    "current_rag_policy",
    "resolve_rag_device",
]
