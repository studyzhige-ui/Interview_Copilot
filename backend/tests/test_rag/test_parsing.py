"""E1 / §4.1.1: parser abstraction — ParseResult contract + selection/fallback.

The concrete parser wrappers load real files via LlamaIndex readers (not unit-
tested here); these cover the join helper, candidate selection (key-gated), and
the orchestration's fallback + parser_profile + empty handling with fakes.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.rag.parsing.parsers as parsers
import app.rag.parsing.registry as reg
from app.core.config import settings
from app.rag.parsing import ParseResult
from app.rag.parsing.base import TIER_FIRST_CLASS, TIER_LIGHTWEIGHT
from app.rag.parsing.parsers import DoclingParser, _join_documents


def test_join_documents_single_doc():
    md, page_map = _join_documents([SimpleNamespace(text="hello world", metadata={})])
    assert md == "hello world"
    assert len(page_map) == 1
    assert (page_map[0].char_start, page_map[0].char_end) == (0, 11)


def test_join_documents_multi_page_records_spans():
    docs = [
        SimpleNamespace(text="page one", metadata={"page_label": "1"}),
        SimpleNamespace(text="page two", metadata={"page_label": "2"}),
    ]
    md, page_map = _join_documents(docs)
    assert md == "page one\n\npage two"
    assert [p.page for p in page_map] == [1, 2]
    assert page_map[1].char_start == len("page one") + 2  # after the "\n\n"


def test_join_documents_skips_empty_segment_without_offset_drift():
    """An empty middle segment is dropped: it neither emits a page span nor
    advances the cursor, so the next span's char_start still indexes the join."""
    docs = [
        SimpleNamespace(text="aa", metadata={}),
        SimpleNamespace(text="", metadata={}),   # dropped
        SimpleNamespace(text="cc", metadata={}),
    ]
    md, page_map = _join_documents(docs)
    assert md == "aa\n\ncc"
    assert len(page_map) == 2
    assert md[page_map[1].char_start:page_map[1].char_end] == "cc"  # span indexes the join


def _knobs(monkeypatch, *, key: bool, docling: bool, provider: str):
    """Control the three selection knobs deterministically (E2)."""
    monkeypatch.setattr(reg, "_has_llama_cloud", lambda: key)
    monkeypatch.setattr(reg, "_docling_available", lambda: docling)
    monkeypatch.setattr(settings, "PARSER_PROVIDER", provider)


def _ids(ext):
    return [p.id for p in reg._candidates(ext)]


def test_candidates_degrade_to_lightweight_when_no_first_class(monkeypatch):
    _knobs(monkeypatch, key=False, docling=False, provider="docling")
    assert _ids(".pdf") == ["pymupdf", "simple_reader"]
    assert _ids(".xlsx") == ["openpyxl", "simple_reader"]
    assert _ids(".txt") == ["text", "simple_reader"]


def test_candidates_docling_primary(monkeypatch):
    _knobs(monkeypatch, key=False, docling=True, provider="docling")
    assert _ids(".pdf") == ["docling", "pymupdf", "simple_reader"]
    assert _ids(".html") == ["docling", "beautifulsoup", "simple_reader"]  # docling first-class
    assert _ids(".txt") == ["text", "simple_reader"]       # docling doesn't claim txt
    # xlsx not first-class (docling->markdown-table would misroute the table
    # splitter; deferred to E4) -> dedicated openpyxl lightweight.
    assert _ids(".xlsx") == ["openpyxl", "simple_reader"]


def test_candidates_llamaparse_primary_docling_fallback(monkeypatch):
    # The local config: key set + docling installed + PARSER_PROVIDER=llamaparse.
    _knobs(monkeypatch, key=True, docling=True, provider="llamaparse")
    # pdf: LlamaParse primary (cloud), Docling the document-level fallback.
    assert _ids(".pdf") == ["llamaparse", "docling", "pymupdf", "simple_reader"]
    assert _ids(".docx") == ["llamaparse", "docling", "python_docx", "simple_reader"]
    # html: LlamaParse doesn't claim it -> Docling (the other first-class) leads.
    assert _ids(".html") == ["docling", "beautifulsoup", "simple_reader"]
    # xlsx: neither first-class claims it -> dedicated openpyxl lightweight.
    assert _ids(".xlsx") == ["openpyxl", "simple_reader"]


def test_candidates_docling_primary_with_llama_fallback(monkeypatch):
    _knobs(monkeypatch, key=True, docling=True, provider="docling")
    assert _ids(".pdf") == ["docling", "llamaparse", "pymupdf", "simple_reader"]


