"""Meter the physical embedding SDK request before LlamaIndex drops usage.

These subclasses use the extension points of the pinned LlamaIndex OpenAI
embedding implementations. Tests assert both synchronous and asynchronous
batch paths; no monkeypatching of SDKs or global callbacks is involved.
"""

from __future__ import annotations

from typing import Any
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.embeddings.openai_like import OpenAILikeEmbedding
from llama_index.core.base.embeddings.base import BaseEmbedding
from pydantic import PrivateAttr

from app.usage import runtime
from app.usage.pricing import quantities


def _descriptor(provider, model, payload, destination):
    value = payload.get("input")
    texts = [value] if isinstance(value, str) else value
    if not isinstance(texts, list) or not texts:
        raise ValueError("embedding_input_required")
    if all(type(x) is int for x in texts):
        texts = [texts]
    count = 0
    for text in texts:
        if isinstance(text, str):
            count += len(text.encode("utf-8"))
        elif isinstance(text, list) and all(type(x) is int and x >= 0 for x in text):
            count += len(text)
        else:
            raise ValueError("invalid_embedding_input")
    units = quantities(
        {
            "requests": 1,
            "documents": len(texts),
            "input_tokens": count,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
    )
    return dict(
        meter="embedding",
        provider=provider,
        model=model,
        content={"payload": payload, "destination": destination},
        units=units,
        token_allowance=count,
    )


def _observed(response, documents):
    usage = getattr(response, "usage", None)
    value = (
        usage.get("prompt_tokens")
        if isinstance(usage, dict)
        else getattr(usage, "prompt_tokens", None)
    )
    if value is None:
        return None
    return quantities(
        {
            "requests": 1,
            "documents": documents,
            "input_tokens": value,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
    )


class _EmbeddingCalls:
    def __init__(self, endpoint, provider, destination, asynchronous=False):
        self.endpoint, self.provider, self.destination = endpoint, provider, destination
        self.asynchronous = asynchronous

    def create(self, **payload):
        desc = _descriptor(self.provider, payload["model"], payload, self.destination)

        def measured(response):
            return _observed(response, desc["units"]["documents"])

        if self.asynchronous:
            return runtime.invoke_async(
                lambda: self.endpoint.create(**payload), observed=measured, **desc
            )
        return runtime.invoke_sync(
            lambda: self.endpoint.create(**payload), observed=measured, **desc
        )


class _EmbeddingClient:
    def __init__(self, client, provider, asynchronous=False):
        self._client = client
        self.embeddings = _EmbeddingCalls(
            client.embeddings, provider, str(client.base_url), asynchronous
        )

    def __getattr__(self, name):
        return getattr(self._client, name)


class AccountOpenAIEmbedding(OpenAIEmbedding):
    usage_provider: str = "openai"

    def _get_client(self):
        return _EmbeddingClient(super()._get_client(), self.usage_provider)

    def _get_aclient(self):
        return _EmbeddingClient(super()._get_aclient(), self.usage_provider, True)


class AccountOpenAILikeEmbedding(OpenAILikeEmbedding):
    usage_provider: str

    def _get_client(self):
        return _EmbeddingClient(super()._get_client(), self.usage_provider)

    def _get_aclient(self):
        return _EmbeddingClient(super()._get_aclient(), self.usage_provider, True)


class AccountLocalEmbedding(BaseEmbedding):
    """Count local resource work; a zero vendor price must be explicit policy."""

    _inner: Any = PrivateAttr()

    def __init__(self, inner, model):
        super().__init__(
            model_name=model, embed_batch_size=inner.embed_batch_size, num_workers=1
        )
        self._inner = inner

    def _get_query_embedding(self, query):
        desc = _descriptor("local", self.model_name, {"input": [query]}, "local")
        return runtime.invoke_sync(
            lambda: self._inner.get_query_embedding(query), **desc
        )

    async def _aget_query_embedding(self, query):
        import asyncio

        return await asyncio.to_thread(self._get_query_embedding, query)

    def _get_text_embedding(self, text):
        return self._get_text_embeddings([text])[0]

    def _get_text_embeddings(self, texts):
        desc = _descriptor("local", self.model_name, {"input": texts}, "local")
        return runtime.invoke_sync(
            lambda: self._inner.get_text_embedding_batch(texts), **desc
        )

    async def _aget_text_embedding(self, text):
        import asyncio

        return await asyncio.to_thread(self._get_text_embedding, text)

    async def _aget_text_embeddings(self, texts):
        import asyncio

        return await asyncio.to_thread(self._get_text_embeddings, texts)
