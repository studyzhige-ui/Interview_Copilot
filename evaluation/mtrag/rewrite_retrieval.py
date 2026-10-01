"""Local M3 retrieval comparison for frozen v2.1 rewrites. No API calls."""

import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from filelock import FileLock

from .download import ROOT
from .freeze_runtime import hash_file
from .m3_campaign import MANIFEST, profile
from .prepare import DOMAINS
from .profile import fingerprint
from .report import paired_comparison, summarize
from .rewrite import atomic_json
from .run import dense, lexical, queries, read_rows, rerank, score_ranking

OUT = ROOT / "retrieval-rewrite-v2.1"
RUNS = OUT / "runs"
REWRITTEN = ROOT / "rewrite-v2.1/rewritten.jsonl"
NAMES = ("bm25", "bge_m3_dense", "bm25_bge_m3", "bm25_bge_m3_rerank_bge_m3")


def config():
    p = profile()
    p["rewrite"]["prompt_version"] = "v2.1"
    p["query_modes"] = ["deepseek_rewrite"]
    # Only these two local models can be instantiated by this campaign.
    p["models"] = {k: v for k, v in p["models"].items() if k.startswith("bge_m3_")}
    return p


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def manifest():
    code = Path(__file__).parent
    paths = [
        ROOT / "tasks.jsonl",
        ROOT / "queries.jsonl",
        REWRITTEN,
        ROOT / "rewrite-v2.1/manifest.json",
        MANIFEST,
        ROOT / "optimization-m3-v1/split.json",
    ]
    paths += [
        code / name
        for name in (
            "rewrite_retrieval.py",
            "run.py",
            "local_models.py",
            "rewrite.py",
            "prompts/query_rewrite_v2_1.txt",
        )
    ]
    paths += [ROOT / "runs" / f"{name}.jsonl" for name in NAMES]
    paths += [ROOT / "vectors/bge_m3" / f"{d}.meta.json" for d in DOMAINS]
    return {
        "profile": config(),
        "files": {str(p): hash_file(p) for p in paths},
        "packages": {
            n: importlib.metadata.version(n)
            for n in ("torch", "transformers", "numpy", "scipy", "tokenizers")
        },
        "new_llm_calls": 0,
        "comparison": "same baseline retrieval; change only rewrite",
        "limitation": "Previously examined internal data; not a fresh blind evaluation",
    }


def prepare():
    if load(ROOT / "rewrite-v2.1/status.json")["state"] != "complete":
        raise ValueError("New rewrites are not complete")
    tasks = queries(config(), REWRITTEN)
    if len(tasks) != 1109:
        raise ValueError("Unexpected task coverage")
    # Verify the actual local weights/tokenizers against the frozen M3 models.
    model_manifest = load(MANIFEST)
    for model in model_manifest["models"].values():
        for relative, digest in model["sha256"].items():
            if hash_file(Path(model["source"]) / relative) != digest:
                raise ValueError(f"Model file changed: {relative}")
    for domain in DOMAINS:
        meta = load(ROOT / "vectors/bge_m3" / f"{domain}.meta.json")
        if not meta["complete"]:
            raise ValueError(f"Incomplete corpus vectors: {domain}")
    frozen = manifest()
    if (OUT / "manifest.json").exists() and load(OUT / "manifest.json") != frozen:
        raise ValueError("Campaign identity changed; preserve existing results")
    atomic_json(OUT / "manifest.json", frozen)
    atomic_json(
        OUT / "preflight.json",
        {
            "queries": len(tasks),
            "models_verified": True,
            "rewrites_verified": True,
            "new_llm_calls": 0,
            "model_paths": config()["models"],
            "gpu": __import__("torch").cuda.get_device_name(0),
        },
    )
    print(
        "Prepared 1109 queries, frozen v2.1 rewrites, two verified local M3 models",
        flush=True,
    )


