"""Mechanical checks for the source-grounded question candidate set."""

from __future__ import annotations

import json
from collections import Counter

from .acquire import LOCK, OUT, SEED
from .build_questions import RESULT, clean_answer


def main() -> None:
    sources = json.loads(SEED.read_text(encoding="utf-8"))
    locked = [
        json.loads(line)
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line
    ]
    questions = [
        json.loads(line)
        for line in RESULT.read_text(encoding="utf-8").splitlines()
        if line
    ]
    source_by_id = {source["id"]: source for source in sources}
    hash_by_id = {source["id"]: source["text_sha256"] for source in locked}
    contents = {
        source["id"]: (OUT / "text" / (source["id"] + ".txt")).read_text(
            encoding="utf-8"
        )
        for source in sources
    }
    assert len(questions) == 400
    assert (
        len({q["id"] for q in questions})
        == len({q["question"] for q in questions})
        == 400
    )
    assert Counter(q["language"] for q in questions) == {"en": 200, "zh": 200}
    expected_types = {
        "single_fact": 252,
        "long_span_single_source": 84,
        "long_span_multi_source": 16,
        "multi_source_multi_intent": 48,
    }
    assert Counter(q["task_type"] for q in questions) == expected_types
    assert {sid for q in questions for sid in q["source_ids"]} == set(source_by_id)
    source_splits = {}
    for question in questions:
        evidence = question["evidence"]
        assert question["review_status"] == "programmatic_candidate"
        assert question["split"] in ("dev", "calibration", "holdout_candidate")
        assert question["answerability"] == "full"
        assert len(evidence) == question["intent_count"]
        assert question["source_ids"] == list(
            dict.fromkeys(e["source_id"] for e in evidence)
        )
        assert all(
            source_by_id[sid]["language"] == question["language"]
            for sid in question["source_ids"]
        )
        if question["task_type"] in (
            "multi_source_multi_intent",
            "long_span_multi_source",
        ):
            assert len(question["source_ids"]) == 2
        else:
            assert len(question["source_ids"]) == 1
        for part in evidence:
            content = contents[part["source_id"]]
            assert 0 <= part["start"] < part["end"] <= len(content)
            assert content[part["start"] : part["end"]] == part["quote"]
            assert part["text_sha256"] == hash_by_id[part["source_id"]]
            assert (
                clean_answer(part["quote"], question["language"])
                in question["reference_answer"]
            )
            source_splits.setdefault(part["source_id"], set()).add(question["split"])
        if question["task_type"] in (
            "long_span_single_source",
            "long_span_multi_source",
        ):
            assert evidence[0]["source_id"] == evidence[1]["source_id"]
            assert evidence[1]["start"] - evidence[0]["end"] >= 800
    assert all(len(splits) == 1 for splits in source_splits.values())
    print(
        json.dumps(
            {
                "questions": len(questions),
                "languages": dict(Counter(q["language"] for q in questions)),
                "types": dict(Counter(q["task_type"] for q in questions)),
                "covered_sources": len(source_by_id),
                "evidence_spans": sum(len(q["evidence"]) for q in questions),
                "splits": dict(Counter(q["split"] for q in questions)),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
