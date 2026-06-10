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


def test_code_branch_splitter_id_and_chunk_type(monkeypatch):
    """Code files use CodeSplitter with an explicitly-built tree-sitter Parser
    (the get_parser isinstance workaround)."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    doc = Document(
        text="def f():\n    return 1\n\nclass A:\n    pass\n",
        metadata={"source_kind": "user_upload", "user_id": 1, "file_name": "m.py"},
    )
    nodes = ingestion.get_optimal_nodes(doc)
    assert nodes
    assert all(n.metadata["splitter_id"] == "code" for n in nodes)
    assert all(n.metadata["chunk_type"] == "code" for n in nodes)


def test_c_file_uses_cpp_grammar(monkeypatch):
    """.c reuses the cpp grammar (existing behaviour) and still splits."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    doc = Document(
        text="#include <stdio.h>\nint main(void) {\n    return 0;\n}\n",
        metadata={"source_kind": "user_upload", "user_id": 1, "file_name": "m.c"},
    )
    nodes = ingestion.get_optimal_nodes(doc)
    assert nodes
    assert all(n.metadata["splitter_id"] == "code" for n in nodes)


# ── B4c: heading provenance + splitter_profile ──────────────────────────


def test_markdown_heading_path_and_section_title(monkeypatch):
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    md = "# Cache\n## Redis\n### Avalanche\n热点 key 失效后大量请求打到数据库。\n"
    doc = Document(
        text=md, metadata={"source_kind": "user_upload", "user_id": 1, "file_name": "q.md"},
    )
    nodes = ingestion.get_optimal_nodes(doc)
    target = [n for n in nodes if "Avalanche" in n.get_content()]
    assert target, "expected a node for the ### Avalanche section"
    n = target[0]
    # header_path "/Cache/Redis/" → ancestor chain; own heading → section_title.
    assert n.metadata.get("heading_path") == ["Cache", "Redis"]
    assert n.metadata.get("section_title") == "Avalanche"


def test_plain_text_has_no_heading_annotations(monkeypatch):
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    doc = Document(
        text="just prose with no markdown headers at all",
        metadata={"source_kind": "user_upload", "user_id": 1},
    )
    nodes = ingestion.get_optimal_nodes(doc)
    assert nodes
    for n in nodes:
        assert "heading_path" not in n.metadata
        assert "section_title" not in n.metadata


def test_splitter_profile_stamped(monkeypatch):
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    doc = Document(
        text="plain prose", metadata={"source_kind": "user_upload", "user_id": 1},
    )
    nodes = ingestion.get_optimal_nodes(doc)
    assert nodes
    for n in nodes:
        sp = n.metadata["splitter_profile"]
        assert sp["chunk_size"] == 512
        assert sp["chunk_overlap"] == 64
        assert sp["tokenizer"] == "embedding"


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
