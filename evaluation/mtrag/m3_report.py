"""Model-explicit comparison of project M3 and Qwen, with old BGE as an appendix."""

import json
from pathlib import Path

from .download import ROOT
from .freeze_runtime import hash_file
from .m3_campaign import MANIFEST, profile
from .report import summarize
from .run import queries, read_rows, score_ranking
from .rewrite import atomic_json

PRIMARY = {
    "bm25": "BM25",
    "bge_m3_dense": "BGE-M3 dense",
    "qwen_dense": "Qwen3-Embedding-0.6B dense",
    "bm25_bge_m3": "BM25 + BGE-M3",
    "bm25_qwen": "BM25 + Qwen",
    "bm25_bge_m3_rerank_bge_m3": "BM25 + BGE-M3 → bge-reranker-v2-m3",
    "bm25_bge_m3_rerank_qwen": "BM25 + BGE-M3 → Qwen3-Reranker-0.6B",
    "bm25_qwen_rerank_bge_m3": "BM25 + Qwen → bge-reranker-v2-m3",
    "bm25_qwen_rerank_qwen": "BM25 + Qwen → Qwen3-Reranker-0.6B",
}
HISTORICAL = {
    "bge_dense": "bge-small-zh-v1.5 dense [旧对照]",
    "bm25_bge": "BM25 + bge-small-zh-v1.5 [旧对照]",
    "bm25_bge_rerank_bge": "BM25 + bge-small-zh-v1.5 → bge-reranker-base [旧对照]",
    "bm25_bge_rerank_qwen": "BM25 + bge-small-zh-v1.5 → Qwen [旧对照]",
    "bm25_qwen_rerank_bge": "BM25 + Qwen → bge-reranker-base [旧对照]",
}


def main():
    p = profile()
    tasks = {t["key"]: t for t in queries(p)}
    summaries = []
    total = 0
    for name, label in {**PRIMARY, **HISTORICAL}.items():
        rows = read_rows(ROOT / "runs" / f"{name}.jsonl")
        if len(rows) != len(tasks) or {r["key"] for r in rows} != tasks.keys():
            raise ValueError(f"Incomplete result coverage: {name}")
        for row in rows:
            if row["metrics"] != score_ranking(row["ids"], tasks[row["key"]]["qrels"]):
                raise ValueError(f"Metric verification failed: {name}")
        total += len(rows)
        for dataset in p["datasets"]:
            for mode in p["query_modes"]:
                selected = [
                    r for r in rows if r["dataset"] == dataset and r["mode"] == mode
                ]
                summaries.append(
                    {
                        "configuration": name,
                        "label": label,
                        "dataset": dataset,
                        "mode": mode,
                        "historical": name in HISTORICAL,
                        **summarize(selected),
                    }
                )
    for domain in ("clapnq", "cloud", "fiqa", "govt"):
        meta = json.loads((ROOT / "vectors/bge_m3" / f"{domain}.meta.json").read_text())
        if not meta["complete"]:
            raise ValueError("Incomplete M3 index")
        validation = json.loads(
            (ROOT / "runs" / f"vector-validation-bge_m3-{domain}.json").read_text()
        )
        if (
            not validation["finite"]
            or not validation["normalized"]
            or min(validation["sample_cosines"]) <= 0.999
        ):
            raise ValueError("M3 vector validation failed")
    out = Path(__file__).resolve().parents[2] / "docs/reports/mtrag-retrieval-m3"
    out.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(
        (out.parent / "mtrag-retrieval-2026-09-26/results.json").read_text(
            encoding="utf-8"
        )
    )
    result = {
        "status": "complete",
        "rows_including_historical": total,
        "primary_configurations_per_dataset": 18,
        "results": summaries,
        "rewrite": baseline["rewrite"],
        "new_paid_llm_calls": 0,
        "manifest": json.loads(MANIFEST.read_text(encoding="utf-8")),
        "implementation_sha256": {
            f.name: hash_file(f) for f in Path(__file__).parent.glob("*.py")
        },
    }
    atomic_json(out / "results.json", result)
    lines = [
        "# 项目 BGE-M3 与 Qwen 检索对比",
        "",
        "状态：全量补测及指标复算完成。",
        "",
        "- 主比较使用项目内 bge-m3、bge-reranker-v2-m3，以及原 Qwen 两个模型；旧 BGE 放在历史附表。",
        "- Human 777 题、UN 公开正例任务 332 题，四领域语料 366,479 个片段，排除 41 个空片段。",
        "- 每套数据主比较 18 个配置；另保留旧模型的 10 个历史配置。",
        "- BF16、batch 8、512 tokens、每通道50、融合50、重排50、输出10；不设分数门槛。",
        "- BGE-M3 采用 CLS + L2 归一化，查询不添加指令；本次仅测试 dense，不测试 M3 sparse/ColBERT。",
        "- M3 从项目目录加载；D:/Models/BAAI 下副本已逐文件 SHA256 校验。",
        "- 复用全部 DeepSeek 改写缓存及原 BM25/Qwen 结果，补测新增付费 LLM 调用为0。",
        "- nDCG/Recall 为四领域宏平均，P50/P95 为各阶段耗时相加，排除模型加载、DeepSeek 和答案生成。",
        "- 历史结果复用意味着测量时间不同；延迟用于本机单请求比较，不代表线上并发 SLA。",
        "",
    ]
    for historical, heading in (
        (False, "项目 M3 与 Qwen 主比较"),
        (True, "旧 BGE 历史对照"),
    ):
        lines.extend([f"## {heading}", ""])
        for dataset in p["datasets"]:
            lines.extend(
                [
                    f"### {dataset}",
                    "",
                    "| 配置 | 查询 | nDCG@10 | Recall@10 | Recall@50 | P50 ms | P95 ms |",
                    "|---|---|---:|---:|---:|---:|---:|",
                ]
            )
            selected = sorted(
                (
                    r
                    for r in summaries
                    if r["dataset"] == dataset and r["historical"] == historical
                ),
                key=lambda r: r["domain_macro"]["ndcg@10"],
                reverse=True,
            )
            for row in selected:
                m = row["domain_macro"]
                lines.append(
                    f"| {row['label']} | {row['mode']} | {m['ndcg@10']:.4f} | {m['recall@10']:.4f} | {m['recall@50']:.4f} | {row['latency_p50_ms']:.1f} | {row['latency_p95_ms']:.1f} |"
                )
            lines.append("")
    lines.extend(
        [
            "## 解释范围",
            "",
            "英文检索评测；无正例任务排除，不测拒答或最终回答正确率。"
            "统一512-token预算不代表完整长上下文能力。两套数据有15组相同对话输入，不能当作完全独立测试。"
            "qrels不是所有相关片段的穷举。未做显著性检验。",
            "",
        ]
    )
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {"status": "complete", "rows": total, "report": str(out)},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
