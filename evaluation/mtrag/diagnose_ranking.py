"""Read-only v1 diagnosis: stage loss and fixed-pool length intervention."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics

from .download import ROOT
from .local_models import AutoTokenizer
from .m3_campaign import profile
from .optimize_m3 import tasks_for, row_path, score_cache_path, load_json
from .rewrite import atomic_json
from .run import read_rows, score_ranking

REPORT = Path(__file__).resolve().parents[2] / "docs/reports/mtrag-ranking-diagnosis"
NAMES = ("bm25", "bge_m3_dense", "bm25_bge_m3", "bm25_bge_m3_rerank_bge_m3")


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    p = profile()
    assert p["rewrite"].get("prompt_version", "v1") == "v1"
    tasks = tasks_for()
    runs = {
        name: {r["key"]: r for r in read_rows(ROOT / "runs" / f"{name}.jsonl")}
        for name in NAMES
    }
    totals, failures, strata = Counter(), Counter(), defaultdict(Counter)
    stage_rows = []
    for t in tasks:
        key, gold = t["key"], set(t["qrels"])
        union = set(runs[NAMES[0]][key]["ids"] + runs[NAMES[1]][key]["ids"])
        pool = set(runs[NAMES[2]][key]["ids"])
        top = set(runs[NAMES[3]][key]["ids"][:10])
        lost = {
            "retrieval": sorted(gold - union),
            "fusion": sorted((gold & union) - pool),
            "reranking": sorted((gold & pool) - top),
            "returned": sorted(gold & top),
        }
        assert sum(map(len, lost.values())) == len(gold)
        totals.update({k: len(v) for k, v in lost.items()})
        location = (
            "hit"
            if gold & top
            else "retrieval"
            if not gold & union
            else "fusion"
            if not gold & pool
            else "reranking"
        )
        failures[location] += 1
        strata[t["dataset"]][location] += 1
        stage_rows.append(
            {
                "query_id": t["query_id"],
                "dataset": t["dataset"],
                "domain": t["domain"],
                "split": t["split"],
                "failure": location,
                "evidence": lost,
            }
        )
    atomic_json(
        REPORT / "stage-audit.json",
        {
            "queries": len(tasks),
            "prompt_version": "v1",
            "labeled_pairs": totals,
            "zero_hit_first_blocker": failures,
            "by_dataset": strata,
            "rows": stage_rows,
        },
    )

    tokenizer = AutoTokenizer.from_pretrained(
        p["models"]["bge_m3_reranker"]["path"], local_files_only=True
    )
    tokenizer.model_max_length = 10**9
    specials = tokenizer.num_special_tokens_to_add(pair=True)
    counts, rows, selected_cases = Counter(), [], []
    for domain in sorted({t["domain"] for t in tasks}):
        chosen = [t for t in tasks if t["domain"] == domain and t["split"] == "tune"]
        ids = {pid for t in chosen for pid in runs[NAMES[2]][t["key"]]["ids"]}
        texts = {}
        with (ROOT / "corpus" / f"{domain}.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                r = json.loads(line)
                if r["_id"] in ids:
                    texts[r["_id"]] = r["text"]
        tokenized = {
            pid: tokenizer.encode(text, add_special_tokens=False)
            for pid, text in texts.items()
        }
        domain_rows = []
        for t in chosen:
            key = t["key"]
            pool = runs[NAMES[2]][key]["ids"]
            retrieved = load_json(row_path("retrieval", key))
            union = sorted(set(retrieved["dense"] + retrieved["bm25"]))
            score = {
                length: load_json(score_cache_path(t, length, union))["scores"]
                for length in (512, 1024)
            }
            ranks = {
                length: sorted(pool, key=lambda pid: (-score[length][pid], pid))
                for length in score
            }
            metrics = {
                length: score_ranking(ranks[length], t["qrels"]) for length in score
            }
            qlen = len(tokenizer.encode(t["query"], add_special_tokens=False))
            budget = 512 - min(qlen, 96) - specials
            gold = set(t["qrels"]) & set(pool)
            clipped = {pid for pid in pool if len(tokenized[pid]) > budget}
            lost = gold - set(ranks[512][:10])
            recovered = lost & set(ranks[1024][:10])
            dropped = (gold & set(ranks[512][:10])) - set(ranks[1024][:10])
            delta = metrics[1024]["ndcg@10"] - metrics[512]["ndcg@10"]
            counts.update(
                {
                    "queries": 1,
                    "query_truncated": int(qlen > 96),
                    "candidate_pairs": len(pool),
                    "clipped_candidate_pairs": len(clipped),
                    "positive_candidate_pairs": len(gold),
                    "clipped_positive_pairs": len(gold & clipped),
                    "lost_positive_pairs": len(lost),
                    "lost_positive_clipped": len(lost & clipped),
                    "recovered_positive_pairs": len(recovered),
                    "recovered_positive_clipped": len(recovered & clipped),
                    "dropped_positive_pairs": len(dropped),
                    "dropped_positive_clipped": len(dropped & clipped),
                    "improved": int(delta > 1e-12),
                    "regressed": int(delta < -1e-12),
                    "unchanged": int(abs(delta) <= 1e-12),
                    "baseline_replay_metric_diff": int(
                        abs(
                            metrics[512]["ndcg@10"]
                            - runs[NAMES[3]][key]["metrics"]["ndcg@10"]
                        )
                        > 1e-12
                    ),
                }
            )
            record = {
                "query_id": t["query_id"],
                "dataset": t["dataset"],
                "domain": domain,
                "query": t["query"],
                "query_tokens": qlen,
                "passage_budget_512": budget,
                "pool_count": len(pool),
                "clipped_count": len(clipped),
                "lost_positive": sorted(lost),
                "lost_positive_clipped": sorted(lost & clipped),
                "recovered": sorted(recovered),
                "dropped": sorted(dropped),
                "metrics_512": metrics[512],
                "metrics_1024": metrics[1024],
                "delta": delta,
                "rank_512": ranks[512],
                "rank_1024": ranks[1024],
            }
            rows.append(record)
            domain_rows.append(record)
        for dataset in ("mtrag-human", "mtragun-human"):
            cell = [r for r in domain_rows if r["dataset"] == dataset]
            candidates = sorted(cell, key=lambda r: r["delta"])
            picks = candidates[:1] + candidates[-1:]
            # Include an untruncated missed positive: controls the blanket truncation hypothesis.
            uncut = next(
                (
                    r
                    for r in cell
                    if set(r["lost_positive"]) - set(r["lost_positive_clipped"])
                ),
                None,
            )
            if uncut:
                picks.append(uncut)
            for r in picks:
                show = list(
                    dict.fromkeys(
                        r["recovered"][:1]
                        + r["dropped"][:1]
                        + r["lost_positive"][:1]
                        + r["rank_512"][:1]
                    )
                )
                selected_cases.append(
                    {
                        **r,
                        "passages": [
                            {
                                "id": pid,
                                "tokens": len(tokenized[pid]),
                                "text": texts[pid],
                                "visible_at_512": tokenizer.decode(
                                    tokenized[pid][: r["passage_budget_512"]]
                                ),
                                "newly_visible_at_1024": tokenizer.decode(
                                    tokenized[pid][
                                        r["passage_budget_512"] : r[
                                            "passage_budget_512"
                                        ]
                                        + 512
                                    ]
                                ),
                            }
                            for pid in show
                        ],
                    }
                )
        print("audited", domain, len(chosen), flush=True)
    groups = defaultdict(list)
    for r in rows:
        groups[(r["dataset"], r["domain"])].append(r)
    macro = {
        length: statistics.mean(
            statistics.mean(r[f"metrics_{length}"]["ndcg@10"] for r in cell)
            for cell in groups.values()
        )
        for length in (512, 1024)
    }
    summary = {
        "counts": counts,
        "equal_dataset_domain_macro_ndcg10": macro,
        "fixed_pool": "original fused top50 for both lengths",
        "scope": "659 tune inputs; cached scores only",
        "no_new_inference": True,
        "caveat": "Different batch padding can cause numerical differences; clipping alone does not prove answer evidence was lost",
    }
    atomic_json(REPORT / "length-audit.json", {**summary, "rows": rows})
    atomic_json(REPORT / "cases.json", selected_cases)
    lines = [
        "# 原始改写下的候选与重排诊断",
        "",
        "## 固定基线",
        "",
        "使用最初 v1 提示词的完整旧缓存及 BGE-M3 / bge-reranker-v2-m3。未调用 API、未重新推理、未修改提示词或排名。",
        "",
        "## 全量阶段定位",
        "",
        f"查询数：{len(tasks)}。零命中题首个阻断位置：`{json.dumps(failures)}`。",
        "",
        f"全部正例片段对分布：`{json.dumps(totals)}`。这是官方标注正例的去向，未标注片段不等于不相关。",
        "",
        "## 固定候选池的长度诊断",
        "",
        "复用659道调参题已保存的512/1024分数，将两者限制在同一份原始融合前50候选中。",
        "",
        f"统计：`{json.dumps(counts)}`。",
        "",
        f"八个数据集/领域单元等权 nDCG@10：512 = {macro[512]:.6f}；1024 = {macro[1024]:.6f}。",
        "",
        "## 解释边界",
        "",
        "截断存在不代表答案证据必然被截断；长度增加后的排名变化也可能来自竞争片段获得更多文本。",
        "baseline_replay_metric_diff 记录缓存分数在原池复算与历史基线的差异，不能隐去批次/padding数值影响。",
        "这些数据已多次用于诊断，不能当成独立盲测；本轮不选新参数，不将金标用于实际检索。",
        "",
        "详细文件：stage-audit.json、length-audit.json、cases.json。",
        "",
    ]
    (REPORT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
