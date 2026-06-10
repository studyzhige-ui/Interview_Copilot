"""B6 / §4.5.1: an existing Milvus collection whose dense dim != EMBEDDING_DIM
must fail loud on first use, so a changed embedding model/dim can't silently
write into an index built for a different dim. Introspection failures degrade
to best-effort (log + proceed) rather than blocking a working index.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.rag import milvus_hybrid
from app.rag.embedding_registry import EmbeddingValidationError


class _FakeClient:
    def __init__(self, dim):
        self._dim = dim

    def describe_collection(self, name):
        return {"fields": [
            {"name": "id"},
            {"name": "dense", "params": {"dim": self._dim}},
            {"name": "sparse"},
        ]}


def test_dim_mismatch_fails_loud():
    bad = _FakeClient(settings.EMBEDDING_DIM + 256)
    with pytest.raises(EmbeddingValidationError):
        milvus_hybrid._assert_collection_dim(bad, "interview_copilot_rag")


def test_matching_dim_passes():
    ok = _FakeClient(settings.EMBEDDING_DIM)
    milvus_hybrid._assert_collection_dim(ok, "interview_copilot_rag")  # no raise


def test_uninspectable_dim_proceeds(caplog):
    class _BadClient:
        def describe_collection(self, name):
            raise RuntimeError("describe unavailable")

    # Best-effort: a describe failure must not block a working index.
    milvus_hybrid._assert_collection_dim(_BadClient(), "interview_copilot_rag")
