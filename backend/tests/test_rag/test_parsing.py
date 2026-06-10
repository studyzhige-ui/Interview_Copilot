"""E1 / §4.1.1: parser abstraction — ParseResult contract + selection/fallback.

The concrete parser wrappers load real files via LlamaIndex readers (not unit-
tested here); these cover the join helper, candidate selection (key-gated), and
the orchestration's fallback + parser_profile + empty handling with fakes.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.rag.parsing.registry as reg
from app.rag.parsing import ParseResult
from app.rag.parsing.base import TIER_FIRST_CLASS, TIER_LIGHTWEIGHT
from app.rag.parsing.parsers import _join_documents


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


def test_candidates_without_key_have_no_llamaparse(monkeypatch):
    monkeypatch.setattr(reg, "_has_llama_cloud", lambda: False)
    assert [p.id for p in reg._candidates(".pdf")] == ["pymupdf", "simple_reader"]
    assert [p.id for p in reg._candidates(".txt")] == ["simple_reader"]


def test_candidates_with_key_prefer_llamaparse(monkeypatch):
    monkeypatch.setattr(reg, "_has_llama_cloud", lambda: True)
    assert reg._candidates(".pdf")[0].id == "llamaparse"
    assert reg._candidates(".docx")[0].id == "llamaparse"
    # a format LlamaParse doesn't support still only gets the default reader.
    assert [p.id for p in reg._candidates(".txt")] == ["simple_reader"]


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
