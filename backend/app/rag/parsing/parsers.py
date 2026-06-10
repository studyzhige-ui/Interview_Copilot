"""Concrete parsers (Phase E1) — thin wrappers over the parser libraries the
project already uses, behind the :class:`DocumentParser` contract.

E1 keeps behaviour faithful to the previous inline logic: LlamaParse (first
class, when a LlamaCloud key is set) for PDF/PPTX/DOCX, PyMuPDF for PDF text,
and LlamaIndex's default ``SimpleDirectoryReader`` for everything else. Docling
(E2) and the per-format lightweight matrix (E3) register alongside these later.
"""
from __future__ import annotations

import os

from app.core.config import settings

from .base import ParseResult, PageSpan, TIER_FIRST_CLASS, TIER_LIGHTWEIGHT


def _join_documents(docs: list) -> tuple[str, list[PageSpan]]:
    """Join LlamaIndex ``Document``s into one Markdown string + a best-effort
    page map. A single-Document format yields identical text; a multi-page PDF
    is joined (page boundaries preserved in ``page_map``, not as hard splits)."""
    parts: list[str] = []
    page_map: list[PageSpan] = []
    cursor = 0
    for i, d in enumerate(docs):
        text = getattr(d, "text", None) or ""
        if not text:
            continue
        meta = getattr(d, "metadata", None) or {}
        try:
            page = int(meta.get("page_label"))
        except (TypeError, ValueError):
            page = i + 1
        page_map.append(PageSpan(page=page, char_start=cursor, char_end=cursor + len(text)))
        parts.append(text)
        cursor += len(text) + 2  # the "\n\n" the join inserts
    return "\n\n".join(parts), page_map


class LlamaParseParser:
    """First-class cloud parser → Markdown. Available only when a LlamaCloud key
    is configured (the registry gates on that)."""

    id = "llamaparse"
    tier = TIER_FIRST_CLASS
    _EXTS = {".pdf", ".pptx", ".docx"}

    def supports(self, ext: str) -> bool:
        return ext in self._EXTS

    def parse(self, file_path: str) -> ParseResult:
        import nest_asyncio
        from llama_index.core import SimpleDirectoryReader
        from llama_parse import LlamaParse

        nest_asyncio.apply()
        parser = LlamaParse(
            result_type="markdown", language="ch_sim",
            api_key=settings.LLAMA_CLOUD_API_KEY, num_workers=2,
        )
        ext = os.path.splitext(file_path)[1].lower()
        docs = SimpleDirectoryReader(
            input_files=[file_path], file_extractor={ext: parser},
        ).load_data()
        markdown, page_map = _join_documents(docs)
        return ParseResult(
            markdown=markdown, parser_id=self.id, is_markdown=True, page_map=page_map,
        )


class PyMuPDFParser:
    """Lightweight PDF text extraction (no cloud, no OCR)."""

    id = "pymupdf"
    tier = TIER_LIGHTWEIGHT

    def supports(self, ext: str) -> bool:
        return ext == ".pdf"

    def parse(self, file_path: str) -> ParseResult:
        from llama_index.core import SimpleDirectoryReader
        from llama_index.readers.file import PyMuPDFReader

        docs = SimpleDirectoryReader(
            input_files=[file_path], file_extractor={".pdf": PyMuPDFReader()},
        ).load_data()
        markdown, page_map = _join_documents(docs)
        return ParseResult(
            markdown=markdown, parser_id=self.id, is_markdown=False, page_map=page_map,
        )


class SimpleReaderParser:
    """LlamaIndex's default reader — the catch-all for the remaining formats
    (txt / md / html / json / csv / docx-without-key / ...). Also the final
    fallback for any extension."""

    id = "simple_reader"
    tier = TIER_LIGHTWEIGHT
    _MARKDOWN_EXTS = {".md", ".markdown"}

    def supports(self, ext: str) -> bool:
        return True

    def parse(self, file_path: str) -> ParseResult:
        from llama_index.core import SimpleDirectoryReader

        docs = SimpleDirectoryReader(input_files=[file_path]).load_data()
        markdown, page_map = _join_documents(docs)
        ext = os.path.splitext(file_path)[1].lower()
        return ParseResult(
            markdown=markdown, parser_id=self.id,
            is_markdown=ext in self._MARKDOWN_EXTS, page_map=page_map,
        )
