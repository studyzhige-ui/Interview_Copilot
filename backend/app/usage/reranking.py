"""Reranker resource contracts shared by remote and in-process providers."""

from typing import Any
from pydantic import PrivateAttr
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from app.usage import runtime
from app.usage.pricing import quantities


def descriptor(provider, model, query, documents, *, destination="local"):
    tokens = (
        sum(
            len(text.encode("utf-8")) + len(query.encode("utf-8")) for text in documents
        )
        + 1024
    )
    return dict(
        meter="reranking",
        provider=provider,
        model=model,
        content={"query": query, "documents": documents, "destination": destination},
        units=quantities(
            {
                "requests": 1,
                "documents": len(documents),
                "input_tokens": tokens,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            }
        ),
        token_allowance=tokens,
    )


def observed(body, documents):
    values = {"requests": 1, "documents": documents}
    usage = body.get("usage") if isinstance(body, dict) else None
    if isinstance(usage, dict):
        # Compatible providers use prompt_tokens or total_tokens. Both are input
        # for a cross-encoder; absent usage stays estimated, not a zero claim.
        count = usage.get("prompt_tokens", usage.get("total_tokens"))
        if count is not None:
            values.update(
                input_tokens=count,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
            )
    return quantities(values)


class AccountLocalReranker(BaseNodePostprocessor):
    _inner: Any = PrivateAttr()
    usage_model: str

    def __init__(self, inner, model):
        super().__init__(usage_model=model)
        self._inner = inner

    def _postprocess_nodes(self, nodes, query_bundle=None):
        if not nodes or query_bundle is None:
            return self._inner.postprocess_nodes(nodes, query_bundle)
        documents = [n.node.get_content() for n in nodes]
        return runtime.invoke_sync(
            lambda: self._inner.postprocess_nodes(nodes, query_bundle),
            observed=lambda _: {"requests": 1, "documents": len(documents)},
            **descriptor("local", self.usage_model, query_bundle.query_str, documents),
        )
