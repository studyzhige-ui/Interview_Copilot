"""Local-only model adapters with explicit pooling, prompts and token budgets."""

import os
import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "data/evaluation/mtrag/runtime"
sys.path.insert(0, str(RUNTIME))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import numpy as np  # noqa: E402
import torch  # noqa: E402
from transformers import (  # noqa: E402
    AutoModel,
    AutoModelForCausalLM,
    AutoModelForSequenceClassification,
    AutoTokenizer,
)

torch.set_num_threads(8)
TASK = "Given a web search query, retrieve relevant passages that answer the query"
QWEN_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on "
    'the Query and the Instruct provided. Note that the answer can only be "yes" or "no".'
    "<|im_end|>\n<|im_start|>user\n"
)
QWEN_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


class LocalModel:
    def __init__(self, family, role, profile):
        self.family, self.role, self.profile = family, role, profile
        self.path = profile["models"][f"{family}_{role}"]["path"]
        self.tokenizer = AutoTokenizer.from_pretrained(self.path, local_files_only=True)
        self.tokenizer.model_max_length = 10**9  # count before our explicit truncation
        if family == "qwen":
            self.tokenizer.padding_side = "left"
        cls = (
            AutoModel
            if role == "embedding"
            else AutoModelForCausalLM
            if family == "qwen"
            else AutoModelForSequenceClassification
        )
        self.model = cls.from_pretrained(
            self.path,
            local_files_only=True,
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        self.model.to("cuda").eval()
        self.truncation = {"items": 0, "truncated": 0, "query_truncated": 0}
        if family == "qwen" and role == "reranker":
            self.prefix = self.tokenizer.encode(QWEN_PREFIX, add_special_tokens=False)
            self.suffix = self.tokenizer.encode(QWEN_SUFFIX, add_special_tokens=False)
            self.yes = self.tokenizer.convert_tokens_to_ids("yes")
            self.no = self.tokenizer.convert_tokens_to_ids("no")

    @torch.inference_mode()
    def embed(self, texts, *, query=False):
        if not query and any(not text.strip() for text in texts):
            valid = [i for i, text in enumerate(texts) if text.strip()]
            vectors = np.zeros(
                (
                    len(texts),
                    self.profile["models"][f"{self.family}_embedding"]["dimensions"],
                ),
                dtype="float32",
            )
            self.truncation["items"] += len(texts) - len(valid)
            if valid:
                vectors[valid] = self.embed([texts[i] for i in valid])
            return vectors
        if query:
            prefix = (
                f"Instruct: {TASK}\nQuery:"
                if self.family == "qwen"
                else ""
                if self.family == "bge_m3"
                else "为这个句子生成表示以用于检索相关文章："
            )
            texts = [prefix + text for text in texts]
        encoded = self.tokenizer(texts, padding=False, truncation=False)
        limit = self.profile["runtime"]["embedding_max_tokens"]
        self.truncation["items"] += len(texts)
        self.truncation["truncated"] += sum(
            len(ids) > limit for ids in encoded["input_ids"]
        )
        # Bert needs its final SEP even when the passage exceeds the budget.
        for i, ids in enumerate(encoded["input_ids"]):
            if len(ids) > limit:
                encoded["input_ids"][i] = ids[:limit]
                if self.family != "qwen":
                    encoded["input_ids"][i][-1] = self.tokenizer.sep_token_id
            for field in ("attention_mask", "token_type_ids"):
                if field in encoded:
                    encoded[field][i] = encoded[field][i][:limit]
        inputs = self.tokenizer.pad(encoded, padding=True, return_tensors="pt").to(
            "cuda"
        )
        output = self.model(**inputs, return_dict=True).last_hidden_state
        vectors = output[:, -1] if self.family == "qwen" else output[:, 0]
        vectors = torch.nn.functional.normalize(vectors.float(), dim=1)
        return vectors.cpu().numpy()

    @torch.inference_mode()
    def rerank(self, query, passages):
        limit = self.profile["runtime"]["reranker_max_tokens"]
        qlimit = self.profile["runtime"]["reranker_query_max_tokens"]
        qids = self.tokenizer.encode(query, add_special_tokens=False)
        self.truncation["query_truncated"] += int(len(qids) > qlimit) * len(passages)
        qids = qids[:qlimit]
        records = []
        for text in passages:
            if self.family == "qwen":
                shortened = self.tokenizer.decode(qids, skip_special_tokens=True)
                body = self.tokenizer.encode(
                    f"<Instruct>: {TASK}\n<Query>: {shortened}\n<Document>: {text}",
                    add_special_tokens=False,
                )
                budget = limit - len(self.prefix) - len(self.suffix)
                self.truncation["truncated"] += int(len(body) > budget)
                ids = self.prefix + body[:budget] + self.suffix
                records.append({"input_ids": ids, "attention_mask": [1] * len(ids)})
            else:
                dids = self.tokenizer.encode(text, add_special_tokens=False)
                budget = (
                    limit
                    - len(qids)
                    - self.tokenizer.num_special_tokens_to_add(pair=True)
                )
                self.truncation["truncated"] += int(len(dids) > budget)
                records.append(
                    self.tokenizer.prepare_for_model(
                        qids,
                        pair_ids=dids[:budget],
                        add_special_tokens=True,
                        return_attention_mask=True,
                        truncation=False,
                    )
                )
        self.truncation["items"] += len(passages)
        inputs = self.tokenizer.pad(records, padding=True, return_tensors="pt").to(
            "cuda"
        )
        if self.family == "qwen":
            logits = (
                self.model(**inputs, logits_to_keep=1, use_cache=False)
                .logits[:, -1]
                .float()
            )
            scores = logits[:, self.yes] - logits[:, self.no]
        else:
            scores = self.model(**inputs).logits.view(-1).float()
        return scores.cpu().numpy()


def smoke(profile):
    import gc
    import json

    for family in ("bge", "qwen"):
        for role in ("embedding", "reranker"):
            model = LocalModel(family, role, profile)
            if role == "embedding":
                vec = model.embed(
                    ["Paris is the capital of France.", "Bananas are fruit."]
                )
                q = model.embed(["What is the capital of France?"], query=True)
                scores = (q @ vec.T)[0]
                assert (
                    vec.shape[1] == profile["models"][f"{family}_{role}"]["dimensions"]
                )
                assert np.allclose(np.linalg.norm(vec, axis=1), 1, atol=1e-5)
            else:
                scores = model.rerank(
                    "What is the capital of France?",
                    ["Paris is the capital of France.", "Bananas are fruit."],
                )
            assert np.isfinite(scores).all() and scores[0] > scores[1], (
                family,
                role,
                scores,
            )
            print(
                json.dumps(
                    {
                        "model": f"{family}_{role}",
                        "scores": scores.tolist(),
                        "passed": True,
                    }
                ),
                flush=True,
            )
            del model
            gc.collect()
            torch.cuda.empty_cache()


if __name__ == "__main__":
    from .profile import load_profile

    smoke(load_profile())
