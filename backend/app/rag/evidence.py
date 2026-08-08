"""Deterministic evidence checks for exact query qualifiers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.rag.contracts import SearchIntent


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value.casefold())


@dataclass(frozen=True)
class EvidenceDecision:
    supported: bool
    missing_terms: tuple[str, ...] = ()


def check_evidence(
    intents: Iterable[SearchIntent],
    evidence_texts: Iterable[str],
) -> EvidenceDecision:
    """Require planner-declared exact qualifiers to occur in the evidence.

    The planner may only copy these qualifiers from the user's conversation,
    so this gate needs no product dictionaries, aliases, or language-specific
    heuristics.
    """
    evidence = _compact("\n".join(evidence_texts))
    missing = tuple(
        dict.fromkeys(
            term
            for intent in intents
            for term in intent.required_terms
            if _compact(term) and _compact(term) not in evidence
        )
    )
    return EvidenceDecision(supported=not missing, missing_terms=missing)


__all__ = ["EvidenceDecision", "check_evidence"]
