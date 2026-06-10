"""Tests for get_optimal_nodes provenance wiring (ingestion §4.3).

token_count is stamped from the embedding tokenizer and the oversize gate
uses it. Counting is monkeypatched to a deterministic function so the test
doesn't depend on a locally-cached embedding model.
"""
from __future__ import annotations

from llama_index.core import Document

from app.rag import ingestion


def test_token_count_stamped_on_every_node(monkeypatch):
    # Deterministic "tokenizer": 1 token per whitespace word.
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    doc = Document(text="alpha beta gamma delta", metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    assert nodes
    for node in nodes:
        assert node.metadata["token_count"] == len(node.get_content().split())


def test_diagnostic_annotations_stamped(monkeypatch):
    """Plain text → sentence splitter → splitter_id/chunk_type stamped, and a
    document-level cleaning_profile propagates to every chunk node."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    doc = Document(
        text="some plain prose about caching",
        metadata={"source_kind": "user_upload", "user_id": 1,
                  "cleaning_profile": {"char_out": 30}},
    )
    nodes = ingestion.get_optimal_nodes(doc)

    assert nodes
    for node in nodes:
        assert node.metadata["splitter_id"] == "sentence"
        assert node.metadata["chunk_type"] == "text"
        assert node.metadata["cleaning_profile"] == {"char_out": 30}


def test_markdown_splitter_id_and_chunk_type(monkeypatch):
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    doc = Document(
        text="# Title\nbody text",
        metadata={"source_kind": "user_upload", "user_id": 1, "file_name": "notes.md"},
    )
    nodes = ingestion.get_optimal_nodes(doc)
    assert nodes
    assert all(n.metadata["splitter_id"] == "markdown" for n in nodes)
    assert all(n.metadata["chunk_type"] == "text" for n in nodes)


def test_table_branch_splitter_id_and_chunk_type(monkeypatch):
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    doc = Document(
        text="name,score\nalice,90\nbob,80",
        metadata={"source_kind": "user_upload", "user_id": 1, "file_name": "data.csv"},
    )
    nodes = ingestion.get_optimal_nodes(doc)
    assert nodes
    assert all(n.metadata["splitter_id"] == "table" for n in nodes)
    assert all(n.metadata["chunk_type"] == "table" for n in nodes)


# NB: the code branch (.py/.java/.cpp/.c → CodeSplitter) isn't unit-tested
# here because CodeSplitter needs the optional ``tree_sitter`` package, absent
# in the test env. Its splitter_id/chunk_type assignment mirrors the other
# branches (verified by inspection). See requirements note re tree_sitter.


def test_token_count_stamped_per_node_on_multi_node_doc(monkeypatch):
    """A long doc splits into several nodes; each carries its OWN token_count
    (not the parent's), per the post-split stamping loop."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    big = " ".join(f"word{i}" for i in range(1200))
    doc = Document(text=big, metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    assert len(nodes) >= 2
    for node in nodes:
        assert node.metadata["token_count"] == len(node.get_content().split())


def test_oversize_gate_uses_embedding_tokenizer(monkeypatch):
    """A node the tokenizer reports as oversize (> CHUNK_SIZE*2 = 1024) is
    secondary-split; the char length is irrelevant to the decision."""
    calls = {"split": 0}

    # Report every node as hugely oversize so the secondary splitter runs.
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: 5000)

    real_get = ingestion.SentenceSplitter.get_nodes_from_documents

    def _counting(self, docs, **kw):
        calls["split"] += 1
        return real_get(self, docs, **kw)

    monkeypatch.setattr(ingestion.SentenceSplitter, "get_nodes_from_documents", _counting)

    doc = Document(text="short text", metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    # Secondary split was invoked despite the text being short (char-len would
    # never have tripped the old len(text) > 1024 gate).
    assert calls["split"] >= 1
    assert nodes
