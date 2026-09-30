"""Local analyzer invariants; quality equivalence is a separate held-out evaluation."""

import pytest

from app.rag.index.lexical import bm25_reference, term_counts


def test_chinese_boundaries_and_technical_identifiers():
    result = term_counts("Redis缓存 FastAPI snake_case C++ C# asyncio.to_thread")
    assert (
        set(
            (
                "redis",
                "缓存",
                "fastapi",
                "fast",
                "api",
                "snake_case",
                "snake",
                "case",
                "c++",
                "c#",
                "asyncio.to_thread",
                "thread",
            )
        )
        <= result.keys()
    )
    assert "redis缓存" not in result


def test_unicode_normalization_repeated_terms_and_blank():
    assert term_counts("ＲＥＤＩＳ redis") == {"redis": 2}
    assert term_counts(" \n\t") == {}
    assert term_counts("缓缓存") == {"缓": 2, "存": 1, "缓缓": 1, "缓存": 1}


@pytest.mark.parametrize(
    "text,query",
    [
        ("界" * 43000, False),
        ("a" * 8001, True),
        (" ".join(f"term{i}" for i in range(300)), True),
    ],
)
def test_explicit_capacity_rejection_not_silent_truncation(text, query):
    with pytest.raises(ValueError):
        term_counts(text, query=query)


def test_bm25_empty_unmatched_and_repeated_query():
    assert bm25_reference([], "x") == []
    assert bm25_reference([{}, {}], "x") == [0.0, 0.0]
    corpus = [term_counts("Redis cache"), term_counts("other text")]
    assert bm25_reference(corpus, "redis")[0] > 0
    assert bm25_reference(corpus, "redis")[1] == 0
    assert bm25_reference(corpus, "redis redis") == bm25_reference(corpus, "redis")
