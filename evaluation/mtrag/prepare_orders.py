"""Prepare deterministic batch orders on CPU while corpus encoding uses GPU."""

import json
import time

from .local_models import AutoTokenizer, np
from .download import ROOT
from .prepare import DOMAINS
from .profile import load_profile
from .rewrite import atomic_json


def main():
    profile = load_profile()
    for family in ("bge",):
        tokenizer = AutoTokenizer.from_pretrained(
            profile["models"][f"{family}_embedding"]["path"], local_files_only=True
        )
        tokenizer.model_max_length = 10**9
        folder = ROOT / "vectors" / family
        folder.mkdir(exist_ok=True, parents=True)
        for domain in DOMAINS:
            target = folder / f"{domain}.order.npy"
            if target.exists():
                continue
            started = time.perf_counter()
            lengths, texts = [], []
            with (ROOT / "corpus" / f"{domain}.jsonl").open(encoding="utf-8") as handle:
                for line in handle:
                    texts.append(json.loads(line)["text"])
                    if len(texts) == 512:
                        encoded = tokenizer(texts, padding=False, truncation=False)
                        lengths.extend(
                            min(len(ids), profile["runtime"]["embedding_max_tokens"])
                            for ids in encoded["input_ids"]
                        )
                        texts = []
                if texts:
                    encoded = tokenizer(texts, padding=False, truncation=False)
                    lengths.extend(
                        min(len(ids), profile["runtime"]["embedding_max_tokens"])
                        for ids in encoded["input_ids"]
                    )
            order = np.argsort(lengths, kind="stable")
            temporary = target.with_suffix(".preparing")
            with temporary.open("wb") as handle:
                np.save(handle, order)
            if not target.exists():
                temporary.replace(target)
            else:
                temporary.unlink()
            timing = {
                "family": family,
                "domain": domain,
                "seconds": time.perf_counter() - started,
                "documents": len(lengths),
                "mean_capped_tokens": float(np.mean(lengths)),
            }
            atomic_json(folder / f"{domain}.ordering.json", timing)
            print(json.dumps(timing), flush=True)


if __name__ == "__main__":
    main()
