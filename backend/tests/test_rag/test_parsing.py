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
    assert _ids(".xlsx") == ["simple_reader"]
    assert _ids(".txt") == ["simple_reader"]


def test_candidates_docling_primary(monkeypatch):
    _knobs(monkeypatch, key=False, docling=True, provider="docling")
    assert _ids(".pdf") == ["docling", "pymupdf", "simple_reader"]
    assert _ids(".html") == ["docling", "simple_reader"]   # docling handles html
    assert _ids(".txt") == ["simple_reader"]               # docling doesn't claim txt
    # xlsx stays on the lightweight path (docling->markdown-table would misroute
    # through the table splitter; deferred to E4).
    assert _ids(".xlsx") == ["simple_reader"]


def test_candidates_llamaparse_primary_docling_fallback(monkeypatch):
    # The local config: key set + docling installed + PARSER_PROVIDER=llamaparse.
    _knobs(monkeypatch, key=True, docling=True, provider="llamaparse")
    # pdf: LlamaParse primary (cloud), Docling the document-level fallback.
    assert _ids(".pdf") == ["llamaparse", "docling", "pymupdf", "simple_reader"]
    assert _ids(".docx") == ["llamaparse", "docling", "simple_reader"]
    # html: LlamaParse doesn't claim it -> Docling (the other first-class) leads.
    assert _ids(".html") == ["docling", "simple_reader"]
    # xlsx: neither first-class claims it -> lightweight only.
    assert _ids(".xlsx") == ["simple_reader"]


def test_candidates_docling_primary_with_llama_fallback(monkeypatch):
    _knobs(monkeypatch, key=True, docling=True, provider="docling")
    assert _ids(".pdf") == ["docling", "llamaparse", "pymupdf", "simple_reader"]


def test_candidates_selected_primary_unavailable_degrades(monkeypatch):
    # PARSER_PROVIDER=docling but docling not installed, with a key present.
    _knobs(monkeypatch, key=True, docling=False, provider="docling")
    assert _ids(".pdf") == ["llamaparse", "pymupdf", "simple_reader"]  # falls to the available first-class
    assert _ids(".xlsx") == ["simple_reader"]  # llamaparse can't, docling absent


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
    # txt -> default reader; xlsx kept on lightweight path (E4); images / legacy
    # office (.xls) deferred.
    assert not p.supports(".txt")
    assert not p.supports(".xlsx")
    assert not p.supports(".xls")
    assert not p.supports(".png")


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
    assert _ids(".htm") == ["docling", "simple_reader"]


def test_xls_legacy_office_not_parsed_by_first_class(monkeypatch):
    """Legacy .xls (deferred) isn't claimed by any first-class parser."""
    _knobs(monkeypatch, key=True, docling=True, provider="docling")
    assert _ids(".xls") == ["simple_reader"]


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
