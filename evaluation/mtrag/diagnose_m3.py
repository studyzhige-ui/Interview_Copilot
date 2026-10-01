"""Trace labeled positive evidence through the fixed M3 retrieval baseline."""

from collections import Counter
import json
from pathlib import Path

from .download import ROOT
from .optimize_m3 import tasks_for, row_path, load_json
from .run import read_rows, corpus
from .rewrite import atomic_json

REPORT = Path(__file__).resolve().parents[2] / "docs/reports/mtrag-m3-diagnosis"


def main():
    tasks = tasks_for("tune")
    names = ("bge_m3_dense", "bm25", "bm25_bge_m3", "bm25_bge_m3_rerank_bge_m3")
    runs = {
        n: {r["key"]: r for r in read_rows(ROOT / "runs" / f"{n}.jsonl")} for n in names
    }
    histories = {
        r["query_id"]: r["messages"] for r in read_rows(ROOT / "queries.jsonl")
    }
    rows, totals, failures = [], Counter(), Counter()
    for t in tasks:
        key = t["key"]
        raw_key = "last_turn::" + t["query_id"]
        gold = set(t["qrels"])
        dense = runs["bge_m3_dense"][key]["ids"]
        lexical = runs["bm25"][key]["ids"]
        union = set(dense + lexical)
        fused = runs["bm25_bge_m3"][key]["ids"]
        ranked = runs["bm25_bge_m3_rerank_bge_m3"][key]["ids"]
        extended = load_json(row_path("retrieval", key))
        union100 = set(extended["dense"] + extended["bm25"])
        raw_union = set(
            runs["bge_m3_dense"][raw_key]["ids"] + runs["bm25"][raw_key]["ids"]
        )
        evidence = {
            "missed_by_both_channels_top50": sorted(gold - union),
            "discarded_by_fusion_top50": sorted((gold & union) - set(fused)),
            "outside_reranked_top10": sorted((gold & set(fused)) - set(ranked[:10])),
            "returned_top10": sorted(gold & set(ranked[:10])),
        }
        assert sum(len(v) for v in evidence.values()) == len(gold)
        for label, ids in evidence.items():
            totals[label] += len(ids)
        totals["total_labeled_pairs"] += len(gold)
        recovered_depth = (gold - union) & union100
        recovered_raw = (gold - union100) & raw_union
        totals["top50_misses_recovered_at_top100"] += len(recovered_depth)
        totals["top100_misses_present_in_raw_query_top50"] += len(recovered_raw)
        if not gold & set(ranked[:10]):
            location = (
                "retrieval"
                if not gold & union
                else "fusion"
                if not gold & set(fused)
                else "reranking"
            )
            failures[location] += 1
        else:
            location = "at_least_one_hit"
            failures[location] += 1
        before = runs["bm25_bge_m3_rerank_bge_m3"][raw_key]["metrics"]["ndcg@10"]
        after = runs["bm25_bge_m3_rerank_bge_m3"][key]["metrics"]["ndcg@10"]
        rows.append(
            {
                "query_id": t["query_id"],
                "domain": t["domain"],
                "dataset": t["dataset"],
                "group": t["group"],
                "last_turn": t["last_turn"],
                "rewritten": t["query"],
                "history": histories[t["query_id"]],
                "evidence": evidence,
                "failure_location": location,
                "depth_recoverable": sorted(recovered_depth),
                "raw_query_recoverable": sorted(recovered_raw),
                "rewrite_ndcg_delta": after - before,
                "top3_ids": ranked[:3],
                "dense_top10_positive": sorted(gold & set(dense[:10])),
                "rerank_lost_dense_top10_positive": sorted(
                    (gold & set(dense[:10])) - set(ranked[:10])
                ),
            }
        )
    REPORT.mkdir(parents=True, exist_ok=True)
    atomic_json(
        REPORT / "trace.json",
        {
            "scope": "659 tune queries only; validation untouched",
            "labeled_pair_partition": totals,
            "query_failure_locations": failures,
            "queries": rows,
        },
    )
    # Cases are selected by observable failure location, not by semantic judgement.
    selected = []
    for field in (
        "raw_query_recoverable",
        "depth_recoverable",
        "rerank_lost_dense_top10_positive",
    ):
        subset = sorted(
            (r for r in rows if r[field]), key=lambda r: r["rewrite_ndcg_delta"]
        )
        selected.extend({**r, "selection_reason": field} for r in subset[:4])
    for domain in {r["domain"] for r in selected}:
        docs = {r["_id"]: r for r in corpus(domain)}
        for row in selected:
            if row["domain"] != domain:
                continue
            ids = list(
                dict.fromkeys(row[row["selection_reason"]][:2] + row["top3_ids"][:1])
            )
            row["passages"] = [docs[pid] for pid in ids]
    atomic_json(REPORT / "case-review.json", selected)
    print(
        json.dumps(
            {
                "labeled_pairs": totals,
                "query_failures": failures,
                "case_review": str(REPORT / "case-review.json"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
