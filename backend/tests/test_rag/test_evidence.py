from app.rag.domain.models import SearchIntent
from app.rag.grounding.evidence import missing_terms_by_intent


def _missing(intent: SearchIntent, text: str) -> list[str]:
    return missing_terms_by_intent(
        [intent],
        [{"text": text, "intent_ids": [intent.intent_id]}],
    )


def test_evidence_accepts_all_explicit_qualifiers():
    intent = SearchIntent(
        intent_id="I1",
        query="How does Node.js use asyncio.to_thread?",
        required_terms=["Node.js", "asyncio.to_thread"],
    )
    missing = _missing(
        intent,
        "Node.js interoperability with Python asyncio.to_thread is limited.",
    )
    assert missing == []


def test_evidence_rejects_only_planner_declared_missing_terms():
    intent = SearchIntent(
        intent_id="I1",
        query="Redis 7 eviction",
        required_terms=["Redis 7"],
    )
    assert _missing(intent, "Generic cache eviction strategies.") == ["Redis 7"]


def test_evidence_has_no_implicit_product_heuristics():
    intent = SearchIntent(intent_id="I1", query="Compare Redis and Memcached")
    assert _missing(intent, "No matching product text.") == []
