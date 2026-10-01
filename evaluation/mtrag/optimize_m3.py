"""Offline, resumable M3 tuning with conversation-disjoint internal validation.

No network calls. Validation is evaluated only after train-only selection is frozen.
"""

import argparse
import copy
import gc
import json
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from .download import ROOT
from .freeze_runtime import hash_file
from .local_models import LocalModel, np, torch
from .m3_campaign import MANIFEST, profile
from .prepare import DOMAINS
from .profile import fingerprint
from .report import summarize
from .rewrite import atomic_json
from .run import BM25, corpus, queries, read_rows, score_ranking, topk

OUT = ROOT / "optimization-m3-v1"
SEED = "m3-optimization-2026-v1"
BASELINE = {
    "name": "baseline",
    "channel_k": 50,
    "dense_weight": 0.5,
    "rerank_k": 50,
    "tokens": 512,
}
FAST = {
    "name": "fast_dense",
    "channel_k": 100,
    "dense_weight": 1.0,
    "rerank_k": 0,
    "tokens": 512,
}


def grid():
    return [BASELINE, FAST] + [
        {
            "name": f"w{weight}-k{k}-t{tokens}",
            "channel_k": 100,
            "dense_weight": weight,
            "rerank_k": k,
            "tokens": tokens,
        }
        for weight in (0.5, 0.75, 1.0)
        for k in (20, 30, 50, 100)
        for tokens in (512, 1024)
    ]


def split_tasks(tasks):
    """Connected components join entire conversations and cross-dataset duplicate inputs."""
    parent = {t["query_id"]: t["query_id"] for t in tasks}

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def join(a, b):
        a, b = root(a), root(b)
        parent[max(a, b)] = min(a, b)

    conversations, inputs = {}, {}
    for task in tasks:
        key = task["query_id"]
        conversation = (task["dataset"], task["conversation_id"])
        if conversation in conversations:
            join(key, conversations[conversation])
        if task["input_sha256"] in inputs:
            join(key, inputs[task["input_sha256"]])
        conversations[conversation] = key
        inputs[task["input_sha256"]] = key
    components = defaultdict(list)
    for task in tasks:
        components[root(task["query_id"])].append(task)
    strata = defaultdict(list)
    for group, members in components.items():
        # Mixed dataset components remain inseparable and receive their own stratum.
        stratum = tuple(sorted({(t["dataset"], t["domain"]) for t in members}))
        strata[stratum].append(group)
    allocation = {}
    for groups in strata.values():
        groups.sort(key=lambda g: fingerprint([SEED, g]))
        boundary = (
            max(1, min(len(groups) - 1, round(0.6 * len(groups))))
            if len(groups) > 1
            else 1
        )
        allocation.update(
            {g: "tune" if i < boundary else "validation" for i, g in enumerate(groups)}
        )
    return {
        t["query_id"]: {
            "split": allocation[root(t["query_id"])],
            "group": root(t["query_id"]),
        }
        for t in tasks
    }


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def tasks_for(split=None):
    tasks = [t for t in queries(profile()) if t["mode"] == "deepseek_rewrite"]
    allocation = load_json(OUT / "split.json")
    return [
        {**t, **allocation[t["query_id"]]}
        for t in tasks
        if split is None or allocation[t["query_id"]]["split"] == split
    ]


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = [t for t in queries(profile()) if t["mode"] == "deepseek_rewrite"]
    allocation = split_tasks(tasks)
    counts = Counter(
        (allocation[t["query_id"]]["split"], t["dataset"], t["domain"]) for t in tasks
    )
    if len(counts) != 16:
        raise ValueError("Every dataset/domain must occur in both splits")
    manifest = {
        "seed": SEED,
        "m3_manifest_sha256": hash_file(MANIFEST),
        "inputs": {
            name: hash_file(ROOT / name)
            for name in (
                "tasks.jsonl",
                "queries.jsonl",
                "rewritten.jsonl",
                "runtime_manifest.json",
            )
        },
        "vector_metadata": {
            d: hash_file(ROOT / "vectors/bge_m3" / f"{d}.meta.json") for d in DOMAINS
        },
        "grid": grid(),
        "split": allocation,
        "split_counts": {"/".join(k): v for k, v in counts.items()},
        "selection": "equal mean over two datasets and four domains of tune nDCG@10; "
        "quality=best reranked; balanced=best reranked with k<=30 and tokens=512; "
        "ties prefer shorter inputs, fewer candidates, then name",
        "embedding_tokens": 512,
        "rewrite": "frozen existing cache; zero API calls",
        "code_sha256": hash_file(Path(__file__)),
        "limitations": "Previously evaluated data; internal validation, not unseen blind test. "
        "Only reranker length is tuned; embedding stays at 512 tokens.",
    }
    if (OUT / "manifest.json").exists() and load_json(
        OUT / "manifest.json"
    ) != manifest:
        raise ValueError(
            "Optimization manifest changed; preserve this run and use a new directory"
        )
    atomic_json(OUT / "manifest.json", manifest)
    atomic_json(OUT / "split.json", allocation)
    # Explicit leakage audit, including transitive duplicate-conversation links.
    for field in ("input_sha256",):
        tune = {t[field] for t in tasks if allocation[t["query_id"]]["split"] == "tune"}
        validation = {
            t[field]
            for t in tasks
            if allocation[t["query_id"]]["split"] == "validation"
        }
        assert not tune & validation
    atomic_json(
        OUT / "split-audit.json",
        {
            "duplicate_input_overlap": 0,
            "counts": manifest["split_counts"],
            "groups": len({a["group"] for a in allocation.values()}),
        },
    )
    print(json.dumps(manifest["split_counts"]), flush=True)


