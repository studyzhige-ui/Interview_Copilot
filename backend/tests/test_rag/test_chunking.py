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
    # Depends on the MarkdownNodeParser.header_path contract (ancestor chain,
    # "/"-joined) — pinned to llama-index-core==0.14.19.
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


def test_splitter_profile_stamped_on_table_and_code_paths(monkeypatch):
    """splitter_profile records the secondary SentenceSplitter regime and is
    stamped UNIFORMLY on every branch (table/code included) — even though those
    branches' primary splitter uses different params. splitter_id carries the
    true primary identity; this pins that documented behaviour."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))
    expected = {"chunk_size": 512, "chunk_overlap": 64, "tokenizer": "embedding",
                "qa_regex_hit": False}

    csv = Document(
        text="name,score\nalice,90\nbob,80",
        metadata={"source_kind": "user_upload", "user_id": 1, "file_name": "d.csv"},
    )
    csv_nodes = ingestion.get_optimal_nodes(csv)
    assert csv_nodes
    for n in csv_nodes:
        assert n.metadata["splitter_id"] == "table"
        assert n.metadata["splitter_profile"] == expected

    code = Document(
        text="def f():\n    return 1\n",
        metadata={"source_kind": "user_upload", "user_id": 1, "file_name": "m.py"},
    )
    code_nodes = ingestion.get_optimal_nodes(code)
    assert code_nodes
    for n in code_nodes:
        assert n.metadata["splitter_id"] == "code"
        assert n.metadata["splitter_profile"] == expected


def test_non_markdown_hash_first_line_is_not_a_section_title(monkeypatch):
    """A non-markdown chunk whose first line starts with '# ' (e.g. a Python or
    shell comment) must NOT be mistaken for a heading. Heading provenance is
    gated to the markdown splitter, so 'never guesses' holds for code/text."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    # No file_name → sentence splitter; first line is a hash-comment the bare
    # regex would otherwise capture as section_title.
    doc = Document(
        text="# TODO refactor this\nsome following prose line",
        metadata={"source_kind": "user_upload", "user_id": 1},
    )
    nodes = ingestion.get_optimal_nodes(doc)
    assert nodes
    for n in nodes:
        assert n.metadata["splitter_id"] == "sentence"
        assert "section_title" not in n.metadata
        assert "heading_path" not in n.metadata


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


# ── B4d: most-conservative QA-prefix grouping (plan §4.3 rule 2) ─────────────


