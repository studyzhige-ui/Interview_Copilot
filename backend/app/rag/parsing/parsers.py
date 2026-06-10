"""Concrete parsers (Phase E1) — thin wrappers over the parser libraries the
project already uses, behind the :class:`DocumentParser` contract.

E1 keeps behaviour faithful to the previous inline logic: LlamaParse (first
class, when a LlamaCloud key is set) for PDF/PPTX/DOCX, PyMuPDF for PDF text,
and LlamaIndex's default ``SimpleDirectoryReader`` for everything else. Docling
(E2) and the per-format lightweight matrix (E3) register alongside these later.
"""
from __future__ import annotations

import os
from threading import Lock

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


def _read_text(file_path: str) -> str:
    """Read a text file with encoding detection (charset-normalizer), falling
    back to UTF-8 with replacement — the ingest text is always normalized to a
    str (plan §4.1.3: TXT/HTML/CSV encoding detection)."""
    from charset_normalizer import from_path

    best = from_path(file_path).best()
    if best is not None:
        return str(best)
    with open(file_path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


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


_docling_converter = None
# Docling reuses one pipeline per converter and its convert() is NOT thread-safe;
# ingestion runs in a THREADED Celery pool (worker-light: --pool=threads
# --concurrency=4), so this lock guards lazy construction AND serializes convert()
# across threads. Serializing the (heavy, background) parse is an acceptable cost;
# non-Docling parses don't take this lock.
_docling_lock = Lock()


def _get_docling_converter():
    """Build/return the cached Docling converter (model weights load on first
    convert). The caller holds ``_docling_lock`` — the converter is shared and
    docling's convert() isn't safe to run concurrently on it."""
    global _docling_converter
    if _docling_converter is None:
        from docling.document_converter import DocumentConverter

        _docling_converter = DocumentConverter()
    return _docling_converter


class DoclingParser:
    """First-class LOCAL parser → Markdown (peer to LlamaParse). Available only
    when the ``docling`` package is installed (the registry gates on that and
    degrades to LlamaParse / lightweight when it isn't). No OCR this round —
    scanned PDFs / images are a later round.

    xlsx is intentionally NOT claimed yet: Docling would emit a Markdown table,
    but the chunk stage routes ``.xlsx`` to the table splitter by filename
    (before the markdown branch), so xlsx stays on the lightweight path until E4
    handles Markdown tables. pdf/docx/pptx/html route to MarkdownNodeParser."""

    id = "docling"
    tier = TIER_FIRST_CLASS
    _EXTS = {".pdf", ".docx", ".pptx", ".html", ".htm"}

    def supports(self, ext: str) -> bool:
        return ext in self._EXTS

    def parse(self, file_path: str) -> ParseResult:
        with _docling_lock:  # serialize: Docling convert() isn't thread-safe
            converter = _get_docling_converter()
            result = converter.convert(file_path)
            markdown = result.document.export_to_markdown()
        # page_map is empty: Docling's exported Markdown exposes no per-page char
        # spans, so page_count reads 0 here (unlike PyMuPDF, which maps per page).
        # Accurate Docling page provenance is deferred to the page_start/end round.
        return ParseResult(markdown=markdown, parser_id=self.id, is_markdown=True, page_map=[])


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


# ── Per-format lightweight parsers (Phase E3) ────────────────────────────────
# Controlled, known-behaviour extractors used when no first-class parser is
# available/supports the format (plan §4.1.3) — they replace LlamaIndex's default
# readers for these formats so parse quality + failure behaviour is explicit.


class DocxParser:
    """Lightweight DOCX → paragraph text (python-docx). Body paragraphs only —
    no styles, tables, headers, or footers (the first-class parsers cover those)."""

    id = "python_docx"
    tier = TIER_LIGHTWEIGHT

    def supports(self, ext: str) -> bool:
        return ext == ".docx"

    def parse(self, file_path: str) -> ParseResult:
        import docx

        document = docx.Document(file_path)
        text = "\n\n".join(p.text for p in document.paragraphs if p.text.strip())
        return ParseResult(markdown=text, parser_id=self.id, is_markdown=False)


class PptxParser:
    """Lightweight PPTX → per-slide text (python-pptx)."""

    id = "python_pptx"
    tier = TIER_LIGHTWEIGHT

    def supports(self, ext: str) -> bool:
        return ext == ".pptx"

    def parse(self, file_path: str) -> ParseResult:
        from pptx import Presentation

        slides: list[str] = []
        for slide in Presentation(file_path).slides:
            parts = [
                shape.text for shape in slide.shapes
                if shape.has_text_frame and shape.text.strip()
            ]
            if parts:
                slides.append("\n".join(parts))
        return ParseResult(markdown="\n\n".join(slides), parser_id=self.id, is_markdown=False)


class XlsxParser:
    """Lightweight XLSX → per-sheet self-describing rows (openpyxl). Each cell is
    emitted as ``header: value`` so a row is understandable on its own — this
    keeps multi-sheet workbooks correct even though the chunk stage currently
    routes .xlsx to the table splitter (the proper table-aware routing is E4)."""

    id = "openpyxl"
    tier = TIER_LIGHTWEIGHT

    def supports(self, ext: str) -> bool:
        return ext == ".xlsx"

    def parse(self, file_path: str) -> ParseResult:
        from openpyxl import load_workbook

        workbook = load_workbook(file_path, read_only=True, data_only=True)
        try:
            lines: list[str] = []
            for sheet in workbook.worksheets:
                rows = list(sheet.iter_rows(values_only=True))
                if not rows:
                    continue
                header = [str(c) if c is not None else "" for c in rows[0]]
                for row in rows[1:]:
                    cells = [
                        f"{header[i]}: {value}"
                        for i, value in enumerate(row)
                        if value is not None and i < len(header)
                    ]
                    if cells:
                        lines.append(" | ".join(cells))
        finally:
            workbook.close()
        # No sheet marker: every row already self-describes (header: value), so
        # rows from different sheets stay correct without a "[Sheet]" line that
        # the table splitter would mis-promote to a repeated header.
        return ParseResult(markdown="\n".join(lines), parser_id=self.id, is_markdown=False)


class HtmlParser:
    """Lightweight HTML → Markdown (BeautifulSoup drops script/style/nav noise,
    then markdownify keeps heading/list/table structure). Emits Markdown
    (``is_markdown=True``) so the chunk stage uses MarkdownNodeParser — feeding
    HTMLNodeParser tag-stripped text yields zero nodes (silent content loss)."""

    id = "beautifulsoup"
    tier = TIER_LIGHTWEIGHT

    def supports(self, ext: str) -> bool:
        return ext in (".html", ".htm")

    def parse(self, file_path: str) -> ParseResult:
        from bs4 import BeautifulSoup
        from markdownify import markdownify

        soup = BeautifulSoup(_read_text(file_path), "html.parser")
        # Drop only navigation/script/style noise (plan §4.1.3) — not <header>/
        # <footer>, which semantic pages often use for real body content.
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        markdown = markdownify(str(soup)).strip()
        return ParseResult(markdown=markdown, parser_id=self.id, is_markdown=True)


class TextParser:
    """Lightweight TXT / CSV / TSV → encoding-detected text (charset-normalizer).
    CSV/TSV stays raw so the chunk stage's table splitter keeps the header row."""

    id = "text"
    tier = TIER_LIGHTWEIGHT
    _EXTS = {".txt", ".csv", ".tsv"}

    def supports(self, ext: str) -> bool:
        return ext in self._EXTS

    def parse(self, file_path: str) -> ParseResult:
        return ParseResult(markdown=_read_text(file_path), parser_id=self.id, is_markdown=False)
