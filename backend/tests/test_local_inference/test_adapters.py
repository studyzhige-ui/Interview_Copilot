from dataclasses import replace
from types import SimpleNamespace
import sys

import pytest

from app.local_inference import child
from app.local_inference.rag import BrokerEmbedding, BrokerReranker
from app.core.config import settings
from app.rag.embedding_registry import build_embedding
from app.rag.reranker_registry import build_reranker
from app.usage import runtime
from app.usage.embedding import AccountLocalEmbedding
from llama_index.core import QueryBundle
from llama_index.core.schema import TextNode, NodeWithScore


def test_factories_create_proxies_not_gpu_models(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
    monkeypatch.setattr(settings, "RERANKER_PROVIDER", "local")
    assert isinstance(build_embedding()._inner, BrokerEmbedding)
    assert isinstance(build_reranker(2)._inner, BrokerReranker)


def test_binding_changes_index_identity(monkeypatch):
    from app.rag.index.identity import current_index_identity

    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
    before = current_index_identity()
    monkeypatch.setattr(settings, "LOCAL_EMBED_QUERY_PREFIX", "Retrieve: ")
    assert current_index_identity().fingerprint != before.fingerprint


async def test_usage_wraps_native_async_client(monkeypatch):
    calls = []

    class Inner:
        embed_batch_size = 16

        async def aget_query_embedding(self, query):
            calls.append(query)
            return [1.0, 0.0]

        async def aget_text_embedding_batch(self, texts):
            calls.extend(texts)
            return [[1.0, 0.0] for _ in texts]

    async def invoke(call, **desc):
        assert desc["meter"] == "embedding" and desc["provider"] == "local"
        return await call()

    monkeypatch.setattr(runtime, "invoke_async", invoke)
    model = AccountLocalEmbedding(Inner(), "test")
    assert await model._aget_query_embedding("q") == [1.0, 0.0]
    assert await model._aget_text_embeddings(["a", "b"]) == [[1.0, 0.0], [1.0, 0.0]]
    assert calls == ["q", "a", "b"]


def test_proxy_rank_keeps_node_identity_and_does_not_clamp(monkeypatch):
    model = BrokerReranker("test", 2)
    sent = []

    def call(task, **_):
        sent.append(task)
        return [-3.0, 0.7, 2.0]

    monkeypatch.setattr(model._client, "call", call)
    nodes = [NodeWithScore(node=TextNode(id_=str(i), text=f"doc{i}")) for i in range(3)]
    ranked = model.postprocess_nodes(nodes, QueryBundle("question"))
    assert [node.node.node_id for node in ranked] == ["2", "1"]
    assert [node.score for node in ranked] == [2.0, 0.7]
    assert sent[0]["query"] == "question"


@pytest.fixture
def fake_torch(monkeypatch):
    class Inference:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=Inference))


def test_real_adapter_checks_tokens_before_inference(specs, fake_torch):
    model = SimpleNamespace(
        tokenizer=lambda *args, **kwargs: {"input_ids": [[1] * 33]},
        encode=lambda *args, **kwargs: pytest.fail("must not truncate and encode"),
    )
    spec = specs[0]
    from .conftest import task

    with pytest.raises(child.InputTooLong):
        child.infer(model, spec, task(spec))


def test_embedding_uses_explicit_prompt_and_normalization(specs, fake_torch):
    from .conftest import task

    seen = {}

    def encode(texts, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(tolist=lambda: [[1.0, 0.0, 0.0]])

    model = SimpleNamespace(
        tokenizer=lambda *a, **k: {"input_ids": [[1, 2]]}, encode=encode
    )
    spec = replace(specs[0], query_prefix="Search: ")
    assert child.infer(model, spec, task(spec)) == [[1.0, 0.0, 0.0]]
    assert seen["prompt"] == "Search: " and seen["normalize_embeddings"] is True


def test_setup_uses_existing_weights_without_loading_models(config, monkeypatch):
    from scripts.prepare_local_inference import build_config
    from app.core.model_assets import ModelInspection

    monkeypatch.setattr(
        "scripts.prepare_local_inference.inspect_model",
        lambda model_id, **kwargs: ModelInspection(
            model_id, config.models[0].model_path, "structurally_valid", "transformers"
        ),
    )
    from pathlib import Path

    result = build_config(
        python=sys.executable,
        device="cpu",
        runtime_dir=Path(config.socket_path).parent,
        model_root=Path(config.models[0].model_path),
        cache_root=Path(config.cache_root),
    )
    assert len(result.models) == 2
    assert result.models[1].max_tokens == settings.RAG_RERANK_INPUT_TOKENS
    assert result.models[0].model_path == config.models[0].model_path


def test_late_batch_rejection_does_not_refund_completed_work(monkeypatch):
    from app.local_inference.client import (
        LocalInferenceNotStarted,
        LocalInferenceUnknown,
    )

    model = BrokerReranker("test", 2)
    count = 0

    def call(req, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return [1.0] * 32
        raise LocalInferenceNotStarted("queue_full")

    monkeypatch.setattr(model._client, "call", call)
    nodes = [
        NodeWithScore(node=TextNode(id_=str(i), text=f"doc{i}")) for i in range(33)
    ]
    with pytest.raises(LocalInferenceUnknown):
        model.postprocess_nodes(nodes, QueryBundle("q"))
    assert count == 2
