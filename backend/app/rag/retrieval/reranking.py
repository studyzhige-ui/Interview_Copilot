"""Cross-encoder reranking and coverage-aware evidence allocation."""

from __future__ import annotations

import asyncio
import math
from typing import Any

from llama_index.core import QueryBundle
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, TextNode

from app.rag.domain.models import SearchIntent
from app.rag.policy import current_rag_policy
from app.rag.retrieval.candidates import IntentCandidates
from app.rag.retrieval.fusion import normalized_text_hash


def _rerank_group(
    reranker: BaseNodePostprocessor,
    group: IntentCandidates,
) -> list[dict[str, Any]]:
    nodes = [
        NodeWithScore(
            node=TextNode(
                text=str(hit.get("text") or ""),
                id_=str(hit.get("id") or ""),
                metadata={
                    "user_id": hit.get("user_id"),
                    "source_kind": hit.get("source_kind"),
                    "document_id": hit.get("document_id"),
                },
                excluded_embed_metadata_keys=["user_id", "source_kind", "document_id"],
            ),
            score=float(hit.get("score") or 0.0),
        )
        for hit in group.hits
    ]
    ranked = reranker.postprocess_nodes(nodes, QueryBundle(group.intent.query))
    by_id = {str(hit.get("id") or ""): hit for hit in group.hits}
    output: list[dict[str, Any]] = []
    for item in ranked:
        node_id = str(item.node.node_id or "")
        if not node_id or node_id not in by_id:
            continue
        output.append(
            {
                **by_id[node_id],
                "score": float(item.score) if item.score is not None else None,
                "intent_ids": [group.intent.intent_id],
            }
        )
    return output


async def rerank_groups(
    reranker: BaseNodePostprocessor,
    groups: list[IntentCandidates],
) -> list[list[dict[str, Any]]]:
    """Rerank independent intents concurrently under one bounded deadline."""

    tasks = [asyncio.to_thread(_rerank_group, reranker, group) for group in groups]
    return list(
        await asyncio.wait_for(
            asyncio.gather(*tasks),
            timeout=current_rag_policy().retrieval.rerank_timeout_seconds,
        )
    )


def select_coverage_aware(
    groups: list[list[dict[str, Any]]],
    intents: list[SearchIntent],
    *,
    min_score: float,
    final_count: int,
    score_margin: float | None,
) -> list[dict[str, Any]]:
    """Reserve one qualifying passage per intent, then fill globally by score."""

    qualifying: list[list[dict[str, Any]]] = []
    for group in groups:
        valid = [
            row
            for row in group
            if row.get("score") is not None
            and math.isfinite(float(row["score"]))
            and float(row["score"]) >= min_score
        ]
        if len(intents) == 1 and valid and score_margin is not None:
            best = float(valid[0]["score"])
            valid = [row for row in valid if float(row["score"]) >= best - score_margin]
        qualifying.append(valid)

    # A configured top-k smaller than the planned intent count must not make
    # complete coverage mathematically impossible.
    effective_limit = max(final_count, len(intents))
    selected: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    seen_texts: dict[str, str] = {}

    def add(row: dict[str, Any]) -> None:
        node_id = str(row.get("id") or "")
        if not node_id:
            return
        existing = by_id.get(node_id)
        if existing is not None:
            existing["intent_ids"] = list(
                dict.fromkeys(
                    [*existing.get("intent_ids", []), *row.get("intent_ids", [])]
                )
            )
            existing["score"] = max(float(existing["score"]), float(row["score"]))
            return
        text_hash = normalized_text_hash(str(row.get("text") or ""))
        duplicate_id = seen_texts.get(text_hash)
        if duplicate_id and duplicate_id in by_id:
            duplicate = by_id[duplicate_id]
            duplicate["intent_ids"] = list(
                dict.fromkeys(
                    [*duplicate.get("intent_ids", []), *row.get("intent_ids", [])]
                )
            )
            return
        copied = {**row, "intent_ids": list(row.get("intent_ids", []))}
        by_id[node_id] = copied
        seen_texts[text_hash] = node_id
        selected.append(copied)

    for group in qualifying:
        if group:
            add(group[0])
    remaining = sorted(
        (row for group in qualifying for row in group[1:]),
        key=lambda row: float(row.get("score") or 0.0),
        reverse=True,
    )
    for row in remaining:
        if len(selected) >= effective_limit:
            break
        add(row)
    return sorted(
        selected[:effective_limit],
        key=lambda row: float(row.get("score") or 0.0),
        reverse=True,
    )


__all__ = ["rerank_groups", "select_coverage_aware"]
