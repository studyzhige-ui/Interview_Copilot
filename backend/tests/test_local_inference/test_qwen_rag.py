"""Migrated Qwen semantics across the real broker/configuration seams."""

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.local_inference import child
from app.local_inference.config import ModelSpec, binding_for
from app.local_inference.qwen_rag import (
    INSTRUCTION,
    QUERY_PREFIX,
    Qwen3Reranker,
    RERANK_CONTRACT,
)


@pytest.fixture
def qwen_spec(tmp_path):
    import sys

    (tmp_path / "config.json").write_text(
        json.dumps({"model_type": "qwen3"}), encoding="utf-8"
    )
    return ModelSpec(
        "embedding",
        "fixture-qwen",
        str(tmp_path),
        sys.executable,
        dimension=3,
        max_tokens=100,
    )


def test_embedding_query_only_prompt_matches_api_and_index(qwen_spec, monkeypatch):
    from app.local_inference.rag import _binding
    from app.rag.index.identity import current_index_identity

    monkeypatch.setattr(
        "app.core.hf_runtime.resolve_local_snapshot", lambda _: qwen_spec.model_path
    )
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", qwen_spec.model_id)
    monkeypatch.setattr(settings, "EMBEDDING_DIM", qwen_spec.dimension)
    monkeypatch.setattr(settings, "LOCAL_EMBED_MAX_TOKENS", qwen_spec.max_tokens)
    monkeypatch.setattr(settings, "LOCAL_EMBED_QUERY_PREFIX", "")
    monkeypatch.setattr(settings, "LOCAL_EMBED_TEXT_PREFIX", "")
    assert qwen_spec.query_prefix == QUERY_PREFIX
    assert qwen_spec.text_prefix == ""
    assert _binding("embedding", qwen_spec.model_id, 3) == qwen_spec.binding
    before = current_index_identity().fingerprint
    monkeypatch.setattr(settings, "LOCAL_EMBED_QUERY_PREFIX", "Custom: ")
    assert current_index_identity().fingerprint != before
    assert replace(qwen_spec, query_prefix="Custom: ").query_prefix == "Custom: "


def test_causal_scorer_has_distinct_matching_binding(qwen_spec, monkeypatch):
    from app.local_inference.rag import _binding

    spec = replace(qwen_spec, role="reranking", dimension=1, query_prefix="")
    monkeypatch.setattr(
        "app.core.hf_runtime.resolve_local_snapshot", lambda _: spec.model_path
    )
    monkeypatch.setattr(settings, "RAG_RERANK_INPUT_TOKENS", spec.max_tokens)
    assert spec.binding == _binding("reranking", spec.model_id, 1)
    assert spec.binding != binding_for("reranking", spec.model_id, None, 1, 100)
    assert spec.binding == binding_for(
        "reranking", spec.model_id, None, 1, 100, adapter_contract=RERANK_CONTRACT
    )


def test_loader_selects_causal_adapter_without_classifier_head(qwen_spec, monkeypatch):
    from app.local_inference import qwen_rag

    spec = replace(qwen_spec, role="reranking", dimension=1, query_prefix="")
    selected = object()
    monkeypatch.setattr(
        qwen_rag, "Qwen3Reranker", lambda actual: selected if actual == spec else None
    )
    assert child.load_model(spec) is selected


@pytest.fixture
def scorer(qwen_spec, monkeypatch):
    import sys
    import numpy as np

    # Exercise the adapter contract without installing GPU libraries in API tests.
    class Tensor(np.ndarray):
        def float(self):
            return self.astype(np.float32)

        def cpu(self):
            return self

    def tensor(value):
        return np.asarray(value).view(Tensor)

    def softmax(value, dim):
        weights = np.exp(value - np.max(value, axis=dim, keepdims=True))
        return tensor(weights / weights.sum(axis=dim, keepdims=True))

    torch = SimpleNamespace(
        bfloat16="bfloat16",
        float32="float32",
        tensor=tensor,
        zeros=lambda shape: tensor(np.zeros(shape)),
        softmax=softmax,
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    seen = {}

    class Inputs(dict):
        def to(self, device):
            return self

    class Tokenizer:
        unk_token_id = -1

        def encode(self, text, **kwargs):
            return [3, 4]

        def convert_tokens_to_ids(self, text):
            return {"yes": 1, "no": 0}[text]

        def __call__(self, texts, **kwargs):
            seen["texts"] = texts
            seen["tokenizer_args"] = kwargs
            return {
                "input_ids": [
                    [1 if "<Document>: relevant" in text else 0] * 4 for text in texts
                ]
            }

        def pad(self, encoded, **kwargs):
            return Inputs(input_ids=torch.tensor(encoded["input_ids"]))

    class Model:
        device = "cpu"
        config = SimpleNamespace(max_position_embeddings=32768)

        def to(self, device):
            return self

        def eval(self):
            return self

        def __call__(self, input_ids, **kwargs):
            seen["model_args"] = kwargs
            logits = torch.zeros((len(input_ids), 1, 2))
            for i, ids in enumerate(input_ids):
                logits[i, 0, 1] = 3 if ids[2] else -3
            return SimpleNamespace(logits=logits)

    def load_model(*args, **kwargs):
        seen["load_args"] = kwargs
        return Model()

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a, **kw: Tokenizer()),
            AutoModelForCausalLM=SimpleNamespace(from_pretrained=load_model),
        ),
    )
    spec = replace(qwen_spec, role="reranking", dimension=1, query_prefix="")
    return Qwen3Reranker(spec), seen


def test_yes_no_probabilities_and_template_are_preserved(scorer):
    model, seen = scorer
    scores = model.scores("question", ["other", "relevant"])
    assert scores[0] < 0.1 and scores[1] > 0.9
    assert INSTRUCTION in seen["texts"][0]
    assert "<Query>: question" in seen["texts"][0]
    assert seen["tokenizer_args"]["truncation"] is False
    assert seen["model_args"] == {"use_cache": False, "logits_to_keep": 1}
    assert seen["load_args"]["local_files_only"] is True
    assert seen["load_args"]["trust_remote_code"] is False


def test_template_tokens_count_toward_budget_before_inference(scorer):
    model, seen = scorer
    model.max_tokens = 7
    with pytest.raises(child.InputTooLong):
        model.scores("question", ["relevant"])
    assert "model_args" not in seen
