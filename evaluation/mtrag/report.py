"""Verify complete coverage and publish reproducible stage-level comparisons."""

import json
import statistics
from collections import defaultdict
from pathlib import Path

from .download import ROOT
from .profile import comparison_matrix, load_profile
from .run import queries, read_rows, score_ranking
from .rewrite import atomic_json
from .freeze_runtime import hash_file


def percentile(values, p):
    values = sorted(values)
    position = (len(values) - 1) * p
    lo = int(position)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (
        position - lo
    )


def summarize(rows):
    metrics = rows[0]["metrics"]
    by_domain = defaultdict(list)
    for row in rows:
        by_domain[row["domain"]].append(row)

    def mean(values):
        return statistics.mean(values)

    per_domain = {
        domain: {
            metric: mean(r["metrics"][metric] for r in subset) for metric in metrics
        }
        for domain, subset in by_domain.items()
    }
    times = [r["timings_ms"]["total"] for r in rows]
    return {
        "queries": len(rows),
        "query_mean": {
            metric: mean(r["metrics"][metric] for r in rows) for metric in metrics
        },
        "domain_macro": {
            metric: mean(d[metric] for d in per_domain.values()) for metric in metrics
        },
        "per_domain": per_domain,
        "latency_p50_ms": percentile(times, 0.5),
        "latency_p95_ms": percentile(times, 0.95),
    }


def paired_comparison(first, second):
    """Compare identical tasks, retaining domain macro weighting."""
    left = {r["key"]: r for r in first}
    right = {r["key"]: r for r in second}
    if left.keys() != right.keys():
        raise ValueError("Paired comparison requires identical query keys")
    output = {}
    for metric in ("ndcg@10", "recall@10", "recall@50"):
        by_domain = defaultdict(list)
        deltas = []
        for key, a in left.items():
            delta = right[key]["metrics"][metric] - a["metrics"][metric]
            deltas.append(delta)
            by_domain[a["domain"]].append(delta)
        output[metric] = {
            "domain_macro_delta": statistics.mean(
                statistics.mean(v) for v in by_domain.values()
            ),
            "improved_queries": sum(d > 1e-12 for d in deltas),
            "unchanged_queries": sum(abs(d) <= 1e-12 for d in deltas),
            "regressed_queries": sum(d < -1e-12 for d in deltas),
        }
    return output


