"""Safe normalization and canonical-document tests."""

from __future__ import annotations

import pytest

from app.rag.cleaning import EmptyContentError, canonicalize_document, clean_text
from app.rag.documents import ParsedDocument, ParsedPage


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\r\nb\rc", "a\nb\nc"),
        ("﻿head\x00er\x07 text", "header text"),
        ("a\n\n\n\nb", "a\n\nb"),
        ("\n  hello  \n", "hello"),
    ],
)
def test_safe_text_normalization(raw, expected):
    assert clean_text(raw)[0] == expected


def test_nfc_does_not_apply_compatibility_folding():
    assert clean_text("é")[0] == "é"
    for value in ("Ａ", "ﬁ", "²", "Ⅳ", "①"):
        assert clean_text(value)[0] == value


def test_format_characters_survive():
    assert clean_text("👨‍👩‍👧")[0] == "👨‍👩‍👧"
    assert clean_text("abc‏دef")[0] == "abc‏دef"


def test_profile_reports_mojibake_and_removed_controls():
    _, profile = clean_text("����\x00x")
    assert profile.removed_control_chars == 1
    assert profile.replacement_char_count == 4
    assert "mojibake_suspected" in profile.warnings


def test_canonical_document_removes_repeated_page_furniture_and_maps_pages():
    parsed = ParsedDocument(
        parser_id="fixture",
        pages=[
            ParsedPage("Guide\nFirst answer\nPage 1", 1),
            ParsedPage("Guide\nSecond answer\nPage 2", 2),
            ParsedPage("Guide\nThird answer\nPage 3", 3),
        ],
    )
    result = canonicalize_document(parsed, parser_profile={"tier": "test"})
    assert result.text == "First answer\n\nSecond answer\n\nThird answer"
    assert [span.page for span in result.page_spans] == [1, 2, 3]
    assert all(
        result.text[span.char_start : span.char_end] for span in result.page_spans
    )
    assert result.cleaning_profile["removed_repeated_edges"] == 6


def test_non_repeated_edge_content_is_preserved():
    parsed = ParsedDocument(
        parser_id="fixture",
        pages=[
            ParsedPage("Introduction\nA", 1),
            ParsedPage("Implementation\nB", 2),
            ParsedPage("Conclusion\nC", 3),
        ],
    )
    assert "Introduction" in canonicalize_document(parsed, parser_profile={}).text


def test_empty_canonical_document_is_rejected():
    parsed = ParsedDocument(pages=[ParsedPage(" \n\x00")], parser_id="fixture")
    with pytest.raises(EmptyContentError):
        canonicalize_document(parsed, parser_profile={})


async def test_ingest_text_rejects_empty_input_before_storage():
    from app.rag.ingestion import ingest_text

    with pytest.raises(EmptyContentError):
        await ingest_text(
            "   \n\t",
            source_kind="manual_text",
            user_id=1,
            document_id="doc-empty",
        )
