"""Validate provenance and mechanical integrity of the new candidate benchmark."""

from __future__ import annotations

import csv
import hashlib
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from .build import OUT, RAW


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def validate() -> dict:
    corpus = load_jsonl(OUT / "corpus.jsonl")
    queries = load_jsonl(OUT / "queries.jsonl")
    answers = load_jsonl(OUT / "answers.jsonl")
    sources = load_jsonl(OUT / "sources.jsonl")
    errors: list[str] = []
    docs = {row["_id"]: row for row in corpus}
    questions = {row["_id"]: row for row in queries}
    labels = {row["query_id"]: row for row in answers}
    source_map = {row["source_id"]: row for row in sources}
    if (
        len(docs) != len(corpus)
        or len(questions) != len(queries)
        or len(labels) != len(answers)
    ):
        errors.append("Duplicate document, question, or answer IDs")
    if set(questions) != set(labels):
        errors.append("Question and answer IDs differ")
    if set(docs) != set(source_map):
        errors.append("Corpus and source IDs differ")
    if len(queries) < 400:
        errors.append("Fewer than 400 questions")
    languages = Counter(row["language"] for row in queries)
    if set(languages) != {"zh", "en"} or abs(languages["zh"] - languages["en"]) > 20:
        errors.append("Question languages are not approximately balanced")
    if len(docs) < 30:
        errors.append("Fewer than 30 occupations")
    normalized = [
        unicodedata.normalize("NFKC", row["text"]).casefold().strip() for row in queries
    ]
    if len(normalized) != len(set(normalized)):
        errors.append("Duplicate normalized questions")

    for source in sources:
        for item in source["files"]:
            path = RAW / item["file"]
            if not path.is_file():
                errors.append(f"Missing original file: {path.name}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                errors.append(f"Source hash mismatch: {path.name}")
    groups: dict[str, set[str]] = defaultdict(set)
    for row in queries:
        groups[row["split_group"]].add(row["split"])
        if row["language"] != row["source_language"]:
            errors.append(f"Question/source language mismatch: {row['_id']}")
        if row["split_group"] not in docs:
            errors.append(f"Unknown split group: {row['_id']}")
        if row["_id"] not in labels:
            continue
        label = labels[row["_id"]]
        if label["review_status"] != "programmatic_candidate":
            errors.append(f"Unexpected review state: {row['_id']}")
        if label["answerability"] != "answerable" or not label["answer"].strip():
            errors.append(f"Invalid answer: {row['_id']}")
        for evidence in label["evidence"]:
            doc = docs.get(evidence["corpus_id"])
            expected = evidence.get("text", label["answer"])
            if (
                doc is None
                or doc["text"][evidence["start"] : evidence["end"]] != expected
            ):
                errors.append(f"Evidence span mismatch: {row['_id']}")
    if any(len(splits) != 1 for splits in groups.values()):
        errors.append("Occupation group crosses splits")

    qrel_ids: set[str] = set()
    qrel_pairs: set[tuple[str, str]] = set()
    qrel_targets: dict[str, set[str]] = defaultdict(set)
    for split in ("dev", "calibration", "test"):
        with (OUT / "qrels" / f"{split}.tsv").open(
            encoding="utf-8", newline=""
        ) as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if reader.fieldnames != ["query-id", "corpus-id", "score"]:
                errors.append(f"Invalid qrels header: {split}")
            for row in reader:
                qid = row["query-id"]
                pair = (qid, row["corpus-id"])
                if pair in qrel_pairs:
                    errors.append(f"Duplicate qrel pair: {qid}, {row['corpus-id']}")
                qrel_pairs.add(pair)
                qrel_ids.add(qid)
                qrel_targets[qid].add(row["corpus-id"])
                if qid not in questions or questions[qid]["split"] != split:
                    errors.append(f"Qrel split mismatch: {qid}")
                if row["corpus-id"] not in docs or row["score"] != "1":
                    errors.append(f"Invalid qrel target/score: {qid}")
                if qid in labels and row["corpus-id"] not in {
                    e["corpus_id"] for e in labels[qid]["evidence"]
                }:
                    errors.append(f"Qrel/evidence mismatch: {qid}")
    if qrel_ids != set(questions):
        errors.append("Qrels do not cover all questions")
    for qid, label in labels.items():
        if qrel_targets[qid] != {e["corpus_id"] for e in label["evidence"]}:
            errors.append(f"Qrels do not cover all evidence documents: {qid}")

    report = {
        "valid": not errors,
        "errors": errors,
        "documents": len(corpus),
        "questions": len(queries),
        "languages": dict(languages),
        "splits": dict(Counter(row["split"] for row in queries)),
        "task_types": dict(Counter(row["task_type"] for row in queries)),
        "review_status": "programmatic_candidate",
    }
    (OUT / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    result = validate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)
