from app.rag.contracts import SearchIntent
from app.rag.evidence import check_evidence


def test_evidence_accepts_all_explicit_qualifiers():
    intent = SearchIntent(
        query="How does Node.js use asyncio.to_thread?",
        required_terms=["Node.js", "asyncio.to_thread"],
    )
    decision = check_evidence(
        [intent],
        ["Node.js interoperability with Python asyncio.to_thread is limited."],
    )
    assert decision.supported is True
    assert decision.missing_terms == ()


def test_evidence_rejects_only_planner_declared_missing_terms():
    intent = SearchIntent(
        query="Redis 7 eviction",
        required_terms=["Redis 7"],
    )
    decision = check_evidence([intent], ["Generic cache eviction strategies."])
    assert decision.supported is False
    assert decision.missing_terms == ("Redis 7",)


def test_evidence_has_no_implicit_product_heuristics():
    intent = SearchIntent(query="Compare Redis and Memcached")
    assert check_evidence([intent], ["No matching product text."]).supported is True
