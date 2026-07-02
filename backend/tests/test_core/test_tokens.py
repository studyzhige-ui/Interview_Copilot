"""Tests for the canonical token helpers in ``app.core.tokens``."""
from __future__ import annotations

from app.core import tokens as cm


def test_token_count_empty_is_zero():
    assert cm.token_count("") == 0


def test_truncate_to_tokens_returns_full_text_under_budget():
    text = "Redis 缓存击穿"
    assert cm.truncate_to_tokens(text, 1000) == text


def test_truncate_to_tokens_cuts_to_budget():
    text = "word " * 500
    out = cm.truncate_to_tokens(text, 10)
    assert cm.token_count(out) <= 10
    assert len(out) < len(text)


def test_truncate_to_tokens_zero_or_empty_is_empty():
    assert cm.truncate_to_tokens("anything", 0) == ""
    assert cm.truncate_to_tokens("", 10) == ""
