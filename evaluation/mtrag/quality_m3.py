"""Evidence-driven ablations: preserve channel candidates and original-query intent.

Only retrieval/reranking. No generated answers, API calls, or rewritten cache edits.
"""

import argparse
import gc
import json
import subprocess
import sys
import time
from pathlib import Path

from .download import ROOT
from .freeze_runtime import hash_file
from .local_models import LocalModel, torch
from .m3_campaign import profile, MANIFEST
from .optimize_m3 import (
    tasks_for,
    score_passages,
    score_cache_path,
    load_json,
    macro,
    OUT as PREVIOUS,
)
from .profile import fingerprint
from .report import summarize
from .rewrite import atomic_json
from .run import corpus, read_rows, score_ranking

OUT = ROOT / "quality-m3-v1"
REPORT = Path(__file__).resolve().parents[2] / "docs/reports/mtrag-m3-quality"
VARIANTS = (
    "baseline",
    "preserve_channels",
    "add_original_retrieval",
    "add_original_rerank",
)
NAMES = ("bge_m3_dense", "bm25", "bm25_bge_m3", "bm25_bge_m3_rerank_bge_m3")


def runs():
    return {
        n: {r["key"]: r for r in read_rows(ROOT / "runs" / f"{n}.jsonl")} for n in NAMES
    }


def checkpoint(stage, key):
    folder = OUT / stage
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (fingerprint(key) + ".json")


def pools(task, results):
    key, original = task["key"], "last_turn::" + task["query_id"]
    union = set(results["bge_m3_dense"][key]["ids"] + results["bm25"][key]["ids"])
    dual = union | set(
        results["bge_m3_dense"][original]["ids"] + results["bm25"][original]["ids"]
    )
    return {
        "baseline": results["bm25_bge_m3"][key]["ids"],
        "preserve_channels": sorted(union),
        "add_original_retrieval": sorted(dual),
        "add_original_rerank": sorted(dual),
    }


def rank(ids, rewritten, original=None):
    first = sorted(ids, key=lambda pid: (-rewritten[pid], pid))
    if original is None:
        return first
    second = sorted(ids, key=lambda pid: (-original[pid], pid))
    scores = {pid: 0.75 / (60 + i) for i, pid in enumerate(first, 1)}
    for i, pid in enumerate(second, 1):
        scores[pid] += 0.25 / (60 + i)
    return sorted(ids, key=lambda pid: (-scores[pid], pid))


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "code": hash_file(Path(__file__)),
        "model_manifest": hash_file(MANIFEST),
        "split": hash_file(PREVIOUS / "split.json"),
        "source_runs": {n: hash_file(ROOT / "runs" / f"{n}.jsonl") for n in NAMES},
        "tasks": hash_file(ROOT / "tasks.jsonl"),
        "rewrites": hash_file(ROOT / "rewritten.jsonl"),
        "variants": VARIANTS,
        "tokens": 512,
        "batch": 8,
        "selection": "highest tune 8-cell macro nDCG@10, baseline wins exact ties; "
        "freeze before validation; no validation-based reselection",
        "diagnosis": hash_file(REPORT.parent / "mtrag-m3-diagnosis/trace.json"),
        "scope": "same existing internal split reused; not fresh independent validation",
    }
    # Convert tuples to their JSON representation before checking idempotence.
    manifest = json.loads(json.dumps(manifest))
    if (OUT / "manifest.json").exists() and load_json(
        OUT / "manifest.json"
    ) != manifest:
        raise ValueError("Changed quality campaign; use a new output directory")
    atomic_json(OUT / "manifest.json", manifest)
    print(
        "Prepared 3 cause-driven ablations plus baseline; no LLM API calls", flush=True
    )


def verify():
    m = load_json(OUT / "manifest.json")
    for path, digest in [
        (Path(__file__), m["code"]),
        (MANIFEST, m["model_manifest"]),
        (PREVIOUS / "split.json", m["split"]),
        (ROOT / "tasks.jsonl", m["tasks"]),
        (ROOT / "rewritten.jsonl", m["rewrites"]),
    ]:
        if hash_file(path) != digest:
            raise ValueError(f"Changed input: {path}")
    for name, digest in m["source_runs"].items():
        if hash_file(ROOT / "runs" / f"{name}.jsonl") != digest:
            raise ValueError(f"Changed source ranking: {name}")