def verify_manifest():
    m = load_json(OUT / "manifest.json")
    if hash_file(Path(__file__)) != m["code_sha256"] or grid() != m["grid"]:
        raise ValueError("Optimization code/config changed after split freeze")
    if hash_file(MANIFEST) != m["m3_manifest_sha256"]:
        raise ValueError("Models/profile changed")
    for name, digest in m["inputs"].items():
        if hash_file(ROOT / name) != digest:
            raise ValueError(f"Input changed: {name}")


def row_path(stage, key):
    folder = OUT / stage
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (fingerprint(key) + ".json")


def retrieve():
    p = profile()
    tasks = tasks_for()
    model = LocalModel("bge_m3", "embedding", p)
    model.embed(["warm up"], query=True)
    torch.backends.cuda.matmul.allow_tf32 = False
    for domain in DOMAINS:
        pending = [
            t
            for t in tasks
            if t["domain"] == domain and not row_path("retrieval", t["key"]).exists()
        ]
        if not pending:
            continue
        rows = corpus(domain)
        empty = np.array([not r["text"].strip() for r in rows])
        meta_path = ROOT / "vectors/bge_m3" / f"{domain}.meta.json"
        if (
            hash_file(meta_path)
            != load_json(OUT / "manifest.json")["vector_metadata"][domain]
        ):
            raise ValueError("Vector metadata changed")
        array = np.load(ROOT / "vectors/bge_m3" / f"{domain}.npy")
        if array.shape != (len(rows), 1024) or not np.isfinite(array).all():
            raise ValueError("Invalid M3 vectors")
        vectors = torch.from_numpy(array).to("cuda")
        lexical = BM25(rows, k1=1.2, b=0.75)
        lexical.search("warm up")
        for index, task in enumerate(pending, 1):
            torch.cuda.synchronize()
            started = time.perf_counter()
            q = torch.from_numpy(model.embed([task["query"]], query=True)).to("cuda")
            values = (vectors @ q[0]).cpu().numpy()
            values[empty] = -np.inf
            dense_ids = [rows[i]["_id"] for i in topk(values, 100)]
            dense_ms = 1000 * (time.perf_counter() - started)
            started = time.perf_counter()
            values = lexical.search(task["query"])
            lexical_ids = [rows[i]["_id"] for i in topk(values, 100, positive=True)]
            lexical_ms = 1000 * (time.perf_counter() - started)
            atomic_json(
                row_path("retrieval", task["key"]),
                {
                    "key": task["key"],
                    "dense": dense_ids,
                    "bm25": lexical_ids,
                    "dense_ms": dense_ms,
                    "bm25_ms": lexical_ms,
                },
            )
            if index % 50 == 0 or index == len(pending):
                print("retrieve", domain, index, "/", len(pending), flush=True)
        del rows, vectors, array, lexical
        gc.collect()
        torch.cuda.empty_cache()


def candidates(retrieved, config):
    if config["dense_weight"] == 1.0:
        return retrieved["dense"][: config["rerank_k"] or 10]
    scores = defaultdict(float)
    for channel, weight in (
        ("dense", config["dense_weight"]),
        ("bm25", 1 - config["dense_weight"]),
    ):
        for rank, pid in enumerate(retrieved[channel][: config["channel_k"]], 1):
            scores[pid] += weight / (60 + rank)
    return sorted(scores, key=lambda pid: (-scores[pid], pid))[: config["rerank_k"]]


