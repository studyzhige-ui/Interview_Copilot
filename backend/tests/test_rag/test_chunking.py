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