def main():
    profile = load_profile()
    tasks = queries(profile)
    by_key = {t["key"]: t for t in tasks}
    expected = set(by_key)
    audit = json.loads((ROOT / "data_audit.json").read_text(encoding="utf-8"))
    summary, run_rows = [], {}
    human_inputs = {t["input_sha256"] for t in tasks if t["dataset"] == "mtrag-human"}
    for config in comparison_matrix(profile):
        name = config["retriever"] + (
            f"_rerank_{config['reranker']}" if config["reranker"] else ""
        )
        if name not in run_rows:
            rows = read_rows(ROOT / "runs" / f"{name}.jsonl")
            if len(rows) != len(expected) or {r["key"] for r in rows} != expected:
                raise ValueError(f"Incomplete/duplicate result coverage: {name}")
            for row in rows:
                recalculated = score_ranking(row["ids"], by_key[row["key"]]["qrels"])
                if recalculated != row["metrics"]:
                    raise ValueError("Stored metrics do not match rankings")
            run_rows[name] = rows
        for dataset in profile["datasets"]:
            selected = [
                r
                for r in run_rows[name]
                if r["dataset"] == dataset and r["mode"] == config["query_mode"]
            ]
            record = {
                "dataset": dataset,
                "configuration": name,
                "query_mode": config["query_mode"],
                **summarize(selected),
            }
            record["failure_diagnostics"] = {
                "no_labeled_positive_in_top50": sum(
                    r["metrics"]["recall@50"] == 0 for r in selected
                ),
                "positive_in_top50_but_none_in_top10": sum(
                    r["metrics"]["recall@50"] > 0 and r["metrics"]["hit@10"] == 0
                    for r in selected
                ),
                "at_least_one_positive_in_top10": sum(
                    r["metrics"]["hit@10"] > 0 for r in selected
                ),
            }
            record["turn_groups"] = {}
            for label, first in (("first_turn", True), ("later_turn", False)):
                subset = [
                    r for r in selected if (by_key[r["key"]]["turn"] == 1) == first
                ]
                if subset:
                    record["turn_groups"][label] = summarize(subset)
            if dataset == "mtragun-human":
                independent = [
                    r
                    for r in selected
                    if by_key[r["key"]]["input_sha256"] not in human_inputs
                ]
                record["excluding_human_identical_inputs"] = summarize(independent)
            summary.append(record)
    caches = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (ROOT / "rewrites").glob("*.json")
    ]
    usage = {
        key: sum((r.get("usage") or {}).get(key, 0) for r in caches)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
        )
    }
    rewrite = {
        "unique_successful_api_calls": len(caches),
        "usage": usage,
        "latency_p50_ms": percentile([r["latency_ms"] for r in caches], 0.5),
        "latency_p95_ms": percentile([r["latency_ms"] for r in caches], 0.95),
        "response_models": sorted(
            {r.get("response_model") or "unknown" for r in caches}
        ),
    }
    indexes = {}
    for family in ("bge", "qwen"):
        indexes[family] = {
            p.stem.replace(".meta", ""): json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "vectors" / family).glob("*.meta.json")
        }
        if len(indexes[family]) != 4 or not all(
            m["complete"] for m in indexes[family].values()
        ):
            raise ValueError("Incomplete vector indexes")
    result = {
        "status": "complete",
        "audit": audit,
        "rewrite": rewrite,
        "indexing": indexes,
        "results": summary,
        "row_count": sum(len(rows) for rows in run_rows.values()),
        "configuration_count_per_dataset": 18,
    }
    comparisons = []
    for dataset in profile["datasets"]:
        for name, rows in run_rows.items():
            first = [
                {**r, "key": r["query_id"]}
                for r in rows
                if r["dataset"] == dataset and r["mode"] == "last_turn"
            ]
            second = [
                {**r, "key": r["query_id"]}
                for r in rows
                if r["dataset"] == dataset and r["mode"] == "deepseek_rewrite"
            ]
            comparisons.append(
                {
                    "dataset": dataset,
                    "configuration": name,
                    "before": "last_turn",
                    "after": "deepseek_rewrite",
                    "metrics": paired_comparison(first, second),
                }
            )
        for mode in profile["query_modes"]:
            pairs = [
                ("bm25", "bge_dense"),
                ("bm25", "qwen_dense"),
                ("bge_dense", "bm25_bge"),
                ("qwen_dense", "bm25_qwen"),
            ]
            pairs.extend(
                (f"bm25_{retriever}", f"bm25_{retriever}_rerank_{ranker}")
                for retriever in ("bge", "qwen")
                for ranker in ("bge", "qwen")
            )
            for before, after in pairs:
                first = [
                    r
                    for r in run_rows[before]
                    if r["dataset"] == dataset and r["mode"] == mode
                ]
                second = [
                    r
                    for r in run_rows[after]
                    if r["dataset"] == dataset and r["mode"] == mode
                ]
                comparisons.append(
                    {
                        "dataset": dataset,
                        "query_mode": mode,
                        "before": before,
                        "after": after,
                        "metrics": paired_comparison(first, second),
                    }
                )
    result["paired_stage_comparisons"] = comparisons
    result["implementation_sha256"] = {
        p.name: hash_file(p) for p in Path(__file__).parent.glob("*.py")
    }
    result["reranker_runtime"] = {
        family: json.loads(
            (ROOT / "runs" / f"{family}-rerank-runtime.json").read_text(
                encoding="utf-8"
            )
        )
        for family in ("bge", "qwen")
    }
    out = (
        Path(__file__).resolve().parents[2] / "docs/reports/mtrag-retrieval-2026-09-26"
    )
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / "results.json", result)
    for name in (
        "source_manifest.json",
        "runtime_manifest.json",
        "data_audit.json",
        "query_alignment.json",
        "dependency_audit.json",
    ):
        atomic_json(out / name, json.loads((ROOT / name).read_text(encoding="utf-8")))
    lines = [
        "# MTRAG 本地检索评测报告",
        "",
        "状态：完整检索评测完成（不含最终答案生成）。",
        "",
        "## 数据与实验设置",
        "",
        "- Human：777 题；UN 当前公开且具有正例标注的部分：332 题。每题运行 18 个配置。",
        f"- 官方完整语料：{sum(c['passages'] for c in audit['corpora'].values()):,} 个片段；qrels ID 校验无缺失。",
        "- 官方文件中的实际领域数量与 README 表格存在差异，以下载文件的校验结果为准。",
        "- 41 个官方空片段保留在语料存档，向量置零并排除检索；它们均不是 qrels 正例。实际可检索非空片段 366,438 个。",
        "- 两套数据存在 15 组相同历史与问题；本轮没有基于测试结果调参。JSON 另给 UN 排除相同输入后的指标。",
        "- CUDA、BF16、batch=8、512-token 共同输入预算；精确余弦召回；每通道50、融合50、重排50、输出10。",
        "- BGE-small-zh 面向中文，本轮英文语料结果不代表整个 BGE 系列或中文场景。",
        "- BM25：小写英文数字分词，无词干化、无停用词过滤；k1=1.2、b=0.75。RRF k=60，等权。",
        "- 最低分、分差过滤、意图分解和文本去重均关闭；重复 ID 合并。",
        "- 查询改写只使用截止当前问题的对话，不读取当前答案、相关片段或 qrels。",
        "",
    ]
    lines.extend(
        [
            "## 依赖环境",
            "",
            "- 评测进程使用工作区内 Transformers 4.57.6、tokenizers 0.22.2、huggingface-hub 0.36.2、safetensors 0.6.2。",
            "- 原应用 Python 环境未覆盖升级，原环境 `pip check` 通过。四个评测模型均已真实加载并通过推理冒烟检查。",
            "- 激活评测依赖后检查 316 个已安装发行包：315 个库的默认依赖要求兼容；仅原应用 interview-copilot 声明的 Transformers/Hub 旧版本精确锁定与评测版本不同。评测不导入原应用。",
            "- 因此新依赖仅对本评测进程生效；这不构成原应用已兼容新版本的证明。完整检查见 dependency_audit.json。",
            "",
        ]
    )
    lines.extend(["## 本轮观察", ""])
    for dataset in profile["datasets"]:
        selected = [r for r in summary if r["dataset"] == dataset]
        best = max(selected, key=lambda r: r["domain_macro"]["ndcg@10"])
        best_without_rerank = max(
            (r for r in selected if "_rerank_" not in r["configuration"]),
            key=lambda r: r["domain_macro"]["ndcg@10"],
        )
        lines.append(
            f"- {dataset}：本轮 nDCG@10 最高为 `{best['configuration']}` / `{best['query_mode']}`，"
            f"得分 {best['domain_macro']['ndcg@10']:.4f}，Recall@10 {best['domain_macro']['recall@10']:.4f}。"
            f"无重排配置中最高为 `{best_without_rerank['configuration']}` / `{best_without_rerank['query_mode']}`，"
            f"nDCG@10 {best_without_rerank['domain_macro']['ndcg@10']:.4f}。"
        )
    lines.extend(
        [
            "- 以上是同一测试集上的描述性比较，未进行显著性检验；不要将很小的分差解读为可靠胜出。",
            "",
        ]
    )
    for dataset in profile["datasets"]:
        lines.extend(
            [
                f"## {dataset}",
                "",
                "质量指标是四领域等权宏平均；耗时为各阶段实测耗时相加，排除模型加载和 DeepSeek。",
                "",
                "| 配置 | 查询方式 | nDCG@10 | Recall@10 | Recall@50 | Hit@10 | P50 ms | P95 ms |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        selected = sorted(
            (r for r in summary if r["dataset"] == dataset),
            key=lambda r: r["domain_macro"]["ndcg@10"],
            reverse=True,
        )
        for r in selected:
            m = r["domain_macro"]
            lines.append(
                f"| {r['configuration']} | {r['query_mode']} | {m['ndcg@10']:.4f} | {m['recall@10']:.4f} | {m['recall@50']:.4f} | {m['hit@10']:.4f} | {r['latency_p50_ms']:.1f} | {r['latency_p95_ms']:.1f} |"
            )
        lines.append("")
    lines.extend(
        [
            "## 分阶段配对变化",
            "",
            "每行使用相同问题比较，Δ 为四领域宏平均之差；改善/持平/退步按逐题 nDCG@10 计数。",
            "",
            "| 数据集 | 对照 | Δ nDCG@10 | Δ Recall@10 | 改善 / 持平 / 退步 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for comparison in comparisons:
        m = comparison["metrics"]
        title = (
            (comparison.get("configuration") or comparison.get("query_mode"))
            + ": "
            + comparison["before"]
            + " → "
            + comparison["after"]
        )
        n = m["ndcg@10"]
        lines.append(
            f"| {comparison['dataset']} | {title} | {n['domain_macro_delta']:+.4f} | "
            f"{m['recall@10']['domain_macro_delta']:+.4f} | "
            f"{n['improved_queries']} / {n['unchanged_queries']} / {n['regressed_queries']} |"
        )
    lines.extend(
        [
            "",
            "逐配置 JSON 另含：Top50 完全漏召回、Top50 命中但 Top10 未命中、Top10 命中三类数量。"
            "这有助于区分召回问题和排序问题；Top50 完全没有标注正例时，重排无法补回。",
            "",
        ]
    )
    lines.extend(
        [
            "## 改写调用与复用",
            "",
            f"- 本次唯一成功改写调用：{len(caches)} 次；缓存目录 `data/evaluation/mtrag/rewrites/`。",
            f"- 输入 tokens：{usage['prompt_tokens']:,}；输出 tokens：{usage['completion_tokens']:,}。不将 token 数冒充实际账单金额。",
            f"- 首次改写 P50/P95：{rewrite['latency_p50_ms']:.1f}/{rewrite['latency_p95_ms']:.1f} ms。",
            "- 后续相同查询与改写配置默认只读缓存，不重新发起 API 请求。",
            "",
            "## 限制与解释",
            "",
            "- UN 仅测已公开的四个领域，不包含尚未发布的 Banking/Telco。",
            "- 两套数据的问题分布不同，不能用两个总分的高低直接断定哪套整体更难。",
            "- 无正例的不可答/欠明确任务不计入普通 Recall/nDCG；本轮未评价拒答能力。",
            "- 512 tokens 是统一预算实验，各 tokenizer 的实际可见文本不同；长文本能力不在此结论范围内。",
            "- 多轮检索分数不能直接证明必须跨文档推理的能力；没有将多个相关片段自动当作必需证据链。",
            "- 对话历史使用官方固定输入；本轮不测线上生成错误在后续对话中的累积效应。",
            "- qrels 不保证穷举所有相关片段，未标注内容按标准做法记零分。",
            "- 延迟是阶段组合估计，BM25 与向量召回采用相加；不能当作生产并行请求的端到端 SLA。",
            "- 完全相同的领域、查询、候选列表和模型会复用重排结果；延迟沿用该相同输入首次实际推理耗时，而非缓存命中耗时。逐题文件标记 reused_identical_inference。",
            "- 首次 API 耗时与本地检索耗时分开；缓存命中不会使首次调用耗时消失。",
            "- 原始逐题排名保存在 data/evaluation/mtrag/runs；运行环境和模型文件哈希见 runtime_manifest.json；源文件哈希见 source_manifest.json。",
            "",
        ]
    )
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {"status": "complete", "report": str(out), "rows": result["row_count"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
