"""Versioned index infrastructure used by every knowledge RAG path."""

from app.rag.index.identity import (
    INDEX_SCHEMA_VERSION,
    IndexIdentity,
    current_index_identity,
)

__all__ = ["INDEX_SCHEMA_VERSION", "IndexIdentity", "current_index_identity"]
