"""Grounding allocation, budget, and citation streaming contracts."""

from app.core.tokens import token_count
from app.rag.domain.models import RetrievalResult, SearchIntent
from app.rag.grounding.builder import grounding_builder
from app.rag.grounding.citations import CitationStreamGuard, validate_citations


def test_grounding_is_coverage_first_and_budget_exact():
    result = RetrievalResult(
        intents=[
            SearchIntent(intent_id="I1", query="first", required_terms=["alpha"]),
            SearchIntent(intent_id="I2", query="second", required_terms=["beta"]),
        ],
        chunks=[
            {
                "node_id": "n1",
                "document_title": "A",
                "text": "alpha evidence",
                "intent_ids": ["I1"],
                "score": 0.95,
            },
            {
                "node_id": "n2",
                "document_title": "B",
                "text": "beta evidence",
                "intent_ids": ["I2"],
                "score": 0.90,
            },
        ],
    )

    bundle = grounding_builder.build(result, token_budget=100)

    assert bundle.supported is True
    assert bundle.covered_intent_ids == ["I1", "I2"]
    assert [source["ref"] for source in bundle.sources] == ["K1", "K2"]
    assert token_count(bundle.context_text) <= 100
    assert bundle.token_count == token_count(bundle.context_text)


def test_citation_stream_guard_handles_split_markers_without_buffering_prose():
    guard = CitationStreamGuard([{"ref": "K1"}])

    assert guard.feed("结论来自 ") == ["结论来自 "]
    assert guard.feed("[K") == []
    assert guard.feed("1]，错误引用 [K99]。") == ["[K1]，错误引用 。"]
    assert guard.flush() == ""
    report = validate_citations("结论 [K1]。", [{"ref": "K1"}], retrieval_hit=True)
    assert report.ok is True
