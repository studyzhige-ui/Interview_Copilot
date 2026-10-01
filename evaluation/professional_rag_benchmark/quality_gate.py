"""Editorial release gate; intentionally rejects the withdrawn draft."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


HERE = Path(__file__).parent


def audit(path: Path) -> dict:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    evidence = Counter(
        (span["source_id"], span["start"], span["end"])
        for row in rows
        for span in row["evidence"]
    )
    generic = sum(
        "what does the document state about" in row["question"].lower()
        or "有哪些要求" in row["question"]
        for row in rows
    )
    compound = [row for row in rows if len(row["evidence"]) > 1]
    reviewed = sum(
        row.get("editorial_review", {}).get("decision") == "accept" for row in rows
    )
    coherent_compound = sum(bool(row.get("composition_rationale")) for row in compound)
    failures = []
    if len(rows) < 400:
        failures.append("fewer than 400 questions")
    if len(evidence) < 320:
        failures.append("fewer than 320 distinct evidence facts")
    if generic:
        failures.append(f"{generic} vague template questions")
    if any(count > 2 for count in evidence.values()):
        failures.append("evidence facts reused more than twice")
    if reviewed != len(rows):
        failures.append(f"{len(rows) - reviewed} questions lack an accept decision")
    if coherent_compound != len(compound):
        failures.append(
            f"{len(compound) - coherent_compound} compound questions lack a composition rationale"
        )
    return {
        "questions": len(rows),
        "distinct_evidence_facts": len(evidence),
        "generic_questions": generic,
        "compound_questions": len(compound),
        "accepted_editorially": reviewed,
        "failures": failures,
    }


if __name__ == "__main__":
    report = audit(HERE / "questions.candidate.jsonl")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(1 if report["failures"] else 0)
