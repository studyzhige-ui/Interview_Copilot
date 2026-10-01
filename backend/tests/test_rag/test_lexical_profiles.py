"""The migrated dictionary analyzer uses the canonical generation boundary."""

import pytest
from app.core.config import settings
from app.rag.index.identity import current_index_identity
from app.rag.index.lexical import term_counts, JIEBA_ANALYZER_VERSION


def test_remote_default_remains_deterministic_cjk(monkeypatch):
    monkeypatch.setattr(settings, "RAG_LEXICAL_ANALYZER", "cjk_bigrams")
    assert term_counts("数据库") == {"数": 1, "据": 1, "库": 1, "数据": 1, "据库": 1}


def test_jieba_search_normalization_and_new_generation(monkeypatch):
    monkeypatch.setattr(settings, "RAG_LEXICAL_ANALYZER", "cjk_bigrams")
    original = current_index_identity().fingerprint
    monkeypatch.setattr(settings, "RAG_LEXICAL_ANALYZER", "jieba_search")
    assert current_index_identity().analyzer_contract == JIEBA_ANALYZER_VERSION
    assert current_index_identity().fingerprint != original
    terms = term_counts("数据库 Ｐｙｔｈｏｎ")
    assert terms["数据库"] == 1
    assert terms["python"] == 1
    assert terms == term_counts("数据库 python", query=True)
    assert " " not in terms


def test_jieba_queries_keep_existing_capacity_limits(monkeypatch):
    monkeypatch.setattr(settings, "RAG_LEXICAL_ANALYZER", "jieba_search")
    with pytest.raises(ValueError, match="byte capacity"):
        term_counts("q" * 8001, query=True)
    with pytest.raises(ValueError, match="distinct lexical"):
        term_counts(" ".join(f"word{i}" for i in range(300)), query=True)
