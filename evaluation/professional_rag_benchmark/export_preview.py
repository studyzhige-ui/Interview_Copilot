"""Render the frozen candidate records for human review."""

import json
from pathlib import Path

from .acquire import SEED


HERE = Path(__file__).parent


def main() -> None:
    sources = {row["id"]: row for row in json.loads(SEED.read_text(encoding="utf-8"))}
    questions = [
        json.loads(line)
        for line in (HERE / "questions.candidate.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    lines = [
        "# 400 source-grounded question candidates",
        "",
        "These are programmatic candidates for review, not independently reviewed gold answers.",
        "Each quote is an exact span from the downloaded original text. Offsets are character offsets in the extracted UTF-8 text.",
        "",
    ]
    for row in questions:
        lines += [
            f"## {row['id']} · {row['task_type']}",
            "",
            f"**Question:** {row['question']}",
            "",
            f"**Reference answer:** {row['reference_answer']}",
            "",
            "**Evidence:**",
            "",
        ]
        for span in row["evidence"]:
            source = sources[span["source_id"]]
            lines.append(
                f"- [{span['source_id']}]({source['url']}) · extracted text `{span['start']}:{span['end']}` · SHA-256 `{span['text_sha256']}`: {span['quote']}"
            )
        lines += ["", f"Split: `{row['split']}` · Review: `{row['review_status']}`", ""]
    output = HERE / "QUESTIONS_400.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {"questions": len(questions), "output": str(output)}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
