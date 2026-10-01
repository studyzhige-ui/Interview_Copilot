"""Versioned local tokenizer and BM25 reference, without downloads or global state.

CJK unigrams/bigrams retain short Chinese terms without a separately maintained
segmentation dictionary. Latin identifiers keep their original spelling (case
folded), plus separator/camel-case components. This is explicitly NOT Milvus'
jieba analyzer; compare it on the frozen corpus before calling it quality-neutral.
The production scorer runs in PostgreSQL using the same counts and parameters.
"""

from __future__ import annotations

import math
import re
import unicodedata
from functools import lru_cache
from collections import Counter
from collections.abc import Mapping, Sequence

ANALYZER_VERSION = "cjk-bigram-identifiers-bm25-v1"
JIEBA_ANALYZER_VERSION = "postgres-jieba-0.42.1-search-bm25-1.2-0.75-v1"


def current_analyzer_contract() -> str:
    from app.core.config import settings

    return (
        JIEBA_ANALYZER_VERSION
        if settings.RAG_LEXICAL_ANALYZER == "jieba_search"
        else ANALYZER_VERSION
    )


@lru_cache(maxsize=1)
def _jieba_tokenizer():
    import jieba

    if jieba.__version__ != "0.42.1":
        raise ValueError("jieba_analyzer_version_mismatch")
    tokenizer = jieba.Tokenizer()
    tokenizer.initialize()
    return tokenizer


BM25_K1 = 1.2
BM25_B = 0.75
MAX_TEXT_BYTES = 128_000
MAX_QUERY_BYTES = 8_000
MAX_QUERY_TERMS = 256
_CJK = r"[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002ffff]"
_WORD = r"[^\W_\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002ffff]"
_PARTS = re.compile(
    _CJK
    + r"+|[A-Za-z][A-Za-z0-9_]*(?:\+\+|#)|"
    + _WORD
    + r"+(?:[_.:/+\-]"
    + _WORD
    + r"+)*",
    re.UNICODE,
)
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+")


def term_counts(text: str, *, query: bool = False) -> dict[str, int]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > (
        MAX_QUERY_BYTES if query else MAX_TEXT_BYTES
    ):
        raise ValueError("lexical input exceeds the declared byte capacity")
    if current_analyzer_contract() == JIEBA_ANALYZER_VERSION:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        counts = Counter(
            token
            for token in _jieba_tokenizer().cut_for_search(normalized, HMM=False)
            if token.strip() and any(character.isalnum() for character in token)
        )
        if query and len(counts) > MAX_QUERY_TERMS:
            raise ValueError("too many distinct lexical query terms")
        return dict(counts)
    counts: Counter[str] = Counter()
    for match in _PARTS.finditer(unicodedata.normalize("NFKC", text)):
        raw = match.group()
        if re.fullmatch(_CJK + "+", raw):
            counts.update(raw)
            counts.update(raw[i : i + 2] for i in range(len(raw) - 1))
        else:
            value = raw.casefold()
            counts[value] += 1
            pieces = {part.casefold() for part in re.split(r"[_.:/+\-]+", raw)}
            pieces.update(part.casefold() for part in _CAMEL.findall(raw))
            counts.update(piece for piece in pieces if piece and piece != value)
    if query and len(counts) > MAX_QUERY_TERMS:
        raise ValueError("too many distinct lexical query terms")
    return dict(counts)


def bm25_reference(corpus: Sequence[Mapping[str, int]], query: str) -> list[float]:
    """Small deterministic test oracle; production never materializes a corpus."""
    wanted = term_counts(query, query=True)
    if not corpus:
        return []
    n = len(corpus)
    lengths = [sum(row.values()) for row in corpus]
    average = sum(lengths) / n or 1.0
    df = {term: sum(term in row for row in corpus) for term in wanted}
    return [
        sum(
            math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            * (row.get(term, 0) * (BM25_K1 + 1))
            / (row.get(term, 0) + BM25_K1 * (1 - BM25_B + BM25_B * length / average))
            for term in wanted
            if row.get(term, 0)
        )
        for row, length in zip(corpus, lengths)
    ]