def report(tasks):
    expected = {t["key"]: t for t in tasks}
    allocation = load(ROOT / "optimization-m3-v1/split.json")
    comparisons, examples = [], []
    for name in NAMES:
        current = read_rows(RUNS / f"{name}.jsonl")
        if (
            len(current) != len(expected)
            or {r["key"] for r in current} != expected.keys()
        ):
            raise ValueError(f"Incomplete or duplicate coverage: {name}")
        previous = {
            r["key"]: r
            for r in read_rows(ROOT / "runs" / f"{name}.jsonl")
            if r["key"] in expected
        }
        if previous.keys() != expected.keys():
            raise ValueError("Unpaired baseline")
        for row in current:
            if (
                score_ranking(row["ids"], expected[row["key"]]["qrels"])
                != row["metrics"]
            ):
                raise ValueError("Metric recalculation mismatch")
        for dataset in ("mtrag-human", "mtragun-human"):
            for split in ("all", "tune", "validation"):
                selected = [
                    r
                    for r in current
                    if r["dataset"] == dataset
                    and (split == "all" or allocation[r["query_id"]]["split"] == split)
                ]
                old = [previous[r["key"]] for r in selected]
                comparisons.append(
                    {
                        "stage": name,
                        "dataset": dataset,
                        "split": split,
                        "old": summarize(old),
                        "new": summarize(selected),
                        "paired": paired_comparison(old, selected),
                    }
                )
        if name == NAMES[-1]:
            for row in current:
                old = previous[row["key"]]
                examples.append(
                    {
                        "query_id": row["query_id"],
                        "query": expected[row["key"]]["query"],
                        "old_ndcg10": old["metrics"]["ndcg@10"],
                        "new_ndcg10": row["metrics"]["ndcg@10"],
                        "delta": row["metrics"]["ndcg@10"] - old["metrics"]["ndcg@10"],
                        "old_top10": old["ids"][:10],
                        "new_top10": row["ids"][:10],
                    }
                )
    atomic_json(
        OUT / "comparison.json",
        {
            "comparisons": comparisons,
            "latency_scope": "warm local retrieval only; excludes API rewriting and index/model loading",
            "latency_caveat": "Old baseline measured in previous run; hardware contention may differ",
            "new_llm_calls": 0,
            "blind_test": False,
        },
    )
    atomic_json(
        OUT / "per-query.json", {"rows": sorted(examples, key=lambda r: r["delta"])}
    )
    lines = [
        "# 新版改写 × BGE-M3 检索对照",
        "",
        "全量 1,109 题完成。BGE-M3 向量模型 + bge-reranker-v2-m3 重排；没有 LLM 调用。",
        "",
        "固定原基线：BM25/向量各50 → 等权 RRF(k=60)保留50 → M3重排 → 前10。输入预算512，重排查询预算96，batch=8。",
        "",
        "## 全量对照（领域宏平均）",
        "",
        "| 数据集 | 阶段 | 旧 nDCG@10 | 新 nDCG@10 | 旧 R@10 | 新 R@10 | 旧/新 P50(ms) | 旧/新 P95(ms) |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for c in comparisons:
        if c["split"] != "all":
            continue
        a, b = c["old"], c["new"]
        lines.append(
            f"| {c['dataset']} | {c['stage']} | {a['domain_macro']['ndcg@10']:.4f} | {b['domain_macro']['ndcg@10']:.4f} | {a['domain_macro']['recall@10']:.4f} | {b['domain_macro']['recall@10']:.4f} | {a['latency_p50_ms']:.1f}/{b['latency_p50_ms']:.1f} | {a['latency_p95_ms']:.1f}/{b['latency_p95_ms']:.1f} |"
        )
    lines += [
        "",
        "## 解释边界",
        "",
        "- 完整分领域指标、候选 Recall@50、调参集与内部验证集结果见 comparison.json。",
        "- 每题改善/退步及前十片段见 per-query.json。官方相关性标签保持不变。",
        "- 旧结果来自历史基线，延迟可能受运行时硬件负载影响；统计排除改写 API、模型加载与建索引时间。",
        "- 这批数据已经用于诊断和提示词修订，不能作为独立盲测或泛化收益证明。",
        "- 此次只重跑检索，没有答案生成，也没有自动替换生产设置。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("all", "prepare", "lexical", "dense", "rerank", "report")
    )
    args = parser.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    if args.stage == "all":
        with FileLock(str(OUT / "campaign.lock"), timeout=1):
            started = time.time()
            state = {
                "state": "running",
                "pid": os.getpid(),
                "started_at": started,
                "new_llm_calls": 0,
            }
            try:
                for stage in ("prepare", "lexical", "dense", "rerank", "report"):
                    state.update(stage=stage, updated_at=time.time())
                    atomic_json(OUT / "status.json", state)
                    print("START", stage, flush=True)
                    subprocess.run(
                        [
                            sys.executable,
                            "-X",
                            "utf8",
                            "-u",
                            "-m",
                            "evaluation.mtrag.rewrite_retrieval",
                            stage,
                        ],
                        check=True,
                    )
                    print("FINISHED", stage, flush=True)
                state.update(
                    state="complete",
                    stage="complete",
                    updated_at=time.time(),
                    elapsed_seconds=time.time() - started,
                )
            except Exception as exc:
                state.update(
                    state="failed",
                    error_type=type(exc).__name__,
                    updated_at=time.time(),
                )
                raise
            finally:
                atomic_json(OUT / "status.json", state)
        return
    if args.stage == "prepare":
        prepare()
        return
    frozen = load(OUT / "manifest.json")
    if frozen != manifest():
        raise ValueError("Frozen campaign inputs changed")
    tasks = queries(config(), REWRITTEN)
    identity = fingerprint(frozen)
    if args.stage == "lexical":
        lexical(config(), tasks, identity, run_directory=RUNS)
    elif args.stage == "dense":
        dense(config(), tasks, identity, "bge_m3", run_directory=RUNS)
    elif args.stage == "rerank":
        rerank(
            config(),
            tasks,
            identity,
            "bge_m3",
            retrievers=("bge_m3",),
            run_directory=RUNS,
        )
    else:
        report(tasks)


if __name__ == "__main__":
    main()