def score_passages(model, query, ids, texts):
    ids = sorted(ids, key=lambda pid: (len(texts[pid]), pid))
    torch.cuda.synchronize()
    started = time.perf_counter()
    scores = []
    for offset in range(0, len(ids), 8):
        scores.extend(
            model.rerank(
                query, [texts[pid] for pid in ids[offset : offset + 8]]
            ).tolist()
        )
    if not np.isfinite(scores).all():
        raise ValueError("Non-finite M3 reranker output")
    return dict(zip(ids, scores)), 1000 * (time.perf_counter() - started)


def score_cache_path(task, length, ids):
    return row_path(
        f"tune-scores-{length}", [task["domain"], task["query"], sorted(ids)]
    )


def tune_scores():
    tasks = tasks_for("tune")
    for length in (512, 1024):
        p = copy.deepcopy(profile())
        p["runtime"]["reranker_max_tokens"] = length
        model = LocalModel("bge_m3", "reranker", p)
        model.rerank("warm up", ["warm up"])
        for domain in DOMAINS:
            texts = {r["_id"]: r["text"] for r in corpus(domain)}
            selected = [t for t in tasks if t["domain"] == domain]
            for index, task in enumerate(selected, 1):
                retrieved = load_json(row_path("retrieval", task["key"]))
                # This union covers every predefined config; no qrels enter scoring.
                ids = sorted(set(retrieved["dense"] + retrieved["bm25"]))
                path = score_cache_path(task, length, ids)
                if not path.exists():
                    scores, elapsed = score_passages(model, task["query"], ids, texts)
                    atomic_json(path, {"scores": scores, "elapsed_ms": elapsed})
                if index % 25 == 0 or index == len(selected):
                    print(
                        "tune-scores",
                        length,
                        domain,
                        index,
                        "/",
                        len(selected),
                        flush=True,
                    )
                    torch.cuda.empty_cache()
            del texts
        del model
        gc.collect()
        torch.cuda.empty_cache()


def macro(rows):
    cells = defaultdict(list)
    for row in rows:
        cells[(row["dataset"], row["domain"])].append(row["metrics"]["ndcg@10"])
    if len(cells) != 8:
        raise ValueError("Missing dataset/domain cell")
    return statistics.mean(statistics.mean(values) for values in cells.values())


def select():
    tasks = tasks_for("tune")
    configurations = grid()
    by_config = defaultdict(list)
    for task in tasks:
        retrieved = load_json(row_path("retrieval", task["key"]))
        union = sorted(set(retrieved["dense"] + retrieved["bm25"]))
        scores = {
            length: load_json(score_cache_path(task, length, union))["scores"]
            for length in (512, 1024)
        }
        for config in configurations:
            ids = candidates(retrieved, config)
            if config["rerank_k"]:
                ids = sorted(ids, key=lambda pid: (-scores[config["tokens"]][pid], pid))
            by_config[config["name"]].append(
                {
                    "key": task["key"],
                    "dataset": task["dataset"],
                    "domain": task["domain"],
                    "metrics": score_ranking(ids, task["qrels"]),
                    "timings_ms": {"total": 0},
                }
            )
    ranking = sorted(
        configurations,
        key=lambda c: (
            -macro(by_config[c["name"]]),
            c["tokens"],
            c["rerank_k"],
            c["name"],
        ),
    )
    quality = next(c for c in ranking if c["rerank_k"])
    balanced = next(
        c for c in ranking if 0 < c["rerank_k"] <= 30 and c["tokens"] == 512
    )
    frozen = {
        "baseline": BASELINE,
        "quality": quality,
        "balanced": balanced,
        "fast": FAST,
        "selection_split": "tune",
        "validation_used_for_selection": False,
    }
    if (OUT / "selection.json").exists() and load_json(
        OUT / "selection.json"
    ) != frozen:
        raise ValueError("Selection differs from frozen selection")
    atomic_json(OUT / "selection.json", frozen)
    atomic_json(
        OUT / "tuning-results.json",
        [
            {
                "config": c,
                "macro_ndcg": macro(by_config[c["name"]]),
                "by_dataset": {
                    d: summarize([r for r in by_config[c["name"]] if r["dataset"] == d])
                    for d in profile()["datasets"]
                },
            }
            for c in ranking
        ],
    )
    print("FROZEN selection", json.dumps(frozen), flush=True)


