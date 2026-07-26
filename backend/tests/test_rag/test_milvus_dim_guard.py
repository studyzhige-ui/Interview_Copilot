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
        return {
            "fields": [
                {"name": "id"},
                {"name": "dense", "params": {"dim": self._dim}},
                {"name": "sparse"},
            ]
        }


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


def test_nonnumeric_dim_proceeds():
    """A non-numeric dim degrades to best-effort (no uncaught int() error)."""

    class _WeirdClient:
        def describe_collection(self, name):
            return {"fields": [{"name": "dense", "params": {"dim": "oops"}}]}

    milvus_hybrid._assert_collection_dim(
        _WeirdClient(), "interview_copilot_rag"
    )  # no raise


# ── validate_existing_dims: startup guard (§4.5.1) ──────────────────────────


class _StartupClient:
    """has_collection only True for names in ``present``; describe returns dim."""

    def __init__(self, present, dim):
        self._present = set(present)
        self._dim = dim

    def has_collection(self, name):
        return name in self._present

    def describe_collection(self, name):
        return {"fields": [{"name": "dense", "params": {"dim": self._dim}}]}


def test_validate_existing_dims_raises_on_mismatch(monkeypatch):
    client = _StartupClient(
        present=[milvus_hybrid.KNOWLEDGE.name], dim=settings.EMBEDDING_DIM + 128
    )
    monkeypatch.setattr(milvus_hybrid, "_get_client", lambda: client)
    with pytest.raises(EmbeddingValidationError):
        milvus_hybrid.validate_existing_dims(milvus_hybrid.KNOWLEDGE)


def test_validate_existing_dims_skips_absent_collections(monkeypatch):
    # No collection exists yet → nothing to validate, never raises (a fresh
    # deploy must not be blocked).
    client = _StartupClient(present=[], dim=settings.EMBEDDING_DIM + 128)
    monkeypatch.setattr(milvus_hybrid, "_get_client", lambda: client)
    milvus_hybrid.validate_existing_dims(milvus_hybrid.KNOWLEDGE, milvus_hybrid.RESUME)


def test_validate_existing_dims_best_effort_when_unreachable(monkeypatch):
    def _boom():
        raise RuntimeError("milvus down")

    monkeypatch.setattr(milvus_hybrid, "_get_client", _boom)
    # Must not crash boot when Milvus is unreachable.
    milvus_hybrid.validate_existing_dims(milvus_hybrid.KNOWLEDGE)