def test_candidates_selected_primary_unavailable_degrades(monkeypatch):
    # PARSER_PROVIDER=docling but docling not installed, with a key present.
    _knobs(monkeypatch, key=True, docling=False, provider="docling")
    assert _ids(".pdf") == ["llamaparse", "pymupdf", "simple_reader"]  # falls to the available first-class
    assert _ids(".xlsx") == ["openpyxl", "simple_reader"]  # no first-class -> dedicated lightweight


class _FakeParser:
    def __init__(self, id_, tier, *, result=None, boom=False):
        self.id = id_
        self.tier = tier
        self._result = result
        self._boom = boom

    def supports(self, ext):
        return True

    def parse(self, file_path):
        if self._boom:
            raise RuntimeError("boom")
        return self._result


def test_parse_document_uses_first_success(monkeypatch):
    good = ParseResult(markdown="ok text", parser_id="good", is_markdown=True)
    monkeypatch.setattr(reg, "_candidates",
                        lambda ext: [_FakeParser("good", TIER_FIRST_CLASS, result=good)])

    out = reg.parse_document("x.pdf")
    assert out.markdown == "ok text" and out.parser_id == "good"
    assert out.parser_profile["fallback_used"] is False
    assert out.parser_profile["char_count"] == len("ok text")
    assert out.parser_profile["tier"] == TIER_FIRST_CLASS
    assert "duration_ms" in out.parser_profile
    assert "warnings" not in out.parser_profile  # clean parse carries no warnings key


def test_parse_document_merges_parser_own_warnings(monkeypatch):
    """A parser's own ParseResult.warnings are surfaced in parser_profile."""
    result = ParseResult(markdown="ok", parser_id="p", warnings=["low text quality"])
    monkeypatch.setattr(reg, "_candidates",
                        lambda ext: [_FakeParser("p", TIER_FIRST_CLASS, result=result)])

    out = reg.parse_document("x.pdf")
    assert out.parser_profile["warnings"] == ["low text quality"]


def test_parse_document_falls_back_on_failure(monkeypatch):
    recovered = ParseResult(markdown="recovered", parser_id="lw")
    monkeypatch.setattr(reg, "_candidates", lambda ext: [
        _FakeParser("first", TIER_FIRST_CLASS, boom=True),
        _FakeParser("lw", TIER_LIGHTWEIGHT, result=recovered),
    ])

    out = reg.parse_document("x.pdf")
    assert out.parser_id == "lw"
    assert out.parser_profile["fallback_used"] is True
    assert any("first" in w for w in out.parser_profile["warnings"])


def test_parse_document_skips_empty_then_succeeds(monkeypatch):
    monkeypatch.setattr(reg, "_candidates", lambda ext: [
        _FakeParser("blank", TIER_FIRST_CLASS, result=ParseResult(markdown="   ", parser_id="blank")),
        _FakeParser("lw", TIER_LIGHTWEIGHT, result=ParseResult(markdown="real", parser_id="lw")),
    ])
    out = reg.parse_document("x.pdf")
    assert out.parser_id == "lw" and out.parser_profile["fallback_used"] is True


def test_parse_document_all_empty_raises(monkeypatch):
    from app.rag.cleaning import EmptyContentError
    monkeypatch.setattr(reg, "_candidates", lambda ext: [
        _FakeParser("x", TIER_LIGHTWEIGHT, result=ParseResult(markdown="   ", parser_id="x")),
    ])
    with pytest.raises(EmptyContentError):
        reg.parse_document("x.pdf")


# ── E2: Docling first-class parser ───────────────────────────────────────────


def test_docling_parser_supports_structured_formats():
    p = DoclingParser()
    assert p.tier == TIER_FIRST_CLASS
    assert p.supports(".pdf") and p.supports(".docx") and p.supports(".pptx")
    assert p.supports(".html") and p.supports(".htm")
    # Images now route to Docling (on-demand OCR), §4.1.3.
    assert p.supports(".png") and p.supports(".jpg") and p.supports(".webp")
    # txt -> default reader; xlsx kept on lightweight path (E4); legacy office
    # (.xls/.doc/.ppt) deferred until the LibreOffice conversion path.
    assert not p.supports(".txt")
    assert not p.supports(".xlsx")
    assert not p.supports(".xls")


def test_parser_provider_normalized(monkeypatch):
    """PARSER_PROVIDER tolerates case / whitespace / empty (-> default docling)."""
    monkeypatch.setattr(reg, "_has_llama_cloud", lambda: True)
    monkeypatch.setattr(reg, "_docling_available", lambda: True)
    for value in ("  DOCLING  ", "Docling", ""):
        monkeypatch.setattr(settings, "PARSER_PROVIDER", value)
        assert _ids(".pdf")[0] == "docling", value