def validate():
    selection = load_json(OUT / "selection.json")
    tasks = tasks_for("validation")
    configs = {
        fingerprint(selection[label]): selection[label]
        for label in ("baseline", "quality", "balanced", "fast")
    }
    for length in sorted({c["tokens"] for c in configs.values()}):
        p = copy.deepcopy(profile())
        p["runtime"]["reranker_max_tokens"] = length
        model = LocalModel("bge_m3", "reranker", p)
        model.rerank("warm up", ["warm up"])
        for domain in DOMAINS:
            texts = {r["_id"]: r["text"] for r in corpus(domain)}
            domain_tasks = [t for t in tasks if t["domain"] == domain]
            for index, task in enumerate(domain_tasks, 1):
                retrieved = load_json(row_path("retrieval", task["key"]))
                ordered = sorted(
                    ((key, c) for key, c in configs.items() if c["tokens"] == length),
                    key=lambda item: fingerprint([task["key"], item[0]]),
                )
                for config_key, config in ordered:
                    path = row_path("validation", [config_key, task["key"]])
                    if path.exists():
                        continue
                    started = time.perf_counter()
                    ids = candidates(retrieved, config)
                    fuse_ms = 1000 * (time.perf_counter() - started)
                    rerank_ms = 0.0
                    if config["rerank_k"]:
                        scores, rerank_ms = score_passages(
                            model, task["query"], ids, texts
                        )
                        ids = sorted(ids, key=lambda pid: (-scores[pid], pid))
                    total = retrieved["dense_ms"] + fuse_ms + rerank_ms
                    if config["dense_weight"] < 1:
                        total += retrieved["bm25_ms"]
                    atomic_json(
                        path,
                        {
                            "key": task["key"],
                            "query_id": task["query_id"],
                            "dataset": task["dataset"],
                            "domain": domain,
                            "group": task["group"],
                            "config": config,
                            "ids": ids,
                            "metrics": score_ranking(ids, task["qrels"]),
                            "timings_ms": {"rerank": rerank_ms, "total": total},
                            "note": "actual fresh candidate-list inference; retrieval timed separately at top100",
                        },
                    )
                if index % 25 == 0 or index == len(domain_tasks):
                    print(
                        "validation",
                        length,
                        domain,
                        index,
                        "/",
                        len(domain_tasks),
                        flush=True,
                    )
                    torch.cuda.empty_cache()
            del texts
        del model
        gc.collect()
        torch.cuda.empty_cache()


