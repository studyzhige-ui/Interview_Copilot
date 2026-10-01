"""Export candidate queries and original texts using BEIR's JSONL/qrels shape."""

from __future__ import annotations

import json

from .acquire import OUT, SEED
from .build_questions import RESULT, TITLES

DEST = OUT / "beir"


def main() -> None:
    sources = json.loads(SEED.read_text(encoding="utf-8"))
    questions = [
        json.loads(line)
        for line in RESULT.read_text(encoding="utf-8").splitlines()
        if line
    ]
    (DEST / "qrels").mkdir(parents=True, exist_ok=True)
    corpus = []
    for source in sources:
        content = (OUT / "text" / (source["id"] + ".txt")).read_text(encoding="utf-8")
        corpus.append(
            {"_id": source["id"], "title": TITLES[source["id"]], "text": content}
        )
    (DEST / "corpus.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in corpus),
        encoding="utf-8",
    )
    queries = [{"_id": q["id"], "text": q["question"]} for q in questions]
    (DEST / "queries.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in queries),
        encoding="utf-8",
    )
    for split in ("dev", "calibration", "holdout_candidate"):
        rows = [
            (q["id"], source_id, 1)
            for q in questions
            if q["split"] == split
            for source_id in q["source_ids"]
        ]
        content = "query-id\tcorpus-id\tscore\n" + "".join(
            f"{qid}\t{sid}\t{score}\n" for qid, sid, score in rows
        )
        (DEST / "qrels" / f"{split}.tsv").write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "corpus_documents": len(corpus),
                "queries": len(queries),
                "qrels": sum(len(q["source_ids"]) for q in questions),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
