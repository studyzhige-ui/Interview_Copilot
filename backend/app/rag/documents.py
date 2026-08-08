"""Parser-independent document representations."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedPage:
    text: str
    number: int | None = None


@dataclass
class ParsedDocument:
    pages: list[ParsedPage]
    parser_id: str
    content_kind: str = "text"
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PageSpan:
    page: int
    char_start: int
    char_end: int


@dataclass
class CanonicalDocument:
    """Clean text plus provenance consumed by every chunking strategy."""

    text: str
    content_kind: str
    page_spans: list[PageSpan]
    parser_id: str
    parser_profile: dict
    cleaning_profile: dict
    ocr_used: bool = False


__all__ = [
    "CanonicalDocument",
    "PageSpan",
    "ParsedDocument",
    "ParsedPage",
]
