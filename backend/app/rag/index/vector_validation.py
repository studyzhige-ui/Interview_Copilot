"""Validation shared by document and query embedding paths."""

from __future__ import annotations

import math
from collections.abc import Iterable

from app.rag.embedding_registry import EmbeddingValidationError


def validate_vector(
    vector: Iterable[float], *, expected_dim: int, label: str
) -> list[float]:
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError, OverflowError) as exc:
        raise EmbeddingValidationError(f"{label}向量包含非数值元素。") from exc
    if len(values) != expected_dim:
        raise EmbeddingValidationError(
            f"{label}向量维度({len(values)})与配置 EMBEDDING_DIM({expected_dim})不一致。"
        )
    if not all(math.isfinite(value) for value in values):
        raise EmbeddingValidationError(f"{label}向量包含 NaN 或 Infinity。")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        raise EmbeddingValidationError(f"{label}向量为零向量，无法用于检索。")
    return values


def validate_vectors(
    vectors: list[Iterable[float]],
    *,
    expected_count: int,
    expected_dim: int,
    label: str,
) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise EmbeddingValidationError(
            f"{label}向量数量({len(vectors)})与文本数量({expected_count})不一致。"
        )
    return [
        validate_vector(vector, expected_dim=expected_dim, label=f"{label}[{index}]")
        for index, vector in enumerate(vectors)
    ]


__all__ = ["validate_vector", "validate_vectors"]
