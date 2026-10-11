"""Canonical retrieval: rank fusion, tenant scope and model identity boundaries."""

import pytest
from app.rag.retrieval.fusion import reciprocal_rank_fusion
from app.rag.retrieval.candidates import _in_scope


def test_fusion_uses_ranks_and_deduplicates_text_not_provider_score_scales():
    first = [
        {"id": "a", "text": "Alpha", "score": -100},
        {"id": "b", "text": "Beta", "score": 999},
    ]
    second = [
        {"id": "b", "text": "Beta", "score": 0.01},
        {"id": "c", "text": " ALPHA ", "score": 0.99},
    ]
    rows = reciprocal_rank_fusion([first, second], weights=[1, 1], rrf_k=60, limit=10)
    assert rows[0]["id"] == "b" and len(rows) == 2


@pytest.mark.parametrize(
    "owner,kind,documents,expected",
    [
        (1, "knowledge", set(), True),
        (2, "knowledge", set(), False),
        (1, "chat_attachment", set(), False),
        (1, "chat_attachment", {"doc"}, True),
        (1, "knowledge", {"different"}, False),
    ],
)
def test_candidate_scope_never_expands_from_attachment_to_global(
    owner, kind, documents, expected
):
    row = {"user_id": owner, "source_kind": kind, "document_id": "doc"}
    assert (
        _in_scope(row, user_pk=1, source_kind=None, document_ids=documents) is expected
    )