def tune():
    results = runs()
    tasks = tasks_for("tune")
    model = LocalModel("bge_m3", "reranker", profile())
    model.rerank("warm up", ["warm up"])
    for domain in sorted({t["domain"] for t in tasks}):
        texts = {r["_id"]: r["text"] for r in corpus(domain)}
        selected = [t for t in tasks if t["domain"] == domain]
        for i, task in enumerate(selected, 1):
            path = checkpoint("tune", task["key"])
            if path.exists():
                continue
            candidates = pools(task, results)
            ids = candidates["add_original_retrieval"]
            retrieved = load_json(
                PREVIOUS / "retrieval" / (fingerprint(task["key"]) + ".json")
            )
            old_union = sorted(set(retrieved["dense"] + retrieved["bm25"]))
            rewritten = load_json(score_cache_path(task, 512, old_union))["scores"]
            missing = [pid for pid in ids if pid not in rewritten]
            if missing:
                extra, _ = score_passages(model, task["query"], missing, texts)
                rewritten.update(extra)
            if task["last_turn"] == task["query"]:
                original = rewritten
            else:
                old = results["bm25_bge_m3_rerank_bge_m3"][
                    "last_turn::" + task["query_id"]
                ]
                original = dict(zip(old["ids"], old["scores"]))
                missing = [pid for pid in ids if pid not in original]
                if missing:
                    extra, _ = score_passages(model, task["last_turn"], missing, texts)
                    original.update(extra)
            measures = {}
            for variant in VARIANTS:
                if variant == "baseline":
                    ordered = results["bm25_bge_m3_rerank_bge_m3"][task["key"]]["ids"]
                else:
                    ordered = rank(
                        candidates[variant],
                        rewritten,
                        original if variant == "add_original_rerank" else None,
                    )
                measures[variant] = {
                    "metrics": score_ranking(ordered, task["qrels"]),
                    "candidate_recall": len(
                        set(candidates[variant]) & task["qrels"].keys()
                    )
                    / len(task["qrels"]),
                    "candidate_count": len(candidates[variant]),
                }
            atomic_json(
                path,
                {
                    "key": task["key"],
                    "dataset": task["dataset"],
                    "domain": domain,
                    "variants": measures,
                },
            )
            if i == 1 or i % 25 == 0 or i == len(selected):
                print("quality tune", domain, i, "/", len(selected), flush=True)
                torch.cuda.empty_cache()
        del texts
    del model
    gc.collect()


def select():
    rows = [load_json(checkpoint("tune", t["key"])) for t in tasks_for("tune")]
    scores = {
        variant: macro(
            [{**r, "metrics": r["variants"][variant]["metrics"]} for r in rows]
        )
        for variant in VARIANTS
    }
    best = max(VARIANTS, key=lambda v: scores[v])
    frozen = {
        "chosen": best,
        "tune_macro_ndcg": scores,
        "validation_used_for_selection": False,
    }
    if (OUT / "selection.json").exists() and load_json(
        OUT / "selection.json"
    ) != frozen:
        raise ValueError("Selection already frozen")
    atomic_json(OUT / "selection.json", frozen)
    print("FROZEN", json.dumps(frozen), flush=True)


def validate():
    chosen = load_json(OUT / "selection.json")["chosen"]
    variants = list(dict.fromkeys(["baseline", chosen]))
    results, tasks = runs(), tasks_for("validation")
    model = LocalModel("bge_m3", "reranker", profile())
    model.rerank("warm up", ["warm up"])
    for domain in sorted({t["domain"] for t in tasks}):
        texts = {r["_id"]: r["text"] for r in corpus(domain)}
        selected = [t for t in tasks if t["domain"] == domain]
        for i, task in enumerate(selected, 1):
            candidate_sets = pools(task, results)
            for variant in sorted(
                variants, key=lambda v: fingerprint([task["key"], v])
            ):
                path = checkpoint("validation", [variant, task["key"]])
                if path.exists():
                    continue
                ids = candidate_sets[variant]
                rewritten, elapsed = score_passages(model, task["query"], ids, texts)
                original = None
                if variant == "add_original_rerank":
                    if task["last_turn"] == task["query"]:
                        original = rewritten
                    else:
                        original, extra = score_passages(
                            model, task["last_turn"], ids, texts
                        )
                        elapsed += extra
                started = time.perf_counter()
                ordered = rank(ids, rewritten, original)
                elapsed += (time.perf_counter() - started) * 1000
                retrieval_ms = sum(
                    results[n][task["key"]]["timings_ms"]["total"]
                    for n in ("bge_m3_dense", "bm25")
                )
                if (
                    variant.startswith("add_original")
                    and task["last_turn"] != task["query"]
                ):
                    retrieval_ms += sum(
                        results[n]["last_turn::" + task["query_id"]]["timings_ms"][
                            "total"
                        ]
                        for n in ("bge_m3_dense", "bm25")
                    )
                atomic_json(
                    path,
                    {
                        "key": task["key"],
                        "dataset": task["dataset"],
                        "domain": domain,
                        "variant": variant,
                        "ids": ordered,
                        "metrics": score_ranking(ordered, task["qrels"]),
                        "candidate_count": len(ids),
                        "candidate_recall": len(set(ids) & task["qrels"].keys())
                        / len(task["qrels"]),
                        "timings_ms": {
                            "rerank": elapsed,
                            "total": elapsed + retrieval_ms,
                        },
                    },
                )
            if i == 1 or i % 25 == 0 or i == len(selected):
                print("quality validation", domain, i, "/", len(selected), flush=True)
                torch.cuda.empty_cache()
        del texts


