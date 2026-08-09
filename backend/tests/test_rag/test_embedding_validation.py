"""Canonical ingestion embedding validation and blank filtering.

``embed_passages`` must fail the whole document (EmbeddingValidationError) on a
dim or count mismatch BEFORE any index write, and emit an observability profile
on success. ``drop_blank_nodes`` removes empty/whitespace chunks so the Milvus
index and the Postgres fact rows stay in sync (plan §4.5.2/§4.5.3/§4.5.4).
"""

from __future__ import annotations

import app.rag.embedding_registry as er
import pytest
from app.rag.cleaning import EmptyContentError
from app.rag.embedding_registry import EmbeddingValidationError
from app.rag.index.knowledge import replace_document_rows
from app.rag.ingest.embedding import drop_blank_nodes, embed_passages
from app.rag.ingest.pipeline import ingest_text
from llama_index.core.schema import TextNode


class _FakeEmbed:
    embed_batch_size = 8

    def __init__(self, vectors):
        self._vectors = vectors

    def get_text_embedding_batch(self, texts, show_progress=False):
        return self._vectors


def test_remote_openai_compatible_embedding_builds_without_local_stack(monkeypatch):
    from llama_index.embeddings.openai_like import OpenAILikeEmbedding

    monkeypatch.setattr(er.settings, "EMBEDDING_PROVIDER", "siliconflow")
    monkeypatch.setattr(er.settings, "EMBEDDING_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")

    assert isinstance(er.build_embedding(), OpenAILikeEmbedding)


def _use_fake_embed(monkeypatch, vectors, dim):
    """Pin the embedding identity and return a duck-typed embedding model."""
    monkeypatch.setattr(
        er,
        "resolve_embedding",
        lambda: er.ResolvedEmbedding(
            "local", er.PROVIDERS["local"], "BAAI/bge-m3", dim
        ),
    )
    return _FakeEmbed(vectors)


def test_embed_texts_success_builds_profile(monkeypatch):
    model = _use_fake_embed(
        monkeypatch,
        [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]],
        dim=4,
    )
    batch = embed_passages(["a", "b"], embed_model=model)

    assert len(batch.vectors) == 2
    assert batch.profile["embedding_provider"] == "local"
    assert batch.profile["embedding_model"] == "BAAI/bge-m3"
    assert batch.profile["embedding_dim"] == 4
    assert batch.profile["embedding_chunk_count"] == 2
    assert batch.profile["embedding_batch_size"] == 8
    assert "embedding_duration_ms" in batch.profile


def test_embed_texts_dim_mismatch_raises(monkeypatch):
    # model returns 3-dim vectors but config expects 4 → permanent failure.
    model = _use_fake_embed(
        monkeypatch,
        [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        dim=4,
    )
    with pytest.raises(EmbeddingValidationError):
        embed_passages(["a", "b"], embed_model=model)


def test_embed_texts_count_mismatch_raises(monkeypatch):
    # 2 texts but only 1 vector back → abort, never write a partial index.
    model = _use_fake_embed(monkeypatch, [[0.1, 0.2, 0.3, 0.4]], dim=4)
    with pytest.raises(EmbeddingValidationError):
        embed_passages(["a", "b"], embed_model=model)


@pytest.mark.parametrize(
    "vector",
    ([0.0, 0.0], [float("nan"), 1.0], ["not-a-number", 1.0]),
)
def test_shared_vector_validation_rejects_unusable_vectors(vector):
    from app.rag.index.vector_validation import validate_vector

    with pytest.raises(EmbeddingValidationError):
        validate_vector(vector, expected_dim=2, label="test")


def test_drop_blank_nodes_filters_empty_and_whitespace():
    nodes = [
        TextNode(text="real content"),
        TextNode(text="   \n\t  "),
        TextNode(text=""),
    ]
    kept = drop_blank_nodes(nodes)

    assert len(kept) == 1
    assert kept[0].get_content() == "real content"


def test_drop_blank_nodes_keeps_all_when_none_blank():
    nodes = [TextNode(text="a"), TextNode(text="b")]
    assert len(drop_blank_nodes(nodes)) == 2


def test_insert_milvus_rows_payload_has_only_index_fields(monkeypatch):
    """The Milvus row payload carries only scope + text + dense; diagnostic
    fields like embedding_profile never become Milvus scalars (§4.5.4). The
    profile-on-node stamping is covered by the _index_nodes order tests."""
    import app.rag.milvus_hybrid as mh

    captured: dict = {}
    monkeypatch.setattr(mh, "delete_by_field", lambda *a, **k: None)
    monkeypatch.setattr(
        mh, "insert", lambda coll, rows: captured.__setitem__("rows", rows)
    )

    nodes = [
        TextNode(text="alpha", id_="n1", metadata={"embedding_profile": {"x": 1}}),
        TextNode(text="beta", id_="n2"),
    ]
    replace_document_rows(
        nodes,
        ["alpha", "beta"],
        [[0.1, 0.2], [0.3, 0.4]],
        user_id=1,
        source_kind="user_upload",
        document_id="doc1",
    )

    assert captured["rows"]
    for row in captured["rows"]:
        assert set(row) == {
            "id",
            "user_id",
            "source_kind",
            "document_id",
            "text",
            "dense",
        }


async def test_ingest_text_all_blank_raises_empty(monkeypatch):
    """When chunking yields only blank nodes, ingest_text fails the document
    (EmptyContentError) before any index/fact write."""
    with pytest.raises(EmptyContentError):
        await ingest_text(
            "some real source text",
            "manual_text",
            user_id=1,
            document_id="doc-blank",
            _chunker=lambda *_args, **_kwargs: [
                TextNode(text="   "),
                TextNode(text=""),
            ],
            _document_title_loader=lambda _id: None,
        )
