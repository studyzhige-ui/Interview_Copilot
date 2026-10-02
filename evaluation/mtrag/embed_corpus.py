"""Checkpointed full-corpus encoding, separate index per embedding model."""

import argparse
import json
import time
from pathlib import Path

from .local_models import LocalModel, np, torch
from .download import ROOT
from .prepare import DOMAINS
from .profile import fingerprint, load_profile
from .rewrite import atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", choices=["bge"], required=True)
    args = parser.parse_args()
    profile = load_profile()
    encode(profile, args.family)


def encode(profile, family):
    from types import SimpleNamespace
    from .freeze_runtime import hash_file

    args = SimpleNamespace(family=family)
    folder = ROOT / "vectors" / args.family
    folder.mkdir(parents=True, exist_ok=True)
    weight = (
        Path(profile["models"][f"{args.family}_embedding"]["path"])
        / "model.safetensors"
    )
    if not weight.exists():
        weight = weight.with_name("pytorch_model.bin")
    digest = hash_file(weight)
    model = LocalModel(args.family, "embedding", profile)
    model.embed(["Warm up the embedding model."])
    batch_size = profile["runtime"]["batch_size"]
    audit = json.loads((ROOT / "data_audit.json").read_text())
    for domain in DOMAINS:
        identity = fingerprint(
            {
                "model": digest,
                "corpus": audit["corpora"][domain]["sha256"],
                "profile": profile,
                "adapter": "local-models-v2-bf16-length-sorted",
            }
        )
        checkpoint = folder / f"{domain}.meta.json"
        info = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
        if info and info["identity"] != identity:
            raise ValueError("Existing vector cache has a different identity")
        if info.get("complete"):
            print("cached vectors", args.family, domain, flush=True)
            continue
        rows = [
            json.loads(line)
            for line in (ROOT / "corpus" / f"{domain}.jsonl").open(encoding="utf-8")
        ]
        ordering_started = time.perf_counter()
        order_path = folder / f"{domain}.order.npy"
        if order_path.exists():
            order = np.load(order_path)
        else:
            lengths = []
            for offset in range(0, len(rows), 512):
                encoded = model.tokenizer(
                    [row["text"] for row in rows[offset : offset + 512]],
                    padding=False,
                    truncation=False,
                )
                lengths.extend(
                    min(len(ids), profile["runtime"]["embedding_max_tokens"])
                    for ids in encoded["input_ids"]
                )
            order = np.argsort(lengths, kind="stable")
            with order_path.with_suffix(".tmp").open("wb") as handle:
                np.save(handle, order)
            order_path.with_suffix(".tmp").replace(order_path)
        ordering_seconds = (
            info.get("ordering_seconds", 0) + time.perf_counter() - ordering_started
        )
        output = folder / f"{domain}.npy"
        start = info.get("completed", 0)
        vectors = np.lib.format.open_memmap(
            output,
            mode="r+" if start else "w+",
            dtype="float32",
            shape=(
                len(rows),
                profile["models"][f"{args.family}_embedding"]["dimensions"],
            ),
        )
        model.truncation = info.get(
            "truncation", {"items": 0, "truncated": 0, "query_truncated": 0}
        )
        prior_seconds = info.get("seconds", 0)
        started = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        for offset in range(start, len(rows), batch_size):
            indices = order[offset : offset + batch_size]
            texts = [rows[i]["text"] for i in indices]
            vectors[indices] = model.embed(texts)
            if (
                offset == start
                or (offset // batch_size) % 100 == 0
                or offset + len(texts) == len(rows)
            ):
                vectors.flush()
                info = {
                    "identity": identity,
                    "model_sha256": digest,
                    "completed": offset + len(texts),
                    "total": len(rows),
                    "complete": offset + len(texts) == len(rows),
                    "seconds": prior_seconds + time.perf_counter() - started,
                    "ordering_seconds": ordering_seconds,
                    "batch_order": "ascending-truncated-token-length-stable",
                    "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
                    "truncation": model.truncation,
                }
                info["reserved_gpu_bytes_before_trim"] = torch.cuda.memory_reserved()
                atomic_json(checkpoint, info)
                torch.cuda.empty_cache()
                print(
                    args.family,
                    domain,
                    info["completed"],
                    "/",
                    len(rows),
                    "seconds",
                    round(info["seconds"], 1),
                    flush=True,
                )
                if (ROOT / "pause_embedding").exists():
                    print("checkpointed pause requested", flush=True)
                    return
        del vectors, rows


if __name__ == "__main__":
    main()