def report():
    frozen = load_json(OUT / "selection.json")
    chosen = frozen["chosen"]
    tasks = tasks_for("validation")
    summaries = {}
    for variant in dict.fromkeys(["baseline", chosen]):
        rows = [load_json(checkpoint("validation", [variant, t["key"]])) for t in tasks]
        for row, t in zip(rows, tasks):
            if row["metrics"] != score_ranking(row["ids"], t["qrels"]):
                raise ValueError("Metric verification failed")
        summaries[variant] = {
            d: summarize([r for r in rows if r["dataset"] == d])
            for d in profile()["datasets"]
        }
    deltas = {
        d: {
            metric: summaries[chosen][d]["domain_macro"][metric]
            - summaries["baseline"][d]["domain_macro"][metric]
            for metric in ("ndcg@10", "recall@10")
        }
        for d in profile()["datasets"]
    }
    accepted = (
        chosen != "baseline"
        and all(v >= 0 for values in deltas.values() for v in values.values())
        and any(v > 0 for values in deltas.values() for v in values.values())
    )
    REPORT.mkdir(parents=True, exist_ok=True)
    atomic_json(
        REPORT / "results.json",
        {
            "status": "complete",
            "selection": frozen,
            "validation": summaries,
            "deltas": deltas,
            "passes_quality_guardrails": accepted,
            "new_llm_calls": 0,
            "manifest": load_json(OUT / "manifest.json"),
        },
    )
    lines = [
        "# 失败归因驱动的 M3 检索质量实验",
        "",
        "状态：完成。仅检索侧，无答案生成。",
        "",
        "## 预先定义的对照",
        "",
        "- baseline：原等权融合保留50条，以改写问题重排。",
        "- preserve_channels：保留两路各50条的去重并集（最多100条），取消融合前的候选淘汰；仍用改写问题重排。",
        "- add_original_retrieval：进一步加入原问题两路各50条（最多200条）；仍用改写问题重排。",
        "- add_original_rerank：相同候选分别用改写、原问题重排，按预定75%/25%的RRF融合两次排序。",
        "- 仅调参集选择一个方案，随后与基线在原内部验证集比较；没有根据验证结果再选参数。",
        "- 调参复用已有候选对分数；验证对实际候选列表重新推理。模型、512-token长度、batch8保持固定。",
        "- 复用已有改写和召回，无新增付费调用。数据与内部验证集已多次使用，非全新盲测。",
        "",
        "## 调参结果",
        "",
        "| 对照 | 八个数据集/领域单元等权 nDCG@10 |",
        "|---|---:|",
    ]
    for variant, value in frozen["tune_macro_ndcg"].items():
        lines.append(f"| {variant} | {value:.4f} |")
    lines.extend(
        [
            "",
            f"冻结选择：{chosen}",
            "",
            "## 验证结果",
            "",
            "| 数据集 | 对照 | nDCG@10 | Recall@10 | P50 ms | P95 ms |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for d in profile()["datasets"]:
        for variant, by_dataset in summaries.items():
            s = by_dataset[d]
            lines.append(
                f"| {d} | {variant} | {s['domain_macro']['ndcg@10']:.4f} | {s['domain_macro']['recall@10']:.4f} | {s['latency_p50_ms']:.1f} | {s['latency_p95_ms']:.1f} |"
            )
    lines.extend(
        [
            "",
            f"是否通过两套数据 nDCG/Recall 均不下降的质量门槛：{accepted}。",
            "门槛通过也不等于统计显著；未通过则保留基线，不自动修改应用。",
            "耗时为新测重排与此前召回耗时相加，不包括改写、加载、生成、并发排队；候选集合构造的CPU时间未单独计入。",
            "问题到证据的逐阶段轨迹和案例见 ../mtrag-m3-diagnosis/。",
            "",
        ]
    )
    (REPORT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("COMPLETE", str(REPORT), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=["prepare", "tune", "select", "validate", "report", "all"]
    )
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare()
    elif args.stage == "all":
        for stage in ("tune", "select", "validate", "report"):
            print("START quality", stage, flush=True)
            subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "evaluation.mtrag.quality_m3",
                    stage,
                ],
                check=True,
            )
            print("FINISHED quality", stage, flush=True)
    else:
        verify()
        {"tune": tune, "select": select, "validate": validate, "report": report}[
            args.stage
        ]()


if __name__ == "__main__":
    main()
