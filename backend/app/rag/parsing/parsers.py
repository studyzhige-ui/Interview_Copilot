"""Concrete parsers (Phase E1) — thin wrappers over the parser libraries the
project already uses, behind the :class:`DocumentParser` contract.

E1 keeps behaviour faithful to the previous inline logic: LlamaParse (first
class, when a LlamaCloud key is set) for PDF/PPTX/DOCX, PyMuPDF for PDF text,
and LlamaIndex's default ``SimpleDirectoryReader`` for everything else. Docling
(E2) and the per-format lightweight matrix (E3) register alongside these later.
"""

from __future__ import annotations

import csv
import os

from app.rag.documents import ParsedDocument, ParsedPage

from .base import (
    IMAGE_EXTS,
    LEGACY_OFFICE_EXTS,
    TIER_FIRST_CLASS,
    TIER_LIGHTWEIGHT,
)


def _pages_from_documents(docs: list) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    for i, d in enumerate(docs):
        text = getattr(d, "text", None) or ""
        if not text:
            continue
        meta = getattr(d, "metadata", None) or {}
        try:
            page = int(meta.get("page_label"))
        except (TypeError, ValueError):
            page = i + 1 if len(docs) > 1 else None
        pages.append(ParsedPage(text=text, number=page))
    return pages


def _read_text(file_path: str) -> str:
    """Read a text file with encoding detection (charset-normalizer), falling
    back to UTF-8 with replacement — the ingest text is always normalized to a
    str (plan §4.1.3: TXT/HTML/CSV encoding detection)."""
    from charset_normalizer import from_bytes

    with open(file_path, "rb") as fh:
        raw = fh.read()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    best = from_bytes(raw).best()
    if best is not None:
        return str(best)
    return raw.decode("utf-8", errors="replace")


class LlamaParseParser:
    """First-class cloud parser → Markdown. Available only when a LlamaCloud key
    is configured (the registry gates on that). Claims images (cloud OCR) and
    legacy Office (.doc/.ppt/.xls, parsed directly) too — so when LlamaParse is
    the primary parser those go to the cloud instead of local RapidOCR / the
    LibreOffice conversion path (plan §4.1.3 matrix)."""

    id = "llamaparse"
    tier = TIER_FIRST_CLASS
    _EXTS = {".pdf", ".pptx", ".docx"} | IMAGE_EXTS | LEGACY_OFFICE_EXTS

    def supports(self, ext: str) -> bool:
        return ext in self._EXTS

    def parse(self, file_path: str) -> ParsedDocument:
        from app.rag.parsing.cloud import parse

        return parse(file_path)


class DoclingParser:
    """First-class local Markdown parser, delegated to an owned CPU process.

    The selected interpreter may be separate from the portable API environment.
    Input snapshots, page/output bounds and process-tree cleanup are mandatory.
    """

    id = "docling"
    tier = TIER_FIRST_CLASS
    _EXTS = {".pdf", ".docx", ".pptx", ".html", ".htm"} | IMAGE_EXTS

    def supports(self, ext: str) -> bool:
        return ext in self._EXTS

    def parse(self, file_path: str) -> ParsedDocument:
        from .local_document import parse_local_document

        return parse_local_document(file_path)


class PyMuPDFParser:
    """Lightweight PDF text extraction (no cloud, no OCR)."""

    id = "pymupdf"
    tier = TIER_LIGHTWEIGHT

    def supports(self, ext: str) -> bool:
        return ext == ".pdf"

    def parse(self, file_path: str) -> ParsedDocument:
        from llama_index.core import SimpleDirectoryReader
        from llama_index.readers.file import PyMuPDFReader

        docs = SimpleDirectoryReader(
            input_files=[file_path],
            file_extractor={".pdf": PyMuPDFReader()},
        ).load_data()
        return ParsedDocument(
            pages=_pages_from_documents(docs),
            parser_id=self.id,
            content_kind="text",
        )


# ── Per-format lightweight parsers ───────────────────────────────────────────


class DocxParser:
    """Lightweight DOCX → paragraph text (python-docx). Body paragraphs only —
    no styles, tables, headers, or footers (the first-class parsers cover those)."""

    id = "python_docx"
    tier = TIER_LIGHTWEIGHT

    def supports(self, ext: str) -> bool:
        return ext == ".docx"

    def parse(self, file_path: str) -> ParsedDocument:
        import docx

        document = docx.Document(file_path)
        text = "\n\n".join(p.text for p in document.paragraphs if p.text.strip())
        return ParsedDocument(
            pages=[ParsedPage(text=text)], parser_id=self.id, content_kind="text"
        )