def report():
    selection = load_json(OUT / "selection.json")
    tasks = tasks_for("validation")
    rows_by_label = {}
    for label in ("baseline", "quality", "balanced", "fast"):
        key = fingerprint(selection[label])
        rows = [load_json(row_path("validation", [key, t["key"]])) for t in tasks]
        for row, task in zip(rows, tasks):
            if row["metrics"] != score_ranking(row["ids"], task["qrels"]):
                raise ValueError("Validation metric mismatch")
        rows_by_label[label] = rows
    summaries = {
        label: {
            dataset: summarize([r for r in rows if r["dataset"] == dataset])
            for dataset in profile()["datasets"]
        }
        for label, rows in rows_by_label.items()
    }
    # Preserve matched per-query changes; do not select a different config on validation.
    paired = {}
    for label in ("quality", "balanced", "fast"):
        deltas = [
            b["metrics"]["ndcg@10"] - a["metrics"]["ndcg@10"]
            for a, b in zip(rows_by_label["baseline"], rows_by_label[label])
        ]
        paired[label] = {
            "improved": sum(d > 1e-12 for d in deltas),
            "unchanged": sum(abs(d) <= 1e-12 for d in deltas),
            "regressed": sum(d < -1e-12 for d in deltas),
            "macro_ndcg_delta": macro(rows_by_label[label])
            - macro(rows_by_label["baseline"]),
        }
    # Rewrite regression inspection is restricted to tune tasks, without new API calls.
    old = {
        r["key"]: r for r in read_rows(ROOT / "runs/bm25_bge_m3_rerank_bge_m3.jsonl")
    }
    regressions = []
    for task in tasks_for("tune"):
        before = old["last_turn::" + task["query_id"]]["metrics"]["ndcg@10"]
        after = old[task["key"]]["metrics"]["ndcg@10"]
        if after < before:
            regressions.append(
                {
                    "query_id": task["query_id"],
                    "last_turn": task["last_turn"],
                    "rewritten": task["query"],
                    "ndcg_delta": after - before,
                }
            )
    regressions.sort(key=lambda r: r["ndcg_delta"])
    result = {
        "status": "complete",
        "selection": selection,
        "validation": summaries,
        "paired_changes": paired,
        "split_audit": load_json(OUT / "split-audit.json"),
        "manifest": load_json(OUT / "manifest.json"),
        "new_llm_calls": 0,
    }
    folder = Path(__file__).resolve().parents[2] / "docs/reports/mtrag-m3-optimization"
    folder.mkdir(parents=True, exist_ok=True)
    atomic_json(folder / "results.json", result)
    atomic_json(folder / "rewrite-regressions-tune.json", regressions)
    lines = [
        "# BGE-M3 检索优化实验",
        "",
        "状态：完成；配置仅由调参集选择，验证集随后一次比较。",
        "",
        "## 范围与方法",
        "",
        "- 固定项目 BGE-M3 和 bge-reranker-v2-m3，复用 DeepSeek 缓存，新增调用0。",
        "- 完整对话分组，跨数据集相同输入合并连通组后划分；约60%调参、40%验证。",
        "- 这些数据此前已经评测过，本轮属于内部验证，不能当作全新盲测。",
        "- 调参目标：两套数据、四领域等权 nDCG@10；配置在查看验证分数前冻结。",
        "- 探索纯向量与加权RRF（向量占比50%/75%/100%），重排20/30/50/100，重排长度512/1024。",
        "- 向量索引仍为512 tokens；本轮长度实验仅针对重排。RRF常数60，输出10，BF16，batch8。",
        "- 调参共享候选对分数，避免重复计算；验证重新推理实际候选列表并计时。",
        "- 延迟为分阶段相加，召回按每通道top100计时；不含改写、加载、答案生成及线上并发排队。",
        "- 本轮baseline重新实测；不要与此前全量数据上的平均指标直接比较。",
        "",
        "## 已冻结配置",
        "",
        "| 方案 | 每通道召回 | 向量权重 | 重排条数 | 重排tokens |",
        "|---|---:|---:|---:|---:|",
    ]
    for label in ("baseline", "quality", "balanced", "fast"):
        c = selection[label]
        lines.append(
            f"| {label} | {c['channel_k']} | {c['dense_weight']} | {c['rerank_k']} | {c['tokens']} |"
        )
    lines.extend(
        [
            "",
            "## 验证结果",
            "",
            "| 数据集 | 方案 | nDCG@10 | Recall@10 | P50 ms | P95 ms |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for dataset in profile()["datasets"]:
        for label in ("baseline", "quality", "balanced", "fast"):
            s = summaries[label][dataset]
            m = s["domain_macro"]
            lines.append(
                f"| {dataset} | {label} | {m['ndcg@10']:.4f} | {m['recall@10']:.4f} | {s['latency_p50_ms']:.1f} | {s['latency_p95_ms']:.1f} |"
            )
    lines.extend(["", "## 是否实际提升", ""])
    for label, p in paired.items():
        lines.append(
            f"- {label}：验证 nDCG@10 宏平均变化 {p['macro_ndcg_delta']:+.4f}；逐题改善/持平/退步 "
            f"{p['improved']}/{p['unchanged']}/{p['regressed']}。"
        )
    lines.extend(
        [
            "",
            "提升不是预设结果；若验证退步，应保留基线，不能继续依据验证集挑参数。"
            "未做统计显著性检验。英文、正例任务范围不变，不评价拒答和答案质量。",
            "",
            "调参集改写退步案例见 rewrite-regressions-tune.json；未自动修改改写提示词。",
            "",
        ]
    )
    (folder / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("COMPLETE", str(folder), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=["prepare", "retrieve", "tune", "select", "validate", "report", "all"],
    )
    args = parser.parse_args()
    if args.stage == "all":
        for stage in ("retrieve", "tune", "select", "validate", "report"):
            print("START optimize", stage, flush=True)
            subprocess.run(
                [sys.executable, "-m", "evaluation.mtrag.optimize_m3", stage],
                check=True,
            )
            print("FINISHED optimize", stage, flush=True)
    elif args.stage == "prepare":
        prepare()
    else:
        verify_manifest()
        {
            "retrieve": retrieve,
            "tune": tune_scores,
            "select": select,
            "validate": validate,
            "report": report,
        }[args.stage]()


if __name__ == "__main__":
    main()
