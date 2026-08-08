"""Tests for ``RemoteAPIRerank``'s raise contract.

An unusable response raises ``RerankerUnavailableError``. The retriever can
then fail closed instead of either mixing RRF and cross-encoder scales or
letting uncalibrated candidates reach the answer context.
"""

from __future__ import annotations

import pytest
from app.rag import reranker_registry
from app.rag.reranker_registry import RemoteAPIRerank, RerankerUnavailableError
from llama_index.core import QueryBundle
from llama_index.core.schema import NodeWithScore, TextNode


def _nodes(*texts: str) -> list[NodeWithScore]:
    return [
        NodeWithScore(node=TextNode(text=t, id_=f"n{i}"), score=0.03)
        for i, t in enumerate(texts)
    ]


def _reranker() -> RemoteAPIRerank:
    return RemoteAPIRerank(
        api_base="https://rerank.example",
        api_key="k",
        model="test-model",
        top_n=5,
    )


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


class _FakeClient:
    """Stands in for ``httpx.Client`` — returns a canned body or raises."""

    body: dict | None = None
    exc: Exception | None = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def post(self, url, json=None, headers=None):
        if self.exc is not None:
            raise self.exc
        return _FakeResponse(self.body or {})


@pytest.fixture
def fake_http(monkeypatch):
    monkeypatch.setattr(reranker_registry.httpx, "Client", _FakeClient)
    yield _FakeClient
    _FakeClient.body = None
    _FakeClient.exc = None


def test_transport_error_raises(fake_http):
    fake_http.exc = ConnectionError("upstream down")

    with pytest.raises(RerankerUnavailableError):
        _reranker()._postprocess_nodes(_nodes("a", "b"), QueryBundle("q"))


def test_empty_results_raises(fake_http):
    fake_http.body = {"results": []}

    with pytest.raises(RerankerUnavailableError):
        _reranker()._postprocess_nodes(_nodes("a", "b"), QueryBundle("q"))


def test_unusable_indices_raise(fake_http):
    fake_http.body = {"results": [{"index": 99, "relevance_score": 0.9}]}

    with pytest.raises(RerankerUnavailableError):
        _reranker()._postprocess_nodes(_nodes("a", "b"), QueryBundle("q"))


def test_happy_path_reorders_by_provider_ranking(fake_http):
    fake_http.body = {
        "results": [
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.4},
        ]
    }

    out = _reranker()._postprocess_nodes(_nodes("first", "second"), QueryBundle("q"))

    assert [n.node.get_content() for n in out] == ["second", "first"]
    assert out[0].score == pytest.approx(0.9)


def test_dashscope_wrapped_results_shape(fake_http):
    fake_http.body = {"output": {"results": [{"index": 0, "score": 0.7}]}}

    out = _reranker()._postprocess_nodes(_nodes("only"), QueryBundle("q"))

    assert len(out) == 1
    assert out[0].score == pytest.approx(0.7)
