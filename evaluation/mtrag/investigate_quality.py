"""Post-evaluation diagnosis only: no parameter selection or application changes."""

import argparse
from collections import Counter
import json
import re
from pathlib import Path

from .download import ROOT
from .local_models import LocalModel
from .m3_campaign import profile
from .optimize_m3 import tasks_for, score_passages, macro
from .profile import fingerprint
from .quality_m3 import pools, rank, runs, OUT as QUALITY
from .rewrite import atomic_json
from .run import corpus, score_ranking, read_rows

OUT = ROOT / "quality-investigation-v1"
REPORT = Path(__file__).resolve().parents[2] / "docs/reports/mtrag-m3-investigation"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit():
    OUT.mkdir(parents=True, exist_ok=True)
    results = runs()
    cases = []
    counts = Counter()
    for t in tasks_for("validation"):
        old = read(
            QUALITY / "validation" / (fingerprint(["baseline", t["key"]]) + ".json")
        )
        new = read(
            QUALITY
            / "validation"
            / (fingerprint(["add_original_rerank", t["key"]]) + ".json")
        )
        p = pools(t, results)
        gold = set(t["qrels"])
        delta = new["metrics"]["ndcg@10"] - old["metrics"]["ndcg@10"]
        category = (
            "regressed"
            if delta < -1e-12
            else "improved"
            if delta > 1e-12
            else "unchanged"
        )
        added = set(p["add_original_rerank"]) - set(p["baseline"])
        added_top10 = added & set(new["ids"][:10])
        record = {
            "key": t["key"],
            "query_id": t["query_id"],
            "dataset": t["dataset"],
            "domain": t["domain"],
            "last_turn": t["last_turn"],
            "rewritten": t["query"],
            "category": category,
            "delta": delta,
            "same_query": t["last_turn"] == t["query"],
            "original_word_count": len(t["last_turn"].split()),
            "new_positive_candidates": sorted(added & gold),
            "new_top10_unjudged": sorted(added_top10 - gold),
            "lost_top10_positive": sorted(
                (set(old["ids"][:10]) & gold) - set(new["ids"][:10])
            ),
            "new_top10_positive": sorted(
                (set(new["ids"][:10]) & gold) - set(old["ids"][:10])
            ),
            "old_top10": old["ids"][:10],
            "new_top10": new["ids"][:10],
        }
        cases.append(record)
        counts[category] += 1
        counts["same_query_" + category] += int(record["same_query"])
        if category == "regressed":
            counts["regressed_with_added_unjudged_in_top10"] += bool(
                record["new_top10_unjudged"]
            )
            counts["regressed_lost_top10_positive"] += bool(
                record["lost_top10_positive"]
            )
        counts["queries_with_new_positive_candidates"] += bool(
            record["new_positive_candidates"]
        )
    tune = [read(p) for p in (QUALITY / "tune").glob("*.json")]
    steps = {}
    for a, b in (
        ("baseline", "preserve_channels"),
        ("preserve_channels", "add_original_retrieval"),
        ("add_original_retrieval", "add_original_rerank"),
    ):
        deltas = [
            r["variants"][b]["metrics"]["ndcg@10"]
            - r["variants"][a]["metrics"]["ndcg@10"]
            for r in tune
        ]
        means = {
            v: macro([{**r, "metrics": r["variants"][v]["metrics"]} for r in tune])
            for v in (a, b)
        }
        steps[a + " -> " + b] = {
            "macro_delta": means[b] - means[a],
            "improved": sum(d > 1e-12 for d in deltas),
            "regressed": sum(d < -1e-12 for d in deltas),
            "unchanged": sum(abs(d) <= 1e-12 for d in deltas),
        }
    selected = []
    # Two biggest losses and one biggest gain per dataset/domain; diagnostic sample, not population estimate.
    for dataset, domain in sorted({(c["dataset"], c["domain"]) for c in cases}):
        cell = [c for c in cases if c["dataset"] == dataset and c["domain"] == domain]
        selected.extend(
            sorted(
                (c for c in cell if c["category"] == "regressed"),
                key=lambda c: c["delta"],
            )[:2]
        )
        selected.extend(
            sorted(
                (c for c in cell if c["category"] == "improved"),
                key=lambda c: -c["delta"],
            )[:1]
        )
    atomic_json(
        OUT / "audit.json",
        {
            "validation_counts": counts,
            "tune_step_changes": steps,
            "cases": cases,
            "sample_keys": [c["key"] for c in selected],
        },
    )
    print(
        json.dumps(
            {
                "validation_counts": counts,
                "tune_step_changes": steps,
                "sample_size": len(selected),
            }
        ),
        flush=True,
    )


