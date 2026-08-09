"""Stable domain contracts for the complete RAG lifecycle.

The package is deliberately dependency-light.  Infrastructure adapters
(Milvus, SQLAlchemy, model clients) consume these contracts but never define
their own competing result shapes.
"""

from app.rag.domain.models import (
    CitationReport,
    GroundingBundle,
    RetrievalResult,
    RetrievalState,
    SearchIntent,
)

__all__ = [
    "CitationReport",
    "GroundingBundle",
    "RetrievalResult",
    "RetrievalState",
    "SearchIntent",
]
