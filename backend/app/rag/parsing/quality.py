"""Format-independent parser quality scoring and fallback policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.documents import CanonicalDocument

ACCEPT_SCORE = 0.82
MINIMUM_SCORE = 0.40


@dataclass(frozen=True)
class ParseQuality:
    score: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


def assess_parse_quality(document: CanonicalDocument) -> ParseQuality:
    text = document.text or ""
    if not text.strip():
        return ParseQuality(0.0, ("empty",))
    warnings: list[str] = []
    score = 1.0
    replacement_ratio = text.count("�") / max(1, len(text))
    if replacement_ratio:
        score -= min(0.55, replacement_ratio * 25)
        warnings.append("replacement_characters")

    meaningful = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", text)) / max(1, len(text))
    if meaningful < 0.12:
        score -= 0.45
        warnings.append("low_meaningful_character_ratio")
    elif meaningful < 0.25:
        score -= 0.18
        warnings.append("sparse_meaningful_text")

    lines = [
        " ".join(line.split()).casefold() for line in text.splitlines() if line.strip()
    ]
    if len(lines) >= 8:
        unique_ratio = len(set(lines)) / len(lines)
        if unique_ratio < 0.35:
            score -= 0.35
            warnings.append("high_line_repetition")
        elif unique_ratio < 0.60:
            score -= 0.12
            warnings.append("line_repetition")

    if len(text.strip()) < 20:
        score -= 0.20
        warnings.append("very_short_output")
    return ParseQuality(max(0.0, min(1.0, score)), tuple(warnings))


__all__ = ["ACCEPT_SCORE", "MINIMUM_SCORE", "ParseQuality", "assess_parse_quality"]
