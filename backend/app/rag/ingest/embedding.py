"""Retrieval-text construction and validated document embedding."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from llama_index.core import Settings

from app.rag import embedding_registry
from app.rag.index.vector_validation import validate_vectors
from app.rag.retrieval_text import build_retrieval_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    profile: dict[str, Any]


def node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if not text and hasattr(node, "get_content"):
        text = node.get_content()
    return str(text or "")


def node_id(node: Any) -> str:
    return str(getattr(node, "node_id", None) or getattr(node, "id_", None) or "")


def drop_blank_nodes(nodes: list[Any]) -> list[Any]:
    kept = [node for node in nodes if node_text(node).strip()]
    if len(kept) != len(nodes):
        logger.warning(
            "Dropped %d blank chunks before embedding", len(nodes) - len(kept)
        )
    return kept


def _metadata(node: Any) -> dict[str, Any]:
    value = getattr(node, "metadata", None)
    if isinstance(value, dict):
        return value
    raw = getattr(node, "metadata_json", None)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def build_retrieval_passages(
    nodes: list[Any],
    *,
    document_title: str | None,
) -> list[str]:
    return [
        build_retrieval_text(
            node_text(node),
            document_title=document_title,
            section_title=_metadata(node).get("section_title"),
            heading_path=_metadata(node).get("heading_path"),
        )
        for node in nodes
    ]


def embed_passages(
    passages: list[str],
    *,
    embed_model: Any | None = None,
) -> EmbeddingBatch:
    cfg = embedding_registry.resolve_embedding()
    model = embed_model or Settings.embed_model
    started = time.perf_counter()
    raw = model.get_text_embedding_batch(passages, show_progress=False)
    vectors = validate_vectors(
        raw,
        expected_count=len(passages),
        expected_dim=cfg.dim,
        label="文档",
    )
    profile = {
        "embedding_provider": cfg.provider_id,
        "embedding_model": cfg.model,
        "embedding_dim": cfg.dim,
        "embedding_batch_size": getattr(model, "embed_batch_size", None),
        "embedding_duration_ms": int((time.perf_counter() - started) * 1000),
        "embedding_chunk_count": len(passages),
    }
    return EmbeddingBatch(vectors=vectors, profile=profile)


__all__ = [
    "EmbeddingBatch",
    "build_retrieval_passages",
    "drop_blank_nodes",
    "embed_passages",
    "node_id",
    "node_text",
]
