"""Deterministic qualifier checks scoped to the evidence of each intent."""

from __future__ import annotations

import re

from app.rag.domain.models import SearchIntent


def compact_term(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value.casefold())


def missing_terms_by_intent(
    intents: list[SearchIntent],
    chunks: list[dict],
) -> list[str]:
    missing: list[str] = []
    for intent in intents:
        evidence = compact_term(
            "\n".join(
                f"{chunk.get('document_title') or ''}\n{chunk.get('text') or ''}"
                for chunk in chunks
                if intent.intent_id in chunk.get("intent_ids", [])
            )
        )
        for term in intent.required_terms:
            compacted = compact_term(term)
            if compacted and compacted not in evidence:
                missing.append(term)
    return list(dict.fromkeys(missing))


__all__ = [
    "compact_term",
    "missing_terms_by_intent",
]
