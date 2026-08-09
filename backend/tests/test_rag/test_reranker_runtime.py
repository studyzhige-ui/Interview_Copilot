from __future__ import annotations

from app.rag.reranker_registry import _warm_local_reranker


def test_local_reranker_is_warmed_with_a_real_forward_pass() -> None:
    calls = []

    class FakeReranker:
        def postprocess_nodes(self, nodes, query_bundle):
            calls.append((nodes, query_bundle))
            return nodes

    _warm_local_reranker(FakeReranker())

    assert len(calls) == 1
    nodes, query_bundle = calls[0]
    assert len(nodes) == 2
    assert query_bundle.query_str == "retrieval evidence"
