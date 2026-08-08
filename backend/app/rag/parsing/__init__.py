"""Multi-format parsing into the canonical ingestion contract."""

from app.rag.documents import CanonicalDocument, ParsedDocument, ParsedPage

from .base import DocumentParser
from .registry import parse_document

__all__ = [
    "CanonicalDocument",
    "DocumentParser",
    "ParsedDocument",
    "ParsedPage",
    "parse_document",
]
