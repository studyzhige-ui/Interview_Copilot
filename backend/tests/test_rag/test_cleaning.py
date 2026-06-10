"""Tests for S0 conservative cleaning (ingestion §4.2)."""
from __future__ import annotations

import pytest

from app.rag.cleaning import EmptyContentError, clean_text


def test_normalizes_newlines_crlf_and_cr():
    out, _ = clean_text("a\r\nb\rc")
    assert out == "a\nb\nc"


def test_strips_bom_and_nul_and_control_chars():
    out, profile = clean_text("﻿head\x00er\x07 text")
    assert "﻿" not in out
    assert "\x00" not in out and "\x07" not in out
    assert out == "header text"
    assert profile.removed_control_chars == 2  # NUL + BEL


def test_keeps_tabs_and_newlines():
    out, _ = clean_text("col1\tcol2\nrow")
    assert out == "col1\tcol2\nrow"


def test_trims_trailing_whitespace_per_line():
    out, _ = clean_text("foo   \nbar\t\n")
    assert out == "foo\nbar"


def test_collapses_long_blank_runs():
    out, _ = clean_text("a\n\n\n\n\nb")
    assert out == "a\n\nb"


def test_strips_leading_trailing_blank_lines():
    out, _ = clean_text("\n\n  hello  \n\n")
    assert out == "hello"


def test_nfc_normalization_is_applied():
    import unicodedata
    decomposed = "é"  # e + combining acute
    out, _ = clean_text(decomposed)
    assert out == unicodedata.normalize("NFC", decomposed)
    assert len(out) == 1


def test_uses_nfc_not_aggressive_nfkc():
    """Must be SAFE NFC, not NFKC — full-width / ligatures / superscripts that
    NFKC would fold must survive unchanged (plan §4.2 '默认只做安全规范化')."""
    for s in ("Ａ", "ﬁ", "²", "Ⅳ", "①"):
        out, _ = clean_text(s)
        assert out == s, f"{s!r} was folded — looks like NFKC, not NFC"


def test_preserves_format_chars_emoji_zwj_and_rtl():
    """Cf format chars (emoji ZWJ, RTL marks) are NOT control chars and must
    be kept — removing them would corrupt emoji sequences / bidi text."""
    family = "👨‍👩‍👧"  # ZWJ-joined family emoji
    rtl = "abc‏دef"  # RLM
    assert clean_text(family)[0] == family
    assert clean_text(rtl)[0] == rtl


def test_mojibake_warning_on_high_replacement_ratio():
    out, profile = clean_text("��������x")
    assert profile.replacement_char_count == 8
    assert "mojibake_suspected" in profile.warnings


def test_clean_text_is_idempotent_on_clean_input():
    once, _ = clean_text("Redis 缓存雪崩\n\n解决方案：随机化过期时间。")
    twice, _ = clean_text(once)
    assert once == twice


def test_profile_records_char_counts():
    out, profile = clean_text("  abc  ")
    assert profile.char_in == 7
    assert profile.char_out == len(out) == 3


def test_empty_input_returns_empty():
    out, profile = clean_text("")
    assert out == ""
    assert profile.char_in == 0


def test_whitespace_only_cleans_to_empty():
    out, _ = clean_text("   \n\t  \r\n ")
    assert out == ""


# ── _clean_documents orchestration (drop-empty + empty protection) ──────


class _FakeDoc:
    def __init__(self, text: str):
        self.text = text
        self.metadata: dict = {}

    def set_content(self, value: str) -> None:
        self.text = value


def test_clean_documents_drops_empty_segments():
    from app.rag import ingestion

    docs = [_FakeDoc("  real content  "), _FakeDoc("   \x00  ")]
    kept = ingestion._clean_documents(docs)

    assert len(kept) == 1
    assert kept[0].text == "real content"
    # Method A: the cleaning profile is logged, NOT stamped onto metadata
    # (no DB landing path yet — that's B4's metadata_json restructure).
    assert "cleaning_profile" not in kept[0].metadata


def test_clean_documents_raises_when_all_empty():
    from app.rag import ingestion

    with pytest.raises(EmptyContentError):
        ingestion._clean_documents([_FakeDoc("   "), _FakeDoc("\n\n")])


def test_clean_documents_noop_when_disabled(monkeypatch):
    from app.rag import ingestion

    monkeypatch.setattr(ingestion.settings, "RAG_CLEANING_ENABLED", False)
    docs = [_FakeDoc("   raw   ")]
    kept = ingestion._clean_documents(docs)
    # Untouched: no cleaning, no drop, no profile stamp.
    assert kept[0].text == "   raw   "
    assert "cleaning_profile" not in kept[0].metadata


async def test_ingest_text_raises_empty_content_on_whitespace():
    """The text ingest path (improved_qa / manual_text) enforces the same
    empty protection — whitespace-only content raises before any DB/Milvus."""
    from app.rag.ingestion import ingest_text

    with pytest.raises(EmptyContentError):
        await ingest_text("   \n\t  ", source_kind="manual_text", user_id=1)
