"""Qwen retrieval semantics, loaded inside the broker's isolated ML child.

The query-only instruction and causal yes/no scorer preserve the local
checkpoint contract. Weight loading never occurs in the API or worker.
Reference: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
"""

from __future__ import annotations

import json
from pathlib import Path

INSTRUCTION = (
    "Given a web search query, retrieve relevant passages that answer the query"
)
QUERY_PREFIX = f"Instruct: {INSTRUCTION}\nQuery: "
RERANK_CONTRACT = "qwen3-causal-yes-no-v1"
PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on "
    'the Query and the Instruct provided. Note that the answer can only be "yes" or "no".'
    "<|im_end|>\n<|im_start|>user\n"
)
SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def is_qwen3(path: str) -> bool:
    config = Path(path) / "config.json"
    if not config.is_file():
        return False
    if config.stat().st_size > 1024 * 1024:
        raise ValueError("model_config_too_large")
    metadata = json.loads(config.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("invalid_model_config")
    return metadata.get("model_type") == "qwen3"


def embedding_query_prefix(path: str, configured: str) -> str:
    return configured or (QUERY_PREFIX if is_qwen3(path) else "")


def reranker_contract(path: str) -> str | None:
    return RERANK_CONTRACT if is_qwen3(path) else None


class Qwen3Reranker:
    def __init__(self, spec):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.max_tokens = spec.max_tokens
        self.tokenizer = AutoTokenizer.from_pretrained(
            spec.model_path,
            padding_side="left",
            local_files_only=True,
            trust_remote_code=False,
        )
        self.model = (
            AutoModelForCausalLM.from_pretrained(
                spec.model_path,
                torch_dtype=torch.bfloat16 if spec.device == "cuda" else torch.float32,
                attn_implementation="sdpa",
                local_files_only=True,
                trust_remote_code=False,
            )
            .to(spec.device)
            .eval()
        )
        if self.max_tokens > self.model.config.max_position_embeddings:
            raise ValueError("configured_tokens_exceed_model_capacity")
        self.prefix = self.tokenizer.encode(PREFIX, add_special_tokens=False)
        self.suffix = self.tokenizer.encode(SUFFIX, add_special_tokens=False)
        self.yes = self.tokenizer.convert_tokens_to_ids("yes")
        self.no = self.tokenizer.convert_tokens_to_ids("no")
        if (
            self.yes == self.no
            or self.yes == self.tokenizer.unk_token_id
            or self.no == self.tokenizer.unk_token_id
        ):
            raise ValueError("invalid_yes_no_tokens")
        if self.max_tokens <= len(self.prefix) + len(self.suffix):
            raise ValueError("qwen_template_exceeds_token_budget")

    def scores(self, query: str, texts: list[str]) -> list[float]:
        import torch
        from .errors import InputTooLong

        rendered = [
            f"<Instruct>: {INSTRUCTION}\n<Query>: {query}\n<Document>: {text}"
            for text in texts
        ]
        encoded = self.tokenizer(
            rendered,
            padding=False,
            truncation=False,
            add_special_tokens=False,
            return_attention_mask=False,
        )["input_ids"]
        rows = [self.prefix + ids + self.suffix for ids in encoded]
        if any(len(ids) > self.max_tokens for ids in rows):
            raise InputTooLong("input_exceeds_model_tokens")
        scores = []
        for start in range(0, len(rows), 8):
            inputs = self.tokenizer.pad(
                {"input_ids": rows[start : start + 8]},
                padding=True,
                return_tensors="pt",
            ).to(self.model.device)
            logits = self.model(**inputs, use_cache=False, logits_to_keep=1).logits[
                :, -1, :
            ]
            scores.extend(
                torch.softmax(logits[:, [self.no, self.yes]].float(), dim=-1)[:, 1]
                .cpu()
                .tolist()
            )
        return scores
