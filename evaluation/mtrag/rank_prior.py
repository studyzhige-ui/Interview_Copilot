"""Fixed-pool retrieval-prior experiment. No LLM calls or new model inference."""

from collections import Counter
import json
from pathlib import Path
import re
import time

from .download import ROOT
from .freeze_runtime import hash_file
from .m3_campaign import MANIFEST
from .optimize_m3 import tasks_for, OUT as PREVIOUS
from .report import paired_comparison, summarize
from .rewrite import atomic_json
from .run import corpus, read_rows, score_ranking

OUT = ROOT / "rank-prior-v1"
REPORT = Path(__file__).resolve().parents[2] / "docs/reports/mtrag-rank-prior"
WEIGHTS = {"baseline": 0.0, "prior10": 0.10, "prior25": 0.25}
NAMES = ("bm25_bge_m3", "bm25_bge_m3_rerank_bge_m3")


def rank(prior, reranked, weight):
    if (
        len(prior) != len(set(prior))
        or set(prior) != set(reranked)
        or len(prior) != len(reranked)
    ):
        raise ValueError(
            "Prior and reranker must use exactly the same unique candidates"
        )
    if weight == 0:
        return list(reranked)
    scores = {pid: (1 - weight) / (60 + i) for i, pid in enumerate(reranked, 1)}
    for i, pid in enumerate(prior, 1):
        scores[pid] += weight / (60 + i)
    return sorted(scores, key=lambda pid: (-scores[pid], pid))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    paths = [
        Path(__file__),
        MANIFEST,
        ROOT / "queries.jsonl",
        ROOT / "rewritten.jsonl",
        ROOT / "tasks.jsonl",
        PREVIOUS / "split.json",
    ]
    paths += [ROOT / "runs" / f"{n}.jsonl" for n in NAMES]
    manifest = {
        "inputs": {str(p): hash_file(p) for p in paths},
        "weights": WEIGHTS,
        "query": "original v1 cached rewrites",
        "pool": "original fused50",
        "tokens": 512,
        "selection": "tune only; highest equal dataset/domain macro nDCG among variants with no dataset nDCG or Recall@10 loss; baseline wins ties",
        "acceptance": "validation both datasets nDCG@10 and Recall@10 nondecreasing, at least one improves",
        "limitation": "Reused internal split, not independent blind validation",
        "new_llm_calls": 0,
    }
    path = OUT / "manifest.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Experiment changed")
    atomic_json(path, manifest)
    tasks = tasks_for()
    runs = {
        n: {r["key"]: r for r in read_rows(ROOT / "runs" / f"{n}.jsonl")} for n in NAMES
    }
    original = {t["key"]: runs[NAMES[1]][t["key"]] for t in tasks}

    # Evidence audit: exact text-equivalence is diagnostic only, never relabel qrels.
    failures, audit_counts = [], Counter()
    for domain in sorted({t["domain"] for t in tasks}):
        selected = [
            t
            for t in tasks
            if t["domain"] == domain
            and not set(original[t["key"]]["ids"][:10]) & set(t["qrels"])
            and set(runs[NAMES[0]][t["key"]]["ids"]) & set(t["qrels"])
        ]
        needed = {
            pid
            for t in selected
            for pid in list(t["qrels"]) + original[t["key"]]["ids"][:10]
        }
        docs = {r["_id"]: r["text"] for r in corpus(domain) if r["_id"] in needed}

        def normalize(text):
            return re.sub(r"\s+", " ", text).strip()

        for t in selected:
            key = t["key"]
            gold = set(t["qrels"])
            prior, after = runs[NAMES[0]][key]["ids"], original[key]["ids"]
            exact = [
                pid
                for pid in after[:10]
                if normalize(docs[pid]) in {normalize(docs[g]) for g in gold}
            ]
            rescued_by_prior = sorted(gold & set(prior[:10]))
            audit_counts["zero_hit_rerank_queries"] += 1
            audit_counts["exact_positive_text_in_top10"] += bool(exact)
            audit_counts["positive_in_prior_top10"] += bool(rescued_by_prior)
            failures.append(
                {
                    "query_id": t["query_id"],
                    "query": t["query"],
                    "domain": domain,
                    "split": t["split"],
                    "exact_equivalent_ids": exact,
                    "prior_top10_positive": rescued_by_prior,
                    "passages": [
                        {
                            "id": pid,
                            "text": docs[pid],
                            "gold": pid in gold,
                            "prior_rank": prior.index(pid) + 1
                            if pid in prior
                            else None,
                            "rerank_rank": after.index(pid) + 1
                            if pid in after
                            else None,
                        }
                        for pid in dict.fromkeys(list(t["qrels"]) + after[:3])
                    ],
                }
            )
    atomic_json(
        REPORT / "zero-hit-evidence.json",
        {
            "counts": audit_counts,
            "review_scope": "100 cases exported; exact text matches automated; semantic review not complete",
            "rows": failures,
        },
    )

    def evaluate(chosen_tasks, variants):
        output = {v: [] for v in variants}
        for t in chosen_tasks:
            base = original[t["key"]]
            for v in variants:
                started = time.perf_counter()
                ordered = rank(runs[NAMES[0]][t["key"]]["ids"], base["ids"], WEIGHTS[v])
                extra_ms = (
                    (time.perf_counter() - started) * 1000 if v != "baseline" else 0.0
                )
                output[v].append(
                    {
                        **base,
                        "ids": ordered,
                        "top10_ids": ordered[:10],
                        "metrics": score_ranking(ordered, t["qrels"]),
                        "timings_ms": {
                            "historical_retrieval_rerank": base["timings_ms"]["total"],
                            "rank_fusion": extra_ms,
                            "total": base["timings_ms"]["total"] + extra_ms,
                        },
                    }
                )
        return output

    def summaries(output):
        return {
            v: {
                d: summarize([r for r in rs if r["dataset"] == d])
                for d in ("mtrag-human", "mtragun-human")
            }
            for v, rs in output.items()
        }

    tune = evaluate([t for t in tasks if t["split"] == "tune"], list(WEIGHTS))
    tune_summary = summaries(tune)
    eligible = [
        v
        for v in WEIGHTS
        if all(
            tune_summary[v][d]["domain_macro"][m]
            >= tune_summary["baseline"][d]["domain_macro"][m] - 1e-12
            for d in tune_summary[v]
            for m in ("ndcg@10", "recall@10")
        )
    ]
    chosen = max(
        eligible,
        key=lambda v: (
            sum(tune_summary[v][d]["domain_macro"]["ndcg@10"] for d in tune_summary[v])
            / 2
        ),
    )
    selection = {"chosen": chosen, "eligible": eligible, "tune": tune_summary}
    selected_path = OUT / "selection.json"
    if (
        selected_path.exists()
        and json.loads(selected_path.read_text(encoding="utf-8")) != selection
    ):
        # Runtime estimates fluctuate; selection and metric summaries must not change.
        previous = json.loads(selected_path.read_text(encoding="utf-8"))
        if previous["chosen"] != chosen or previous["eligible"] != eligible:
            raise ValueError("Frozen selection changed")
    else:
        atomic_json(selected_path, selection)
    # Only after the selection is frozen, score the chosen variant on internal validation.
    validation = evaluate(
        [t for t in tasks if t["split"] == "validation"],
        list(dict.fromkeys(["baseline", chosen])),
    )
    validation_summary = summaries(validation)
    paired = {
        d: paired_comparison(
            [r for r in validation["baseline"] if r["dataset"] == d],
            [r for r in validation[chosen] if r["dataset"] == d],
        )
        for d in tune_summary["baseline"]
    }
    deltas = {
        d: {
            m: validation_summary[chosen][d]["domain_macro"][m]
            - validation_summary["baseline"][d]["domain_macro"][m]
            for m in ("ndcg@10", "recall@10")
        }
        for d in paired
    }
    accepted = (
        chosen != "baseline"
        and all(x >= -1e-12 for d in deltas.values() for x in d.values())
        and any(x > 1e-12 for d in deltas.values() for x in d.values())
    )
    result = {
        "status": "complete",
        "selection": selection,
        "validation": validation_summary,
        "paired": paired,
        "deltas": deltas,
        "passes_guardrails": accepted,
        "evidence_audit": audit_counts,
        "latency": "historical baseline latency plus measured CPU fusion; not fresh end-to-end measurement",
        "new_llm_calls": 0,
        "fresh_blind_test": False,
    }
    atomic_json(REPORT / "results.json", result)
    atomic_json(OUT / "validation-rankings.json", validation)
    lines = [
        "# 原检索排名与 M3 重排融合实验",
        "",
        "固定v1改写、两个M3模型、原融合50候选、512输入。假设：重排完全覆盖原检索排序时，会丢掉有价值的召回排名信号。",
        "",
        "实验只将原融合排名以10%或25%权重加入最终排名，重排占90%或75%，两者以常数60做加权RRF。没有加入未消解的原问题，也没有新增候选。",
        "",
        f"零命中证据审计：{json.dumps(audit_counts)}。语义人工复核未覆盖全部100题，未修改标签。",
        "",
        "## 调参集",
        "",
        "| 方案 | Human nDCG / Recall@10 | UN nDCG / Recall@10 |",
        "|---|---|---|",
    ]
    for v, ds in tune_summary.items():
        a, b = [ds[d]["domain_macro"] for d in ("mtrag-human", "mtragun-human")]
        lines.append(
            f"| {v} | {a['ndcg@10']:.4f} / {a['recall@10']:.4f} | {b['ndcg@10']:.4f} / {b['recall@10']:.4f} |"
        )
    lines += [
        "",
        f"调参后冻结选择：{chosen}。",
        "",
        "## 内部验证",
        "",
        "| 数据集 | 方案 | nDCG@10 | Recall@10 |",
        "|---|---|---:|---:|",
    ]
    for v, ds in validation_summary.items():
        for d, s in ds.items():
            lines.append(
                f"| {d} | {v} | {s['domain_macro']['ndcg@10']:.4f} | {s['domain_macro']['recall@10']:.4f} |"
            )
    lines += [
        "",
        f"通过预设双数据集质量门槛：{accepted}。",
        "",
        "不通过则继续保留基线；不根据验证结果换选其他权重。通过也只表示已有数据回归通过，不代表独立泛化或显著性。",
        "延迟为历史检索/重排时间加本轮CPU融合时间，不能冒充新测端到端延迟。未修改应用配置。",
        "",
    ]
    (REPORT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "chosen": chosen,
                "passes_guardrails": accepted,
                "deltas": deltas,
                "audit": audit_counts,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
