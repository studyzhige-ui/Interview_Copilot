"""Recompute resume-safe Hit@1 from original v1 M3 rankings and official qrels."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/evaluation/mtrag"
OUT = ROOT / "docs/reports/mtrag-top1-audit"
STAGES = ("bge_m3_dense", "bm25_bge_m3", "bm25_bge_m3_rerank_bge_m3")


def rows(path):
    return [
        json.loads(x)
        for x in path.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]


def main():
    tasks = {r["query_id"]: r for r in rows(DATA / "tasks.jsonl")}
    split = json.loads(
        (DATA / "optimization-m3-v1/split.json").read_text(encoding="utf-8")
    )
    runs = {}
    for name in STAGES:
        selected = [
            r
            for r in rows(DATA / "runs" / f"{name}.jsonl")
            if r["mode"] == "deepseek_rewrite"
        ]
        runs[name] = {r["query_id"]: r for r in selected}
        assert len(selected) == len(tasks) and runs[name].keys() == tasks.keys()
        assert all(any(v > 0 for v in t["qrels"].values()) for t in tasks.values())
    evidence = []
    for q, t in tasks.items():
        first = {n: runs[n][q]["ids"][0] if runs[n][q]["ids"] else None for n in STAGES}
        evidence.append(
            {
                "query_id": q,
                "dataset": t["dataset"],
                "domain": t["domain"],
                "split": split[q]["split"],
                "top1": first,
                "hit1": {
                    n: int(t["qrels"].get(pid, 0) > 0) for n, pid in first.items()
                },
            }
        )
    results = []
    for dataset in ("mtrag-human", "mtragun-human"):
        for part in ("all", "validation"):
            selected = [
                r
                for r in evidence
                if r["dataset"] == dataset and (part == "all" or r["split"] == part)
            ]
            counts = {n: sum(r["hit1"][n] for r in selected) for n in STAGES}
            rates = {n: c / len(selected) for n, c in counts.items()}
            gains = sum(
                r["hit1"][STAGES[0]] == 0 and r["hit1"][STAGES[-1]] == 1
                for r in selected
            )
            losses = sum(
                r["hit1"][STAGES[0]] == 1 and r["hit1"][STAGES[-1]] == 0
                for r in selected
            )
            assert gains - losses == counts[STAGES[-1]] - counts[STAGES[0]]
            results.append(
                {
                    "dataset": dataset,
                    "split": part,
                    "n": len(selected),
                    "hits": counts,
                    "rates": rates,
                    "dense_to_final_pp": 100 * (rates[STAGES[-1]] - rates[STAGES[0]]),
                    "dense_to_final_relative_percent": 100
                    * (rates[STAGES[-1]] / rates[STAGES[0]] - 1),
                    "paired_gained": gains,
                    "paired_lost": losses,
                }
            )
    sources = [
        DATA / "tasks.jsonl",
        DATA / "rewritten.jsonl",
        DATA / "optimization-m3-v1/split.json",
    ]
    sources += [DATA / "runs" / f"{n}.jsonl" for n in STAGES]
    OUT.mkdir(parents=True, exist_ok=True)
    result = {
        "metric": "Hit@1: first passage ID has official qrel > 0; empty result is miss",
        "aggregation": "per-query mean, not domain macro",
        "results": results,
        "hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "limitations": [
            "Exact dense search, not PostgreSQL HNSW",
            "English ASCII BM25 analyzer, not Chinese jieba",
            "No confidence threshold or multi-intent decomposition",
            "Only queries with public positive qrels",
            "Existing internal validation has been inspected; not blind; datasets overlap",
        ],
    }
    (OUT / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (OUT / "per-query.jsonl").open("w", encoding="utf-8") as handle:
        for row in evidence:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    lines = [
        "# 简历指标核验：真实 Top-1 命中率",
        "",
        "统计原始v1改写下的M3基线结果；不重新请求LLM、不重新推理。",
        "",
        "口径：第一条返回片段ID在官方qrels中得分大于0记为命中，空结果记未命中；按题目数平均。不是生成答案准确率，也不是此前领域宏平均nDCG。",
        "",
        "| 数据集/划分 | 题数 | 纯稠密 | 混合未重排 | 混合+重排 | 相对纯稠密增加 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        vals = [f"{r['rates'][n] * 100:.2f}% ({r['hits'][n]}/{r['n']})" for n in STAGES]
        lines.append(
            f"| {r['dataset']} / {r['split']} | {r['n']} | {' | '.join(vals)} | {r['dense_to_final_pp']:.2f} 个百分点 |"
        )
    lines += [
        "",
        "## 可用于简历的表述",
        "",
        "架构：基于PostgreSQL单库实现pgvector HNSW稠密检索与SQL BM25评分，使用jieba中文分词，接入Cross-Encoder重排及多意图结果合并，减少跨检索存储同步环节。",
        "",
        "评测：在MTRAG Human公开正例子集（777题）的离线检索评测中，BM25+BGE-M3混合检索结合重排，使Top-1命中率由39.64%提升至43.50%（+3.86个百分点）；UN公开正例子集332题由47.29%提升至55.42%（+8.13个百分点）。",
        "",
        "## 不能混淆的证据边界",
        "",
        "- 上述离线指标没有通过生产PostgreSQL/HNSW执行；不能声称实测证明了整条数据库链路的增益。",
        "- 离线BM25用英文ASCII词项，未测试中文分词；分数门槛和多意图拆分均关闭。",
        "- Python中用jieba分词，词频写入PostgreSQL，由SQL计算BM25；不是SQL内完成中文分词。",
        "- 当前应用有最低分及相对最高分差过滤；未证明分数是校准后的置信概率，不宜写成经过验证的动态置信度。",
        "- 单库实现支持减少跨存储同步环节的架构描述，未测同步延迟改善，不能给出此项性能数字。",
        "- 不写消除语义偏斜；仍有失败查询。",
        "- 不将Human与UN简单当成互不重叠的独立样本合并宣传；不挑选最接近6%的划分。",
        "- 内部验证集被多次查看，全量也被用于优化；不能宣称独立盲测、线上A/B或统计显著。",
        "",
        "当前生产源码入口：backend/app/rag/hybrid_index.py、backend/app/rag/retrieval/reranking.py；离线历史指标复算脚本evaluation/mtrag/top1_audit.py。这些指标不代表当前规范检索投影的实测效果。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
