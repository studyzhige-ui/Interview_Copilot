"""Thin LlamaIndex adapters to the one local broker; usage stays in app.usage."""

from __future__ import annotations

from pathlib import Path
from pydantic import PrivateAttr
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore

from app.core.config import settings
from .client import (
    Client,
    LocalInferenceNotStarted,
    LocalInferenceUnknown,
    make_request,
)
from .config import binding_for


def socket_path():
    return settings.LOCAL_INFERENCE_SOCKET or str(
        Path(settings.APP_DATA_DIR) / "inference/run/worker.sock"
    )


def _binding(role, model, dimension):
    return binding_for(
        role,
        model,
        settings.MODEL_REVISIONS_JSON.get(model),
        dimension,
        settings.LOCAL_EMBED_MAX_TOKENS
        if role == "embedding"
        else settings.RAG_RERANK_INPUT_TOKENS,
        settings.LOCAL_EMBED_QUERY_PREFIX if role == "embedding" else "",
        settings.LOCAL_EMBED_TEXT_PREFIX if role == "embedding" else "",
    )


class BrokerEmbedding(BaseEmbedding):
    _client: Client = PrivateAttr()
    _binding: str = PrivateAttr()
    dimension: int

    def __init__(self, model, dimension):
        super().__init__(
            model_name=model, dimension=dimension, embed_batch_size=16, num_workers=1
        )
        self._client = Client(
            socket_path(), timeout=settings.LOCAL_INFERENCE_TIMEOUT_SECONDS
        )
        self._binding = _binding("embedding", model, dimension)

    def _task(self, texts, query=False):
        return make_request(
            "embedding",
            self._binding,
            "query" if query else "passages",
            texts,
            priority="interactive" if query else "background",
            timeout=self._client.timeout,
        )

    def _get_query_embedding(self, query):
        return self._client.call(self._task([query], True), dimension=self.dimension)[0]

    async def _aget_query_embedding(self, query):
        return (
            await self._client.acall(
                self._task([query], True), dimension=self.dimension
            )
        )[0]

    def _get_text_embedding(self, text):
        return self._get_text_embeddings([text])[0]

    async def _aget_text_embedding(self, text):
        return (await self._aget_text_embeddings([text]))[0]

    def _get_text_embeddings(self, texts):
        return self._client.call(self._task(texts), dimension=self.dimension)

    async def _aget_text_embeddings(self, texts):
        return await self._client.acall(self._task(texts), dimension=self.dimension)


class BrokerReranker(BaseNodePostprocessor):
    _client: Client = PrivateAttr()
    _binding: str = PrivateAttr()
    top_n: int

    def __init__(self, model, top_n):
        if type(top_n) is not int or top_n < 1:
            raise ValueError("invalid_reranker_top_n")
        super().__init__(top_n=top_n)
        self._client = Client(
            socket_path(), timeout=settings.LOCAL_INFERENCE_TIMEOUT_SECONDS
        )
        self._binding = _binding("reranking", model, 1)

    def _postprocess_nodes(self, nodes, query_bundle=None):
        if not nodes:
            return []
        if query_bundle is None:
            raise ValueError("reranker_query_required")
        scores = []
        for start in range(0, len(nodes), 32):
            batch = nodes[start : start + 32]
            task = make_request(
                "reranking",
                self._binding,
                "rank",
                [n.node.get_content() for n in batch],
                query=query_bundle.query_str,
                timeout=self._client.timeout,
            )
            try:
                scores.extend(self._client.call(task, dimension=1))
            except LocalInferenceNotStarted:
                if scores:
                    # The aggregate usage reservation covers all batches. Once
                    # one batch ran, a later admission rejection cannot refund
                    # the entire operation or trigger an invisible fallback.
                    raise LocalInferenceUnknown("partial_local_reranking") from None
                raise
        ranked = [
            NodeWithScore(node=node.node, score=score)
            for node, score in zip(nodes, scores, strict=True)
        ]
        return sorted(ranked, key=lambda node: node.score, reverse=True)[: self.top_n]
