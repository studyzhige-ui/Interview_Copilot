"""Materialize the already-selected ranking policy; no tuning or model calls."""

import json
import time

from .download import ROOT
from .freeze_runtime import hash_file
from .m3_campaign import profile
from .optimize_m3 import tasks_for
from .rank_prior import OUT, REPORT, NAMES, WEIGHTS, rank
from .report import paired_comparison, summarize, percentile
from .rewrite import atomic_json
from .run import read_rows, score_ranking


def main():
    experiment = json.loads((REPORT / "results.json").read_text(encoding="utf-8"))
    if not experiment["passes_guardrails"]:
        raise ValueError("Selected policy failed validation")
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    from pathlib import Path

    if any(
        hash_file(Path(path)) != digest for path, digest in manifest["inputs"].items()
    ):
        raise ValueError("Frozen experiment changed")
    chosen = experiment["selection"]["chosen"]
    weight = WEIGHTS[chosen]
    tasks = tasks_for()
    source = {
        n: {r["key"]: r for r in read_rows(ROOT / "runs" / f"{n}.jsonl")} for n in NAMES
    }
    output, old, overhead, rescues, losses = [], [], [], [], []
    for t in tasks:
        a, b = [source[n][t["key"]] for n in NAMES]
        started = time.perf_counter()
        ordered = rank(a["ids"], b["ids"], weight)
        elapsed = (time.perf_counter() - started) * 1000
        prior_pos = {pid: i for i, pid in enumerate(a["ids"], 1)}
        rerank_pos = {pid: i for i, pid in enumerate(b["ids"], 1)}
        scores = [
            (1 - weight) / (60 + rerank_pos[pid]) + weight / (60 + prior_pos[pid])
            for pid in ordered
        ]
        metrics = score_ranking(ordered, t["qrels"])
        assert set(ordered) == set(b["ids"]) and len(ordered) == len(b["ids"])
        assert metrics["recall@50"] == b["metrics"]["recall@50"]
        overhead.append(elapsed)
        old.append(b)
        output.append(
            {
                **b,
                "ids": ordered,
                "scores": scores,
                "top10_ids": ordered[:10],
                "score_type": "weighted_rrf_of_rerank_and_retrieval_ranks",
                "reranker_score_by_id": dict(zip(b["ids"], b["scores"])),
                "metrics": metrics,
                "timings_ms": {
                    "historical_baseline": b["timings_ms"]["total"],
                    "rank_fusion": elapsed,
                    "total": b["timings_ms"]["total"] + elapsed,
                },
                "policy": chosen,
            }
        )
        if b["metrics"]["hit@10"] == 0 and metrics["hit@10"] == 1:
            rescues.append(t["query_id"])
        if b["metrics"]["hit@10"] == 1 and metrics["hit@10"] == 0:
            losses.append(t["query_id"])
    summaries = {
        d: {
            "old": summarize([r for r in old if r["dataset"] == d]),
            "new": summarize([r for r in output if r["dataset"] == d]),
            "paired": paired_comparison(
                [r for r in old if r["dataset"] == d],
                [r for r in output if r["dataset"] == d],
            ),
        }
        for d in ("mtrag-human", "mtragun-human")
    }
    full_guard = all(
        s["new"]["domain_macro"][m] >= s["old"]["domain_macro"][m] - 1e-12
        for s in summaries.values()
        for m in ("ndcg@10", "recall@10")
    )
    result = {
        "chosen": chosen,
        "full_regression_guard": full_guard,
        "queries": len(output),
        "summary": summaries,
        "recovered_zero_hits": rescues,
        "new_zero_hits": losses,
        "fusion_cpu_p50_ms": percentile(overhead, 0.5),
        "fusion_cpu_p95_ms": percentile(overhead, 0.95),
        "new_model_calls": 0,
        "new_llm_calls": 0,
        "production_deployed": False,
    }
    atomic_json(REPORT / "full-results.json", result)
    target = OUT / "rankings.jsonl"
    temp = target.with_suffix(".jsonl.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for row in output:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temp.replace(target)
    p = profile()
    p["models"] = {k: v for k, v in p["models"].items() if k.startswith("bge_m3_")}
    p["rewrite"]["prompt_version"] = "v1"
    p["query_modes"] = ["deepseek_rewrite"]
    p["retrieval"]["final_rank_fusion"] = {
        "method": "weighted_rrf",
        "constant": 60,
        "reranker_weight": 1 - weight,
        "retrieval_weight": weight,
        "candidate_pool": "unchanged_fused50",
    }
    if full_guard:
        atomic_json(
            OUT / "recommended-profile.json",
            {
                "profile": p,
                "implementation": "evaluation.mtrag.rank_prior.rank",
                "status": "internal_regression_passed",
                "apply_after": "M3 reranking, before final top10",
                "production_deployed": False,
                "warning": "Default run.py does not automatically consume this experimental policy; use rank_prior/finalize_rank_prior entry points",
            },
        )
    lines = [
        "# 最终排序优化：全量复核",
        "",
        f"冻结方案：{chosen}；全量回归门槛通过：{full_guard}。",
        "",
        "| 数据集 | 旧 nDCG@10 | 新 nDCG@10 | 旧 Recall@10 | 新 Recall@10 |",
        "|---|---:|---:|---:|---:|",
    ]
    for d, s in summaries.items():
        a, b = s["old"]["domain_macro"], s["new"]["domain_macro"]
        lines.append(
            f"| {d} | {a['ndcg@10']:.4f} | {b['ndcg@10']:.4f} | {a['recall@10']:.4f} | {b['recall@10']:.4f} |"
        )
    lines += [
        "",
        f"由零命中变成命中：{len(rescues)}题；由命中变成零命中：{len(losses)}题。",
        "",
        f"本次实测新增CPU排序融合耗时：P50 {result['fusion_cpu_p50_ms']:.4f} ms，P95 {result['fusion_cpu_p95_ms']:.4f} ms。",
        "原有模型推理复用缓存；不是新测端到端延迟，也没有新增模型/API请求。",
        "1,109条输出均验证候选ID集合不变、Recall@50不变；只改变最终顺序。",
        "最初提示词、查询缓存、512输入和两路召回预算保持不变。",
        "全量结果含调参题，不能作为独立验证。已有内部验证450题的结果另见README.md；不宣称统计显著。",
        "实验推荐配置与排名位于 data/evaluation/mtrag/rank-prior-v1/；应用生产配置没有修改。",
        "",
    ]
    (REPORT / "FULL_RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "summary"}), flush=True)


if __name__ == "__main__":
    main()
