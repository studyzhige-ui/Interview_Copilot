"""Parse-stage contract (Phase E / plan §4.1.1).

The ingest pipeline consumes a single ``ParseResult`` and never touches a
parser library's object model directly. Concrete parsers (LlamaParse, Docling,
PyMuPDF, the per-format lightweight readers) implement :class:`DocumentParser`;
the registry/orchestration in ``parsing.registry`` picks among them (first-class
primary -> other first-class fallback -> per-format lightweight) and translates
failures. Output is always Markdown (or best-effort readable text).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# A parser's tier in the fallback matrix (plan §4.1.3):
#   first_class — high-quality structured Markdown (LlamaParse / Docling)
#   lightweight — per-format best-effort text (PyMuPDF / python-docx / ...)
TIER_FIRST_CLASS = "first_class"
TIER_LIGHTWEIGHT = "lightweight"


@dataclass(frozen=True)
class PageSpan:
    """A page's character span within ``ParseResult.markdown`` — best-effort
    page provenance. Empty for formats with no page concept."""
    page: int
    char_start: int
    char_end: int


@dataclass
class ParseResult:
    """What every parser returns and the ingest pipeline consumes.

    ``parser_id`` / ``ocr_used`` are separate top-level diagnostics (mirroring
    ``splitter_id``) for quick filtering; ``parser_profile`` carries the rest
    (tier / fallback_used / page_count / char_count / duration_ms / warnings).
    All three land in ``document_chunks.metadata_json`` — the producers B4
    reserved as forward keys.
    """
    markdown: str
    parser_id: str = ""
    is_markdown: bool = False          # output is structured Markdown -> MarkdownNodeParser
    ocr_used: bool = False
    page_map: list[PageSpan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parser_profile: dict = field(default_factory=dict)


@runtime_checkable
class DocumentParser(Protocol):
    """A replaceable parser. ``id`` identifies it (also stamped as parser_id),
    ``tier`` places it in the fallback matrix, ``supports`` gates by extension,
    and ``parse`` produces a :class:`ParseResult`. A parser raises on failure;
    the orchestration records the warning and tries the next candidate."""

    id: str
    tier: str

    def supports(self, ext: str) -> bool: ...

    def parse(self, file_path: str) -> ParseResult: ...
