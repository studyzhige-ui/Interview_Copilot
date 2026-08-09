"""Deterministic fusion and de-duplication of retrieval channels."""

from __future__ import annotations

import hashlib
import unicodedata
from collections import defaultdict
from typing import Any


def normalized_text_hash(text: str) -> str:
    collapsed = " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    weights: list[float],
    rrf_k: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Fuse independent dense/sparse rankings without mixing raw score scales."""

    if len(ranked_lists) != len(weights):
        raise ValueError("ranked_lists and weights must align")
    scores: defaultdict[str, float] = defaultdict(float)
    rows: dict[str, dict[str, Any]] = {}
    for hits, weight in zip(ranked_lists, weights):
        for rank, hit in enumerate(hits, start=1):
            node_id = str(hit.get("id") or "")
            if not node_id:
                continue
            scores[node_id] += float(weight) / (rrf_k + rank)
            rows.setdefault(node_id, hit)
    ranked = sorted(
        ({**rows[node_id], "score": score} for node_id, score in scores.items()),
        key=lambda row: float(row["score"]),
        reverse=True,
    )
    seen_texts: set[str] = set()
    output: list[dict[str, Any]] = []
    for row in ranked:
        text_hash = normalized_text_hash(str(row.get("text") or ""))
        if text_hash in seen_texts:
            continue
        seen_texts.add(text_hash)
        output.append(row)
        if len(output) >= limit:
            break
    return output


__all__ = ["normalized_text_hash", "reciprocal_rank_fusion"]