def test_unknown_parser_provider_warns_and_uses_insertion_order(monkeypatch, caplog):
    import logging
    _knobs(monkeypatch, key=True, docling=True, provider="doclng")  # typo
    with caplog.at_level(logging.WARNING):
        ids = _ids(".pdf")
    assert "unknown PARSER_PROVIDER" in caplog.text
    # insertion order: llamaparse registered before docling -> llamaparse leads.
    assert ids[0] == "llamaparse"


def test_htm_routes_through_docling_when_primary(monkeypatch):
    _knobs(monkeypatch, key=False, docling=True, provider="docling")
    assert _ids(".htm") == ["docling", "beautifulsoup", "simple_reader"]


def test_xls_legacy_office_not_parsed_by_first_class(monkeypatch):
    """Legacy .xls (deferred) isn't claimed by any first-class parser."""
    _knobs(monkeypatch, key=True, docling=True, provider="docling")
    assert _ids(".xls") == ["simple_reader"]


# ── E3: per-format lightweight fallback matrix ───────────────────────────────


def test_candidates_include_dedicated_lightweight(monkeypatch):
    """Each format gets its dedicated lightweight parser before the SimpleReader
    catch-all; uncovered formats (json) get only SimpleReader."""
    _knobs(monkeypatch, key=False, docling=False, provider="docling")
    assert _ids(".pdf") == ["pymupdf", "simple_reader"]
    assert _ids(".docx") == ["python_docx", "simple_reader"]
    assert _ids(".pptx") == ["python_pptx", "simple_reader"]
    assert _ids(".xlsx") == ["openpyxl", "simple_reader"]
    assert _ids(".html") == ["beautifulsoup", "simple_reader"]
    assert _ids(".csv") == ["text", "simple_reader"]
    assert _ids(".txt") == ["text", "simple_reader"]
    assert _ids(".json") == ["simple_reader"]


def test_candidates_first_class_then_lightweight_then_catchall(monkeypatch):
    _knobs(monkeypatch, key=False, docling=True, provider="docling")
    assert _ids(".docx") == ["docling", "python_docx", "simple_reader"]


def test_docx_parser_extracts_paragraphs(tmp_path):
    import docx
    path = tmp_path / "d.docx"
    document = docx.Document()
    document.add_paragraph("Hello world")
    document.add_paragraph("Second para")
    document.save(str(path))

    result = parsers.DocxParser().parse(str(path))
    assert "Hello world" in result.markdown and "Second para" in result.markdown
    assert result.parser_id == "python_docx" and result.is_markdown is False


def test_docx_parser_raises_on_corrupt_file(tmp_path):
    """A non-docx file makes DocxParser raise, so parse_document's except catches
    it and tries the next candidate (lightweight failure degrades gracefully)."""
    path = tmp_path / "fake.docx"
    path.write_text("this is not a docx", encoding="utf-8")
    with pytest.raises(Exception):
        parsers.DocxParser().parse(str(path))