def probe():
    audit_data = read(OUT / "audit.json")
    tasks = [
        t for t in tasks_for("validation") if t["key"] in audit_data["sample_keys"]
    ]
    histories = {
        r["query_id"]: r["messages"] for r in read_rows(ROOT / "queries.jsonl")
    }
    results = runs()
    model = LocalModel("bge_m3", "reranker", profile())
    for domain in sorted({t["domain"] for t in tasks}):
        texts = {r["_id"]: r["text"] for r in corpus(domain)}
        for t in (x for x in tasks if x["domain"] == domain):
            path = OUT / (fingerprint(t["key"]) + ".json")
            if path.exists():
                continue
            p = pools(t, results)
            rw, _ = score_passages(model, t["query"], p["add_original_rerank"], texts)
            raw = (
                rw
                if t["last_turn"] == t["query"]
                else score_passages(
                    model, t["last_turn"], p["add_original_rerank"], texts
                )[0]
            )
            rankings = {
                v: rank(ids, rw, raw if v == "add_original_rerank" else None)
                for v, ids in p.items()
            }
            metrics = {v: score_ranking(ids, t["qrels"]) for v, ids in rankings.items()}
            important = list(
                dict.fromkeys(
                    list(t["qrels"])
                    + rankings["baseline"][:2]
                    + rankings["add_original_rerank"][:3]
                )
            )
            passages = []
            for pid in important:
                token_count = len(
                    model.tokenizer.encode(texts[pid], add_special_tokens=False)
                )
                passages.append(
                    {
                        "id": pid,
                        "labeled_positive": pid in t["qrels"],
                        "text": texts[pid],
                        "tokens": token_count,
                        "rewritten_score": rw.get(pid),
                        "original_score": raw.get(pid),
                        "ranks": {
                            v: ids.index(pid) + 1 if pid in ids else None
                            for v, ids in rankings.items()
                        },
                    }
                )
            atomic_json(
                path,
                {
                    "key": t["key"],
                    "dataset": t["dataset"],
                    "domain": domain,
                    "original": t["last_turn"],
                    "rewritten": t["query"],
                    "history": histories[t["query_id"]],
                    "metrics": metrics,
                    "rankings": rankings,
                    "passages": passages,
                    "scores": {"rewritten": rw, "original": raw},
                    "note": "All ablations share freshly scored full pool, so fixed-pool ordering changes can be isolated.",
                },
            )
            print("probed", t["query_id"], flush=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    records = [
        read(OUT / (fingerprint(key) + ".json")) for key in audit_data["sample_keys"]
    ]
    atomic_json(REPORT / "probe-results.json", records)
    atomic_json(REPORT / "audit.json", audit_data)
    print("COMPLETE diagnostic sample", len(records), flush=True)


def duplicates():
    """Exact text-equivalence audit; does not edit qrels or replace official metrics."""
    tasks = tasks_for("validation")
    comparisons = []
    for domain in sorted({t["domain"] for t in tasks}):
        selected = [t for t in tasks if t["domain"] == domain]
        rankings, required = {}, set()
        for t in selected:
            required.update(t["qrels"])
            for variant in ("baseline", "add_original_rerank"):
                row = read(
                    QUALITY
                    / "validation"
                    / (fingerprint([variant, t["key"]]) + ".json")
                )
                rankings[(t["key"], variant)] = row["ids"][:10]
                required.update(row["ids"][:10])
        hashes = {}
        with (ROOT / "corpus" / f"{domain}.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if row["_id"] in required:
                    hashes[row["_id"]] = fingerprint(
                        re.sub(r"\s+", " ", row["text"]).strip()
                    )
        for t in selected:
            gold_hash = {hashes[pid]: pid for pid in t["qrels"]}
            for variant in ("baseline", "add_original_rerank"):
                matches = [
                    {
                        "returned_id": pid,
                        "identical_positive_id": gold_hash[hashes[pid]],
                    }
                    for pid in rankings[(t["key"], variant)]
                    if pid not in t["qrels"] and hashes[pid] in gold_hash
                ]
                if matches:
                    comparisons.append(
                        {"key": t["key"], "variant": variant, "matches": matches}
                    )
    result = {
        "method": "exact text equality after whitespace normalization; no semantic relabeling",
        "affected_queries": len({r["key"] for r in comparisons}),
        "per_variant_affected_queries": dict(
            Counter(r["variant"] for r in comparisons)
        ),
        "cases": comparisons,
    }
    REPORT.mkdir(parents=True, exist_ok=True)
    atomic_json(REPORT / "duplicate-evidence-audit.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["audit", "probe", "duplicates"])
    args = parser.parse_args()
    {"audit": audit, "probe": probe, "duplicates": duplicates}[args.stage]()
