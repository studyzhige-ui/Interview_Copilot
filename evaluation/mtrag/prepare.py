"""Adapt only official task inputs and qrels; validate against full passage IDs."""

import csv
import hashlib
import json
import zipfile
from collections import defaultdict

from .download import ROOT
from .profile import fingerprint, load_profile
from .rewrite import request_body

DOMAINS = ("clapnq", "cloud", "fiqa", "govt")


def main():
    corpus_dir = ROOT / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    ids = {}
    corpus_summary = {}
    for domain in DOMAINS:
        ids[domain] = set()
        empty = []
        target = corpus_dir / f"{domain}.jsonl"
        with zipfile.ZipFile(
            ROOT / "upstream/corpora/passage_level" / f"{domain}.jsonl.zip"
        ) as z:
            with z.open(f"{domain}.jsonl") as source, target.open("wb") as output:
                for line in source:
                    row = json.loads(line)
                    if row["_id"] in ids[domain]:
                        raise ValueError(f"Duplicate ID: {domain} {row['_id']}")
                    if not row["text"].strip():
                        empty.append(row["_id"])
                    ids[domain].add(row["_id"])
                    output.write(line)
        corpus_summary[domain] = {
            "passages": len(ids[domain]),
            "empty_passages": empty,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
    tasks, queries, summary = [], [], {}
    errors = []
    for dataset in ("mtrag-human", "mtragun-human"):
        reference = ROOT / "upstream" / dataset / "generation_tasks/reference.jsonl"
        source_tasks = [
            json.loads(line)
            for line in reference.read_text(encoding="utf-8").splitlines()
        ]
        by_id = {row["task_id"]: row for row in source_tasks}
        if len(by_id) != len(source_tasks):
            raise ValueError("Duplicate task IDs")
        domain_counts = {}
        for domain in DOMAINS:
            rel_path = (
                f"{domain}/qrels/dev.tsv"
                if dataset == "mtrag-human"
                else f"qrels/{domain}.tsv"
            )
            qrels = defaultdict(dict)
            path = ROOT / "upstream" / dataset / "retrieval_tasks" / rel_path
            for rel in csv.DictReader(path.open(encoding="utf-8"), delimiter="\t"):
                qid, pid, score = rel["query-id"], rel["corpus-id"], int(rel["score"])
                if score <= 0:
                    continue
                if pid not in ids[domain]:
                    errors.append(
                        {"dataset": dataset, "domain": domain, "qid": qid, "pid": pid}
                    )
                qrels[qid][pid] = max(score, qrels[qid].get(pid, 0))
            domain_counts[domain] = len(qrels)
            for qid, rels in qrels.items():
                row = by_id[qid]
                if domain not in row["Collection"].lower():
                    raise ValueError(f"Domain mismatch {qid}")
                messages = [
                    {
                        "role": {"user": "user", "agent": "assistant"}[m["speaker"]],
                        "content": m["text"],
                    }
                    for m in row["input"]
                ]
                query = {"query_id": f"{dataset}::{qid}", "messages": messages}
                request_body(query, load_profile())
                queries.append(query)
                tasks.append(
                    {
                        "query_id": query["query_id"],
                        "official_task_id": qid,
                        "dataset": dataset,
                        "domain": domain,
                        "conversation_id": row["conversation_id"],
                        "turn": int(row["turn"]),
                        "last_turn": messages[-1]["content"],
                        "qrels": rels,
                        "answerability": row.get(
                            "Answerability", row.get("answerability")
                        ),
                        "question_type": row.get("Question Type"),
                        "multi_turn": row.get("Multi-Turn"),
                        "standalone_type": row.get("Standalone Type"),
                        "input_sha256": fingerprint(messages),
                    }
                )
        summary[dataset] = {
            "published_tasks": len(source_tasks),
            "retrieval_tasks": domain_counts,
            "included": sum(domain_counts.values()),
            "excluded_without_positive_qrels": len(source_tasks)
            - sum(domain_counts.values()),
            "source_fields": sorted(set().union(*(r.keys() for r in source_tasks))),
        }
    if errors:
        (ROOT / "alignment_errors.json").write_text(
            json.dumps(errors, indent=2), encoding="utf-8"
        )
        raise ValueError(
            f"{len(errors)} qrels missing from official passages; see alignment_errors.json"
        )
    for filename, rows in (("queries.jsonl", queries), ("tasks.jsonl", tasks)):
        with (ROOT / filename).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    sets = {
        name: {row["input_sha256"] for row in tasks if row["dataset"] == name}
        for name in summary
    }
    convs = {
        name: {row["conversation_id"] for row in tasks if row["dataset"] == name}
        for name in summary
    }
    audit = {
        "corpora": corpus_summary,
        "datasets": summary,
        "total_queries": len(queries),
        "unique_inputs": len({row["input_sha256"] for row in tasks}),
        "cross_dataset_identical_inputs": len(set.intersection(*sets.values())),
        "cross_dataset_shared_conversation_ids": len(set.intersection(*convs.values())),
        "qrel_alignment_errors": len(errors),
        "tasks_sha256": hashlib.sha256((ROOT / "tasks.jsonl").read_bytes()).hexdigest(),
        "queries_sha256": hashlib.sha256(
            (ROOT / "queries.jsonl").read_bytes()
        ).hexdigest(),
    }
    (ROOT / "data_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
