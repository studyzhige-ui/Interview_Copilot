"""Tests for the embedding-model token counter (ingestion §4.3 / §4.5.2).

Behaviour is asserted via monkeypatched tokenizer loading so the tests are
environment-independent (no dependency on whether BGE-M3 is cached locally).
"""

from __future__ import annotations

import pytest
from app.rag import embedding_tokenizer as et


@pytest.fixture(autouse=True)
def _reset():
    et.reset_cache()
    yield
    et.reset_cache()


def test_empty_text_is_zero():
    assert et.count_tokens("") == 0


def test_estimate_fallback_when_no_local_tokenizer(monkeypatch):
    """Remote provider / model-not-cached → char-based estimate (len)."""
    monkeypatch.setattr(et, "_load_tokenizer", lambda: None)
    assert et.count_tokens("abcde") == 5
    assert et.count_tokens("缓存雪崩") == 4  # 1 token/char estimate


def test_uses_real_tokenizer_when_available(monkeypatch):
    class _FakeTok:
        def encode(self, text, add_special_tokens=False):
            assert add_special_tokens is False
            return text.split()  # 1 token per whitespace-separated word

    monkeypatch.setattr(et, "_load_tokenizer", lambda: _FakeTok())
    assert et.count_tokens("a b c d") == 4
    # NOT the char-estimate (which would be 7).
    assert et.count_tokens("a b c d") != len("a b c d")


def test_tokenizer_loaded_once_and_cached(monkeypatch):
    calls = {"n": 0}

    class _FakeTok:
        def encode(self, text, add_special_tokens=False):
            return list(text)

    def _load():
        calls["n"] += 1
        return _FakeTok()

    monkeypatch.setattr(et, "_load_tokenizer", _load)
    et.count_tokens("x")
    et.count_tokens("y")
    et.count_tokens("z")
    assert calls["n"] == 1  # loaded once, then cached


def test_unavailable_tokenizer_not_retried(monkeypatch):
    calls = {"n": 0}

    def _load():
        calls["n"] += 1
        return None

    monkeypatch.setattr(et, "_load_tokenizer", _load)
    et.count_tokens("a")
    et.count_tokens("b")
    assert calls["n"] == 1  # cached as unavailable (False), not re-attempted


def test_reset_cache_forces_reload(monkeypatch):
    monkeypatch.setattr(et, "_load_tokenizer", lambda: None)
    et.count_tokens("a")
    et.reset_cache()

    class _FakeTok:
        def encode(self, text, add_special_tokens=False):
            return list(text)

    monkeypatch.setattr(et, "_load_tokenizer", lambda: _FakeTok())
    assert et.count_tokens("abc") == 3  # reloaded → real tokenizer used


def test_load_tokenizer_returns_none_for_remote_provider(monkeypatch):
    """A non-local embedding provider has no local tokenizer to load."""
    from types import SimpleNamespace

    # _load_tokenizer imports resolve_embedding from embedding_registry, so
    # that is the binding to patch.
    import app.rag.embedding_registry as reg

    monkeypatch.setattr(
        reg,
        "resolve_embedding",
        lambda: SimpleNamespace(
            provider=SimpleNamespace(kind="openai_compat"), model="x"
        ),
    )
    assert et._load_tokenizer() is None