class PptxParser:
    """Lightweight PPTX → per-slide text (python-pptx)."""

    id = "python_pptx"
    tier = TIER_LIGHTWEIGHT

    def supports(self, ext: str) -> bool:
        return ext == ".pptx"

    def parse(self, file_path: str) -> ParsedDocument:
        from pptx import Presentation

        slides: list[ParsedPage] = []
        for index, slide in enumerate(Presentation(file_path).slides, start=1):
            parts = [
                shape.text
                for shape in slide.shapes
                if shape.has_text_frame and shape.text.strip()
            ]
            if parts:
                slides.append(ParsedPage(text="\n".join(parts), number=index))
        return ParsedDocument(pages=slides, parser_id=self.id, content_kind="text")


class XlsxParser:
    """Lightweight XLSX → per-sheet self-describing rows (openpyxl). Each cell is
    emitted as ``header: value`` so a row is understandable on its own — this
    keeps multi-sheet workbooks correct even though the chunk stage currently
    routes .xlsx to the table splitter (the proper table-aware routing is E4)."""

    id = "openpyxl"
    tier = TIER_LIGHTWEIGHT

    def supports(self, ext: str) -> bool:
        return ext == ".xlsx"

    def parse(self, file_path: str) -> ParsedDocument:
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
                        lines.append(f"sheet: {sheet.title} | " + " | ".join(cells))
        finally:
            workbook.close()
        # No sheet marker: every row already self-describes (header: value), so
        # rows from different sheets stay correct without a "[Sheet]" line that
        # the table splitter would mis-promote to a repeated header.
        return ParsedDocument(
            pages=[ParsedPage(text="\n".join(lines))],
            parser_id=self.id,
            content_kind="table",
        )


class HtmlParser:
    """Lightweight HTML → Markdown (BeautifulSoup drops script/style/nav noise,
    then markdownify keeps heading/list/table structure). Emits Markdown
    Markdown output lets the chunk stage use MarkdownNodeParser — feeding
    HTMLNodeParser tag-stripped text yields zero nodes (silent content loss)."""

    id = "beautifulsoup"
    tier = TIER_LIGHTWEIGHT

    def supports(self, ext: str) -> bool:
        return ext in (".html", ".htm")

    def parse(self, file_path: str) -> ParsedDocument:
        from bs4 import BeautifulSoup
        from markdownify import markdownify

        soup = BeautifulSoup(_read_text(file_path), "html.parser")
        # Drop only navigation/script/style noise (plan §4.1.3) — not <header>/
        # <footer>, which semantic pages often use for real body content.
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        markdown = markdownify(str(soup)).strip()
        return ParsedDocument(
            pages=[ParsedPage(text=markdown)],
            parser_id=self.id,
            content_kind="markdown",
        )


class TextParser:
    """Normalize text, delimited tables, JSON, Markdown, and source code."""

    id = "text"
    tier = TIER_LIGHTWEIGHT
    _EXTS = {
        ".txt",
        ".csv",
        ".tsv",
        ".md",
        ".markdown",
        ".json",
        ".py",
        ".java",
        ".cpp",
        ".c",
    }

    def supports(self, ext: str) -> bool:
        return ext in self._EXTS

    def parse(self, file_path: str) -> ParsedDocument:
        ext = os.path.splitext(file_path)[1].lower()
        text = _read_text(file_path)
        if ext in {".csv", ".tsv"}:
            rows = list(
                csv.reader(
                    text.splitlines(),
                    delimiter="," if ext == ".csv" else "\t",
                )
            )
            header = rows[0] if rows else []
            records = [
                " | ".join(
                    f"{header[index]}: {value}"
                    for index, value in enumerate(row)
                    if index < len(header) and value
                )
                for row in rows[1:]
            ]
            text = "\n".join(record for record in records if record)
            content_kind = "table"
        elif ext in {".md", ".markdown"}:
            content_kind = "markdown"
        elif ext == ".json":
            content_kind = "json"
        elif ext in {".py", ".java", ".cpp", ".c"}:
            content_kind = "code"
        else:
            content_kind = "text"
        return ParsedDocument(
            pages=[ParsedPage(text=text)],
            parser_id=self.id,
            content_kind=content_kind,
        )
