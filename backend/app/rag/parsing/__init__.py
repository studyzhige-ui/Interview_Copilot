"""Parse stage (Phase E) — a replaceable parser abstraction.

The ingest pipeline consumes a single ``ParseResult`` from :func:`parse_document`
and never binds to a parser library directly (plan §4.1.1).
"""
from .base import DocumentParser, PageSpan, ParseResult
from .registry import parse_document

__all__ = ["DocumentParser", "PageSpan", "ParseResult", "parse_document"]
