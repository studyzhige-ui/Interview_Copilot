"""Independent nDCG@10/Recall@10 recomputation for scoped resume claims."""

import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/evaluation/mtrag"
OUT = ROOT / "docs/reports/mtrag-resume-metrics"
NAMES = ("bge_m3_dense", "bm25_bge_m3_rerank_bge_m3")


def rows(path):
    return [
        json.loads(x)
        for x in path.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]


def main():
    tasks = {r["query_id"]: r for r in rows(DATA / "tasks.jsonl")}
    per_query = []
    for name in NAMES:
        selected = [
            r
            for r in rows(DATA / "runs" / f"{name}.jsonl")
            if r["mode"] == "deepseek_rewrite"
        ]
        assert (
            len(selected) == len(tasks)
            and {r["query_id"] for r in selected} == tasks.keys()
        )
        for r in selected:
            t = tasks[r["query_id"]]
            assert len(set(r["ids"])) == len(r["ids"])
            qrels = t["qrels"]
            assert set(qrels.values()) == {
                1
            }  # binary qrels: linear and exponential gain agree
            dcg = sum(
                qrels.get(pid, 0) / math.log2(i + 2)
                for i, pid in enumerate(r["ids"][:10])
            )
            ideal = sum(1 / math.log2(i + 2) for i in range(min(10, len(qrels))))
            ndcg = dcg / ideal
            recall = len(set(r["ids"][:10]) & qrels.keys()) / len(qrels)
            assert abs(ndcg - r["metrics"]["ndcg@10"]) < 1e-12
            assert abs(recall - r["metrics"]["recall@10"]) < 1e-12
            per_query.append(
                {
                    "query_id": r["query_id"],
                    "dataset": t["dataset"],
                    "domain": t["domain"],
                    "stage": name,
                    "ndcg@10": ndcg,
                    "recall@10": recall,
                }
            )
    summary = {}
    for dataset in ("mtrag-human", "mtragun-human"):
        summary[dataset] = {}
        for stage in NAMES:
            selected = [
                r for r in per_query if r["dataset"] == dataset and r["stage"] == stage
            ]
            summary[dataset][stage] = {
                "n": len(selected),
                "query_mean": {
                    m: statistics.mean(r[m] for r in selected)
                    for m in ("ndcg@10", "recall@10")
                },
                "domain_macro": {
                    m: statistics.mean(
                        statistics.mean(r[m] for r in selected if r["domain"] == d)
                        for d in sorted({r["domain"] for r in selected})
                    )
                    for m in ("ndcg@10", "recall@10")
                },
            }
        a, b = [summary[dataset][n]["query_mean"] for n in NAMES]
        summary[dataset]["delta"] = {
            "ndcg_absolute": b["ndcg@10"] - a["ndcg@10"],
            "ndcg_relative_percent": 100 * (b["ndcg@10"] / a["ndcg@10"] - 1),
            "recall_percentage_points": 100 * (b["recall@10"] - a["recall@10"]),
        }
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [DATA / "tasks.jsonl", DATA / "rewritten.jsonl"] + [
        DATA / "runs" / f"{n}.jsonl" for n in NAMES
    ]
    (OUT / "results.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "metric_choice": "nDCG@10 chosen for ranking task, not to match an invented percentage",
                "aggregation": "query mean; domain macro also supplied to reconcile previous reports",
                "source_sha256": {
                    str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    with (OUT / "per-query.jsonl").open("w", encoding="utf-8") as handle:
        for r in per_query:
            handle.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
