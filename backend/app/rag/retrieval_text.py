"""Build the index-only text used by retrieval models.

Postgres keeps the original chunk as the answer fact. Milvus receives a short,
stable structural prefix so dense retrieval, BM25 and the cross-encoder can
identify otherwise context-free fragments without adding generated text.
"""

from __future__ import annotations

from collections.abc import Iterable


def build_retrieval_text(
    text: str,
    *,
    document_title: str | None = None,
    section_title: str | None = None,
    heading_path: Iterable[str] | None = None,
) -> str:
    title = " ".join((document_title or "").split())[:120]
    headings: list[str] = []
    seen_headings: set[str] = set()
    for value in [*(heading_path or ()), section_title or ""]:
        cleaned = " ".join(str(value).split())[:120]
        normalized = cleaned.casefold()
        if cleaned and normalized not in seen_headings:
            headings.append(cleaned)
            seen_headings.add(normalized)

    prefix: list[str] = []
    if title:
        prefix.append(f"Document: {title}")
    if headings:
        prefix.append(f"Section: {' > '.join(headings)}")
    structural = "\n".join(prefix)[:256]
    return "\n".join([structural, text]) if structural else text


__all__ = ["build_retrieval_text"]