def test_pptx_parser_extracts_slide_text(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches
    path = tmp_path / "s.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.text = "Slide content here"
    prs.save(str(path))

    result = parsers.PptxParser().parse(str(path))
    assert "Slide content here" in result.markdown
    assert result.parser_id == "python_pptx"


def test_xlsx_parser_self_describing_rows(tmp_path):
    from openpyxl import Workbook
    path = tmp_path / "x.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["name", "score"])
    ws.append(["alice", 90])
    wb.save(str(path))

    result = parsers.XlsxParser().parse(str(path))
    assert "name: alice" in result.markdown and "score: 90" in result.markdown
    assert result.parser_id == "openpyxl"


def test_xlsx_parser_empty_workbook_yields_empty(tmp_path):
    """An empty / header-only workbook yields no text → parse_document moves on."""
    from openpyxl import Workbook
    path = tmp_path / "empty.xlsx"
    wb = Workbook()
    wb.active.append(["just", "headers"])  # header row only, no data rows
    wb.save(str(path))
    assert parsers.XlsxParser().parse(str(path)).markdown == ""


def test_xlsx_parser_multi_sheet_keeps_per_sheet_headers(tmp_path):
    """Multi-sheet workbook: each sheet's rows self-describe with its OWN header
    (the E1 multi-sheet delta is neutralized by self-describing rows)."""
    from openpyxl import Workbook
    path = tmp_path / "m.xlsx"
    wb = Workbook()
    s1 = wb.active
    s1.title = "S1"
    s1.append(["alpha"])
    s1.append([1])
    s2 = wb.create_sheet("S2")
    s2.append(["beta"])
    s2.append([2])
    wb.save(str(path))

    result = parsers.XlsxParser().parse(str(path))
    assert "alpha: 1" in result.markdown   # S1 row self-describes with S1's header
    assert "beta: 2" in result.markdown    # S2 row self-describes with S2's header


def test_html_parser_to_markdown_drops_noise(tmp_path):
    path = tmp_path / "h.html"
    path.write_text(
        "<html><head><style>.x{color:red}</style></head>"
        "<body><nav>menu links</nav><h1>Heading</h1><p>Real content</p>"
        "<script>var a=1;</script></body></html>",
        encoding="utf-8",
    )
    result = parsers.HtmlParser().parse(str(path))
    assert result.is_markdown is True   # Markdown -> MarkdownNodeParser (not HTMLNodeParser)
    assert "Real content" in result.markdown and "Heading" in result.markdown
    assert "menu links" not in result.markdown
    assert "var a=1" not in result.markdown and "color:red" not in result.markdown


def test_html_parse_to_chunks_keeps_content(tmp_path, monkeypatch):
    """E2E seam: HtmlParser output must chunk to >=1 node with the content
    intact — guards the HTMLNodeParser-on-tag-stripped-text -> 0 nodes silent
    data loss (Docling-unavailable HTML fallback path)."""
    from llama_index.core import Document
    from app.rag import ingestion
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    path = tmp_path / "p.html"
    path.write_text(
        "<html><body><h1>Cache</h1><p>Redis avalanche detail.</p></body></html>",
        encoding="utf-8",
    )
    result = parsers.HtmlParser().parse(path.__fspath__())
    doc = Document(text=result.markdown, metadata={
        "source_kind": "user_upload", "user_id": 1, "file_name": "p.html",
        "is_markdown_parsed": result.is_markdown,
    })
    nodes = ingestion.get_optimal_nodes(doc)

    assert nodes, "HTML chunked to zero nodes — content lost"
    joined = " ".join(n.get_content() for n in nodes)
    assert "Redis avalanche detail" in joined


def test_text_parser_reads_with_encoding_detection(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("héllo wörld 缓存", encoding="utf-8")
    result = parsers.TextParser().parse(str(path))
    assert "héllo wörld 缓存" in result.markdown
    assert result.parser_id == "text"


def test_docling_parse_holds_lock_during_convert(monkeypatch):
    """DoclingParser serializes convert() under _docling_lock (Docling's
    convert() isn't thread-safe and ingestion runs in a threaded pool)."""
    held = {}

    class _LockCheckingConverter:
        def convert(self, file_path):
            held["locked_during_convert"] = parsers._docling_lock.locked()
            return SimpleNamespace(document=SimpleNamespace(
                export_to_markdown=lambda: "ok", pages={}))

    monkeypatch.setattr(parsers, "_get_docling_converter", lambda: _LockCheckingConverter())
    DoclingParser().parse("x.pdf")
    assert held["locked_during_convert"] is True


def test_docling_parser_exports_markdown(monkeypatch):
    """DoclingParser converts via the cached converter and returns its Markdown
    (converter mocked so no model download)."""
    class _FakeDoc:
        def export_to_markdown(self):
            return "# Title\n\nbody text"

    class _FakeConverter:
        def convert(self, file_path):
            return SimpleNamespace(document=_FakeDoc())

    monkeypatch.setattr(parsers, "_get_docling_converter", lambda: _FakeConverter())

    result = DoclingParser().parse("doc.pdf")
    assert result.markdown == "# Title\n\nbody text"
    assert result.parser_id == "docling"
    assert result.is_markdown is True


def test_docling_failure_falls_back_through_registry(monkeypatch):
    """A Docling convert failure degrades to the next candidate (no crash)."""
    _knobs(monkeypatch, key=False, docling=True, provider="docling")

    class _BoomConverter:
        def convert(self, file_path):
            raise RuntimeError("docling model load failed")

    monkeypatch.setattr(parsers, "_get_docling_converter", lambda: _BoomConverter())
    # Real candidate list (docling first), but docling.parse() raises -> registry
    # records the warning and falls through to PyMuPDF/SimpleReader. Stub those so
    # the test doesn't touch real files.
    monkeypatch.setattr(parsers.PyMuPDFParser, "parse",
                        lambda self, fp: ParseResult(markdown="pdf text", parser_id="pymupdf"))

    out = reg.parse_document("x.pdf")
    assert out.parser_id == "pymupdf"
    assert out.parser_profile["fallback_used"] is True
    assert any("docling" in w for w in out.parser_profile["warnings"])


# ── F1: OCR + image documents ────────────────────────────────────────────────


def test_llamaparse_supports_images():
    """LlamaParse claims images too (cloud OCR) so they route to it when it's
    the primary parser (plan §4.1.3 image matrix)."""
    from app.rag.parsing.parsers import LlamaParseParser
    p = LlamaParseParser()
    assert p.supports(".pdf") and p.supports(".docx")
    assert p.supports(".png") and p.supports(".jpeg") and p.supports(".tiff")


def test_ocr_enabled_requires_flag_and_engine(monkeypatch):
    """OCR runs only when RAG_OCR_ENABLED AND the engine is importable — so a
    deploy without rapidocr still parses text PDFs (do_ocr=False)."""
    monkeypatch.setattr(parsers, "_ocr_available", lambda: True)
    monkeypatch.setattr(settings, "RAG_OCR_ENABLED", True)
    assert parsers._ocr_enabled() is True
    # Flag off → disabled even with the engine present.
    monkeypatch.setattr(settings, "RAG_OCR_ENABLED", False)
    assert parsers._ocr_enabled() is False
    # Engine missing → disabled even with the flag on (graceful degradation).
    monkeypatch.setattr(settings, "RAG_OCR_ENABLED", True)
    monkeypatch.setattr(parsers, "_ocr_available", lambda: False)
    assert parsers._ocr_enabled() is False


def _fake_docling(monkeypatch, markdown="text"):
    class _FakeConverter:
        def convert(self, file_path):
            return SimpleNamespace(document=SimpleNamespace(
                export_to_markdown=lambda: markdown))
    monkeypatch.setattr(parsers, "_get_docling_converter", lambda: _FakeConverter())


def test_docling_stamps_ocr_used_for_image_when_ocr_active(monkeypatch):
    """An image IS OCR (its only text source) → ocr_used=True when OCR active;
    a text format is NOT marked OCR even with OCR active (never over-reports)."""
    _fake_docling(monkeypatch, markdown="OCR'd text")
    monkeypatch.setattr(parsers, "_ocr_enabled", lambda: True)

    img = DoclingParser().parse("scan.png")
    assert img.ocr_used is True and img.markdown == "OCR'd text"
    assert img.parser_id == "docling" and img.is_markdown is True

    pdf = DoclingParser().parse("doc.pdf")
    assert pdf.ocr_used is False  # text format, no over-report


def test_docling_image_not_marked_ocr_when_disabled(monkeypatch):
    """OCR off/unavailable → an image isn't marked ocr_used (the convert yields
    whatever text it can; empty would degrade to the registry's friendly error)."""
    _fake_docling(monkeypatch, markdown="x")
    monkeypatch.setattr(parsers, "_ocr_enabled", lambda: False)
    assert DoclingParser().parse("scan.jpg").ocr_used is False


def test_candidates_image_first_class_only_no_text_catchall(monkeypatch):
    """Images are first-class-OCR only (plan §4.1.3 matrix): NO dedicated
    lightweight AND NO SimpleReader text catch-all — a raw-bytes read of a
    .tiff/.bmp by SimpleDirectoryReader is binary garbage. So with no first-class
    the candidate list is EMPTY (→ friendly EmptyContentError), never garbage."""
    _knobs(monkeypatch, key=False, docling=True, provider="docling")
    assert _ids(".png") == ["docling"]
    # key + both first-class: LlamaParse primary, Docling the doc-level fallback.
    _knobs(monkeypatch, key=True, docling=True, provider="llamaparse")
    assert _ids(".jpg") == ["llamaparse", "docling"]
    # No first-class at all → empty candidate list (no text catch-all for images).
    _knobs(monkeypatch, key=False, docling=False, provider="docling")
    assert _ids(".webp") == []
    assert _ids(".tiff") == []


def test_parse_document_image_no_first_class_raises_friendly(monkeypatch):
    """A no-first-class deploy can't parse an image (no text fallback) → the
    friendly EmptyContentError, never silently-indexed garbage. parse_document
    raises on the empty candidate list without ever opening the file."""
    from app.rag.cleaning import EmptyContentError
    _knobs(monkeypatch, key=False, docling=False, provider="docling")
    with pytest.raises(EmptyContentError):
        reg.parse_document("scan.tiff")
