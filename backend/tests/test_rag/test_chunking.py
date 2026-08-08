"""Unified structure-aware chunking tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.rag.chunking as chunking
from app.rag.documents import CanonicalDocument, PageSpan
from app.rag.retrieval_text import build_retrieval_text


def _document(
    text: str,
    kind: str = "text",
    *,
    spans: list[PageSpan] | None = None,
) -> CanonicalDocument:
    return CanonicalDocument(
        text=text,
        content_kind=kind,
        page_spans=spans or [],
        parser_id="fixture",
        parser_profile={"tier": "test"},
        cleaning_profile={"char_out": len(text)},
    )


@pytest.fixture
def small_policy(monkeypatch):
    tokens = SimpleNamespace(chunk_target=64, chunk_overlap=8, passage_limit=96)
    monkeypatch.setattr(
        chunking,
        "current_rag_policy",
        lambda: SimpleNamespace(tokens=tokens),
    )
    return tokens


def _chunks(document, *, title="Fixture"):
    return chunking.chunk_document(
        document,
        metadata={
            "file_name": "fixture.txt",
            "source_kind": "user_upload",
            "user_id": 1,
        },
        document_title=title,
    )


@pytest.mark.parametrize(
    ("kind", "splitter_id"),
    [
        ("table", "table"),
        ("markdown", "markdown"),
        ("json", "json"),
        ("code", "code"),
        ("text", "sentence"),
        ("unknown", "sentence"),
    ],
)
def test_splitter_selection_uses_parser_semantics(kind, splitter_id):
    assert chunking.select_splitter(kind).id == splitter_id


def test_every_chunk_gets_one_provenance_contract(small_policy):
    nodes = _chunks(_document("Redis prevents repeated database reads."))
    assert nodes
    metadata = nodes[0].metadata
    assert metadata["splitter_id"] == "sentence"
    assert metadata["parser_id"] == "fixture"
    assert metadata["cleaning_profile"] == {"char_out": 39}
    assert metadata["token_count"] == chunking.count_tokens(nodes[0].text)
    assert metadata["splitter_profile"]["chunk_target"] == 64


def test_markdown_keeps_heading_context(small_policy):
    markdown = "# Cache\n## Redis\n### Avalanche\nRandomize expiry times."
    nodes = _chunks(_document(markdown, "markdown"))
    target = next(node for node in nodes if "Avalanche" in node.text)
    assert target.metadata["heading_path"] == ["Cache", "Redis"]
    assert target.metadata["section_title"] == "Avalanche"


def test_normalized_table_records_are_not_duplicated(small_policy):
    text = "name: Alice | score: 90\nname: Bob | score: 80"
    nodes = _chunks(_document(text, "table"))
    combined = "\n".join(node.text for node in nodes)
    assert combined.count("name: Alice") == 1
    assert combined.count("name: Bob") == 1
    assert all(node.metadata["chunk_type"] == "table" for node in nodes)


def test_code_uses_language_parser(small_policy):
    document = _document("def answer():\n    return 42\n", "code")
    nodes = chunking.chunk_document(
        document,
        metadata={
            "file_name": "answer.py",
            "source_kind": "user_upload",
            "user_id": 1,
        },
    )
    assert nodes
    assert all(node.metadata["splitter_id"] == "code" for node in nodes)


def test_final_gate_obeys_embedding_and_reranker_budgets(small_policy):
    text = " ".join(f"token{i}" for i in range(400))
    nodes = _chunks(_document(text), title="Long technical document")
    assert len(nodes) > 1
    for node in nodes:
        assert chunking.count_tokens(node.text) <= small_policy.chunk_target
        retrieval_text = build_retrieval_text(
            node.text,
            document_title="Long technical document",
            section_title=node.metadata.get("section_title"),
            heading_path=node.metadata.get("heading_path"),
        )
        assert chunking.count_tokens(retrieval_text) <= small_policy.passage_limit


def test_page_provenance_follows_canonical_offsets(small_policy):
    text = "first page answer\n\nsecond page answer"
    boundary = len("first page answer")
    document = _document(
        text,
        spans=[
            PageSpan(1, 0, boundary),
            PageSpan(2, boundary + 2, len(text)),
        ],
    )
    nodes = _chunks(document)
    assert nodes[0].metadata["page_start"] == 1
    assert nodes[0].metadata["page_end"] == 2


def test_qa_bank_keeps_question_answer_pairs(small_policy):
    text = "Q: What is Redis?\nA: A data store.\nQ: What is TTL?\nA: Expiry."
    nodes = _chunks(_document(text))
    assert nodes[0].metadata["splitter_profile"]["qa_regex_hit"] is True
    assert all("Q:" in node.text for node in nodes)
