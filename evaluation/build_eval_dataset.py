import json
import re
from pathlib import Path

import fitz


import sys
from pathlib import Path

# Resolve the repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Add backend/ to the Python import path.
sys.path.append(str(PROJECT_ROOT / "backend"))

from app.core.config import settings

# Use configured runtime data directories.
EVAL_DIR = Path(settings.EVAL_DIR)
UPLOAD_DIR = Path(settings.STORAGE_DIR) / "uploads"
OUTPUT_PATH = EVAL_DIR / "eval_dataset.jsonl"


QUESTION_RE = re.compile(r"[？?]\s*$")


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def is_question_heading(line: str) -> bool:
    line = normalize_line(line)
    if not line:
        return False
    if len(line) < 6 or len(line) > 120:
        return False
    if not QUESTION_RE.search(line):
        return False
    return True


def split_qa_pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    current_question: str | None = None
    current_answer: list[str] = []

    for raw_line in text.splitlines():
        line = normalize_line(raw_line)
        if not line:
            continue

        if is_question_heading(line):
            if current_question and current_answer:
                answer = "\n".join(current_answer).strip()
                if len(answer) >= 120:
                    pairs.append((current_question, answer))
            current_question = line
            current_answer = []
            continue

        if current_question:
            current_answer.append(line)

    if current_question and current_answer:
        answer = "\n".join(current_answer).strip()
        if len(answer) >= 120:
            pairs.append((current_question, answer))

    return pairs


def extract_pdf_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    return "\n".join(page.get_text() for page in doc)


def build_dataset() -> list[dict]:
    rows: list[dict] = []

    for pdf_path in sorted(UPLOAD_DIR.glob("*.pdf")):
        text = extract_pdf_text(pdf_path)
        qa_pairs = split_qa_pairs(text)

        for idx, (question, answer) in enumerate(qa_pairs, start=1):
            rows.append(
                {
                    "id": f"{pdf_path.stem}-{idx:04d}",
                    "question": question,
                    "reference": answer,
                    "source_file": pdf_path.name,
                    "source_type": "interview_qa",
                }
            )

    return rows


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = build_dataset()

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "dataset_path": str(OUTPUT_PATH),
        "samples": len(rows),
        "files": len(list(UPLOAD_DIR.glob("*.pdf"))),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