def test_qa_prefix_pairs_kept_in_same_chunk(monkeypatch):
    """A plain-text question bank with paired 问题：/答案： prefixes splits at
    question boundaries, so each question stays in one chunk with its answer."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    text = (
        "问题：什么是缓存击穿？\n答案：热点 key 失效后大量请求打到数据库。\n"
        "问题：什么是缓存雪崩？\n答案：大量 key 在同一时刻集中失效。\n"
    )
    doc = Document(text=text, metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    assert len(nodes) == 2
    first = nodes[0].get_content()
    assert "缓存击穿" in first and "打到数据库" in first  # Q and its A together
    second = nodes[1].get_content()
    assert "缓存雪崩" in second and "集中失效" in second
    for n in nodes:
        assert n.metadata["splitter_id"] == "sentence"
        assert n.metadata["splitter_profile"]["qa_regex_hit"] is True


def test_qa_english_prefixes_grouped(monkeypatch):
    """The English Q:/A: form (half-width colon) triggers the same grouping."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    text = "Q: What is a B-tree?\nA: A balanced search tree.\nQ: What is a heap?\nA: A tree-based priority queue.\n"
    doc = Document(text=text, metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    assert len(nodes) == 2
    assert "B-tree" in nodes[0].get_content() and "balanced" in nodes[0].get_content()
    assert all(n.metadata["splitter_profile"]["qa_regex_hit"] is True for n in nodes)


def test_single_qa_pair_does_not_trigger_grouping(monkeypatch):
    """A lone Q/A marker (one question) is NOT treated as a bank — falls back to
    the sentence splitter so an incidental "问题：" line can't reshape a doc."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    text = "问题：只有一个问题。\n答案：所以不触发分组。"
    doc = Document(text=text, metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    assert nodes
    assert all(n.metadata["splitter_profile"]["qa_regex_hit"] is False for n in nodes)


def test_question_list_without_answers_does_not_trigger(monkeypatch):
    """Numbered/bare questions with no answer markers stay rule-3 'hint only' —
    no forced QA split (requires ≥1 answer marker)."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    text = "问题：第一题？\n问题：第二题？\n问题：第三题？\n"
    doc = Document(text=text, metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    assert nodes
    assert all(n.metadata["splitter_profile"]["qa_regex_hit"] is False for n in nodes)


def test_mid_sentence_qa_marker_does_not_trigger(monkeypatch):
    """A 问题：/答案： that appears mid-line (not at a line start) must not match
    the line-anchored regex, so ordinary prose is never reshaped."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    text = "前言里讨论了一个问题：到底是什么。后面又给出答案：其实就是这样。再次提到问题：依旧如此。"
    doc = Document(text=text, metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    assert nodes
    assert all(n.metadata["splitter_profile"]["qa_regex_hit"] is False for n in nodes)


def test_qa_preamble_kept_as_own_chunk(monkeypatch):
    """Text before the first question marker is preserved as its own leading
    chunk — QA grouping drops nothing."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    text = (
        "本文档是一份面试题库整理。\n"
        "问题：什么是索引？\n答案：加速查询的数据结构。\n"
        "问题：什么是事务？\n答案：一组原子操作。\n"
    )
    doc = Document(text=text, metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    assert len(nodes) == 3  # preamble + two Q/A groups
    assert "面试题库整理" in nodes[0].get_content()
    assert "索引" in nodes[1].get_content() and "事务" in nodes[2].get_content()
    assert all(n.metadata["splitter_profile"]["qa_regex_hit"] is True for n in nodes)


def test_qa_mixed_answer_markers_grouped(monkeypatch):
    """答案：/答：/A: all count as answer markers toward the pairing trigger."""
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: len(t.split()))

    text = "问题：甲是什么？\n答：是甲。\n问题：乙是什么？\n答案：是乙。\n"
    doc = Document(text=text, metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    assert len(nodes) == 2
    assert all(n.metadata["splitter_profile"]["qa_regex_hit"] is True for n in nodes)


def test_oversize_qa_group_routes_through_secondary_gate(monkeypatch):
    """An oversize Q/A group does not bypass the downstream oversize gate — it is
    still secondary-split, and the resulting sub-nodes keep qa_regex_hit=True."""
    # Report every node as oversize so each QA group hits the secondary splitter.
    monkeypatch.setattr(ingestion, "count_embedding_tokens", lambda t: 5000)
    calls = {"split": 0}
    real_get = ingestion.SentenceSplitter.get_nodes_from_documents

    def _counting(self, docs, **kw):
        calls["split"] += 1
        return real_get(self, docs, **kw)

    monkeypatch.setattr(ingestion.SentenceSplitter, "get_nodes_from_documents", _counting)

    text = (
        "问题：什么是缓存击穿？\n答案：热点 key 失效后大量请求打到数据库。\n"
        "问题：什么是缓存雪崩？\n答案：大量 key 在同一时刻集中失效。\n"
    )
    doc = Document(text=text, metadata={"source_kind": "user_upload", "user_id": 1})
    nodes = ingestion.get_optimal_nodes(doc)

    # _qa_aware_nodes builds TextNodes directly, so every SentenceSplitter call
    # here comes from the oversize gate re-splitting the QA groups.
    assert calls["split"] >= 1
    assert nodes
    assert all(n.metadata["splitter_profile"]["qa_regex_hit"] is True for n in nodes)
