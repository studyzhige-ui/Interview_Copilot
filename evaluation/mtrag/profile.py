"""Explicit evaluation defaults; never import application settings or old data."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

DEFAULT_PROFILE = Path(__file__).with_name("defaults.json")


def load_profile(path: Path = DEFAULT_PROFILE) -> dict:
    profile = json.loads(path.read_text(encoding="utf-8"))
    retrieval = profile["retrieval"]
    if retrieval["min_score"] is not None or retrieval["score_margin"] is not None:
        raise ValueError("The ranking comparison must not apply score gates")
    if not (
        retrieval["per_channel_k"]
        >= retrieval["fused_k"]
        >= retrieval["rerank_k"]
        >= retrieval["output_k"]
        > 0
    ):
        raise ValueError("Invalid candidate/output budgets")
    if profile["rewrite"]["provider"] != "deepseek":
        raise ValueError("MTRAG query rewriting requires DeepSeek")
    if profile["rewrite"]["api_base"] != "https://api.deepseek.com/v1":
        raise ValueError("Use the explicit official DeepSeek endpoint")
    if profile["corpus"]["rechunk"] or not profile["corpus"]["preserve_ids"]:
        raise ValueError("Preserve official passages and qrel IDs")
    return profile


def fingerprint(value: object) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def comparison_matrix(profile: dict) -> list[dict]:
    variants = [("bm25", None)]
    for family in ("bge", "qwen"):
        variants.extend([(f"{family}_dense", None), (f"bm25_{family}", None)])
        variants.extend((f"bm25_{family}", reranker) for reranker in ("bge", "qwen"))
    return [
        {"retriever": retriever, "reranker": reranker, "query_mode": mode}
        for mode in profile["query_modes"]
        for retriever, reranker in variants
    ]


def select_ranked_passages(rows: list[dict], profile: dict) -> list[dict]:
    """Keep top-k by score; negative scores are valid, only identical IDs merge."""
    for row in rows:
        if not row.get("passage_id") or not math.isfinite(float(row["score"])):
            raise ValueError("Every result needs a passage ID and finite score")
    ranked = sorted(rows, key=lambda row: (-float(row["score"]), row["passage_id"]))
    seen: set[str] = set()
    output = []
    for row in ranked:
        if row["passage_id"] not in seen:
            output.append(row)
            seen.add(row["passage_id"])
        if len(output) >= profile["retrieval"]["output_k"]:
            break
    return output


if __name__ == "__main__":
    profile = load_profile()
    missing = [
        item["path"]
        for item in profile["models"].values()
        if not (Path(item["path"]) / "config.json").is_file()
        or not (Path(item["path"]) / "model.safetensors").is_file()
    ]
    if missing:
        raise SystemExit(f"Missing model files: {missing}")
    print(
        json.dumps(
            {
                "profile_sha256": fingerprint(profile),
                "model_files_present": True,
                "matrix": comparison_matrix(profile),
            },
            indent=2,
        )
    )
