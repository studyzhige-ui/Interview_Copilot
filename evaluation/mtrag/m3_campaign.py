"""Add the project's BGE M3 models without invalidating the original campaign."""

import argparse
import gc
import json
import subprocess
import sys
from pathlib import Path

from .download import ROOT
from .freeze_runtime import hash_file
from .local_models import LocalModel, np, torch
from .profile import fingerprint, load_profile
from .rewrite import atomic_json

PROJECT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "m3-manifest.json"


def profile():
    p = load_profile()
    p["models"]["bge_m3_embedding"] = {
        "path": str(PROJECT / "data/cache/models/BAAI--bge-m3"),
        "dimensions": 1024,
    }
    p["models"]["bge_m3_reranker"] = {
        "path": str(PROJECT / "data/cache/models/BAAI--bge-reranker-v2-m3")
    }
    return p


def prepare():
    from .run import campaign_identity

    p = profile()
    files = {}
    for role, name in (("embedding", "bge-m3"), ("reranker", "bge-reranker-v2-m3")):
        source = Path(p["models"][f"bge_m3_{role}"]["path"])
        destination = Path("D:/Models/BAAI") / name
        hashes = {}
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            copied = destination / relative
            digest = hash_file(path)
            if not copied.is_file() or hash_file(copied) != digest:
                raise ValueError(f"Copy verification failed: {copied}")
            hashes[relative.as_posix()] = digest
        files[name] = {
            "source": str(source),
            "copy": str(destination),
            "sha256": hashes,
            "all_copied_files_verified": True,
        }
    manifest = {
        "profile": p,
        "baseline_identity": campaign_identity(load_profile()),
        "models": files,
        "adapter_version": "m3-cls-normalized-no-query-prefix-v1",
        "scope": "dense M3 embeddings; same 512-token budget; no sparse or ColBERT heads",
    }
    if (
        MANIFEST.exists()
        and json.loads(MANIFEST.read_text(encoding="utf-8")) != manifest
    ):
        raise ValueError("M3 manifest changed; use a separate campaign")
    atomic_json(MANIFEST, manifest)
    for role in ("embedding", "reranker"):
        model = LocalModel("bge_m3", role, p)
        passages = ["Paris is the capital of France.", "Bananas are fruit."]
        if role == "embedding":
            vectors = model.embed(passages)
            query = model.embed(["What is the capital of France?"], query=True)
            assert vectors.shape == (2, 1024)
            assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
            scores = (query @ vectors.T)[0]
        else:
            scores = model.rerank("What is the capital of France?", passages)
        if not np.isfinite(scores).all() or scores[0] <= scores[1]:
            raise ValueError(f"M3 smoke check failed: {role}: {scores}")
        print("M3 smoke passed", role, scores.tolist(), flush=True)
        del model
        gc.collect()
        torch.cuda.empty_cache()
    print("Copies verified; both project M3 models passed GPU inference", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=[
            "prepare",
            "encode",
            "dense",
            "rerank-m3",
            "rerank-qwen",
            "report",
            "all",
        ],
    )
    args = parser.parse_args()
    if args.stage == "all":
        for stage in ("encode", "dense", "rerank-m3", "rerank-qwen", "report"):
            print("START M3", stage, flush=True)
            subprocess.run(
                [sys.executable, "-m", "evaluation.mtrag.m3_campaign", stage],
                check=True,
            )
            print("FINISHED M3", stage, flush=True)
        return
    if args.stage == "prepare":
        prepare()
        return
    p = profile()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["profile"] != p:
        raise ValueError("Prepared profile differs from active profile")
    from .run import campaign_identity, dense, queries, rerank

    if campaign_identity(load_profile()) != manifest["baseline_identity"]:
        raise ValueError("Baseline inputs changed; cannot reuse old results")
    identity = fingerprint(manifest)
    if args.stage == "encode":
        from .embed_corpus import encode

        encode(p, "bge_m3")
    elif args.stage == "dense":
        dense(p, queries(p), identity, "bge_m3")
    elif args.stage == "rerank-m3":
        rerank(p, queries(p), identity, "bge_m3", retrievers=("bge_m3", "qwen"))
    elif args.stage == "rerank-qwen":
        rerank(
            p,
            queries(p),
            identity,
            "qwen",
            retrievers=("bge_m3",),
            runtime_name="qwen-on-m3-rerank-runtime.json",
        )
    else:
        from .m3_report import main as report

        report()


if __name__ == "__main__":
    main()
