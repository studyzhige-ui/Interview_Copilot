"""Validate the checked-in RAG evaluation dataset and its exact evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path(__file__).with_name("rag_dataset.jsonl")
DEFAULT_MANIFEST = Path(__file__).with_name("corpus_manifest.json")
DEFAULT_RAGAS_SAMPLE = Path(__file__).with_name("ragas_formal_sample.json")
DEFAULT_CORPUS_DIR = PROJECT_ROOT / "data" / "evaluation" / "corpus"

_NAVIGATION_TERM = re.compile(
    r"(?:https?://|www\.|\]\(|!\[|\.(?:html?|pdf)(?:[#?]|$)|"
    r"link to this (?:heading|definition)|table of contents)",
    re.IGNORECASE,
)
_TRANSLATION_PAIR_ID = re.compile(r"^(hard-negative-\d+)-(?:zh|en)$")
_DIFFICULTIES = {"basic", "intermediate", "advanced"}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def _source_files(row: dict[str, Any]) -> list[str]:
    if row.get("source_files"):
        return [str(value) for value in row["source_files"]]
    if row.get("source_file"):
        return [str(row["source_file"])]
    return []


def _format_bucket(row: dict[str, Any]) -> str:
    sources = _source_files(row)
    if len(sources) > 1:
        return "multi"
    return Path(sources[0]).suffix.lower().lstrip(".") if sources else "none"


def _canonical_source_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    elif suffix in {".html", ".htm"}:
        from bs4 import BeautifulSoup
        from markdownify import markdownify

        soup = BeautifulSoup(
            path.read_text(encoding="utf-8", errors="replace"), "html.parser"
        )
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        text = markdownify(str(soup)).strip()
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return _normalize(text)


def _meaningful_phrase(phrase: str) -> bool:
    words = re.findall(r"[A-Za-z0-9_][A-Za-z0-9_'-]*", phrase)
    cjk = re.findall(r"[\u3400-\u9fff]", phrase)
    return len(phrase) >= 32 and (len(words) >= 3 or len(cjk) >= 8)


def validate_dataset(
    dataset_path: Path = DEFAULT_DATASET,
    manifest_path: Path = DEFAULT_MANIFEST,
    ragas_sample_path: Path = DEFAULT_RAGAS_SAMPLE,
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
) -> dict[str, Any]:
    rows = _load_jsonl(dataset_path)
    positives = [row for row in rows if row.get("expected_retrieval") is True]
    negatives = [row for row in rows if row.get("expected_retrieval") is False]
    trajectories = [row for row in rows if row.get("layer") == "trajectory"]
    multi_document = [
        row
        for row in positives
        if int(row.get("expected_intent_count") or 0) > 1
        and len(_source_files(row)) > 1
    ]
    errors: list[str] = []

    ids = [str(row.get("id") or "") for row in rows]
    if not ids or any(not row_id for row_id in ids) or len(ids) != len(set(ids)):
        errors.append("dataset ids must be present and unique")
    if len(rows) < 400 or len(positives) < 300 or len(negatives) < 40:
        errors.append("dataset does not meet the minimum breadth contract")
    if {row.get("language") for row in rows} != {"zh", "en"}:
        errors.append("dataset must contain both Chinese and English")
    if len(multi_document) < 10:
        errors.append(
            "dataset needs at least ten multi-intent, multi-document positives"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_files = {str(item["file"]) for item in manifest["documents"]}
    source_texts: dict[str, str] = {}
    if corpus_dir.is_dir():
        for source_file in manifest_files:
            source_path = corpus_dir / source_file
            if not source_path.is_file():
                errors.append(f"missing corpus file: {source_file}")
                continue
            source_texts[source_file] = _canonical_source_text(source_path)

    for row in positives:
        row_id = str(row.get("id") or "<missing>")
        sources = _source_files(row)
        intent_count = row.get("expected_intent_count")
        if row.get("split") not in {"calibration", "test"}:
            errors.append(f"{row_id}: invalid split")
        if row.get("difficulty") not in _DIFFICULTIES:
            errors.append(f"{row_id}: invalid positive difficulty")
        if row.get("expected_planner_retrieval") is not True:
            errors.append(
                f"{row_id}: positive must explicitly require planner retrieval"
            )
        if not isinstance(intent_count, int) or intent_count < 1:
            errors.append(f"{row_id}: missing explicit positive intent count")
        if not sources or len(sources) != len(set(sources)):
            errors.append(f"{row_id}: sources must be present and unique")
        if set(sources) - manifest_files:
            errors.append(f"{row_id}: source is absent from corpus manifest")
        if bool(row.get("source_file")) == bool(row.get("source_files")):
            errors.append(f"{row_id}: use source_file xor source_files")
        document_ids = [str(value) for value in row.get("relevant_document_ids") or []]
        if len(document_ids) != len(sources) or len(document_ids) != len(
            set(document_ids)
        ):
            errors.append(
                f"{row_id}: relevant_document_ids must map one-to-one to sources"
            )
        if intent_count == 1 and len(sources) != 1:
            errors.append(f"{row_id}: single intent must use one source")
        if intent_count > 1 and len(sources) < 2:
            errors.append(f"{row_id}: multi intent must use multiple sources")

        terms = [str(term).strip() for term in row.get("reference_terms") or []]
        if len(terms) < 1 or any(len(term) < 3 for term in terms):
            errors.append(f"{row_id}: invalid reference_terms")

        evidence_groups = row.get("evidence_groups") or []
        if not isinstance(evidence_groups, list) or not 1 <= len(evidence_groups) <= 3:
            errors.append(f"{row_id}: evidence_groups must contain one to three groups")
            continue
        evidence_sources: set[str] = set()
        for index, group in enumerate(evidence_groups):
            source_file = str(group.get("source_file") or "")
            alternatives = group.get("alternatives") or []
            evidence_sources.add(source_file)
            if source_file not in sources:
                errors.append(
                    f"{row_id}: evidence group {index} uses an unrelated source"
                )
            if "all_of" in group:
                errors.append(f"{row_id}: evidence group {index} uses legacy all_of")
            if not isinstance(alternatives, list) or not alternatives:
                errors.append(f"{row_id}: evidence group {index} needs alternatives")
                continue

            seen_alternatives: set[tuple[str, ...]] = set()
            for alternative_index, alternative in enumerate(alternatives):
                phrases = [
                    str(value).strip() for value in alternative.get("all_of") or []
                ]
                if not 1 <= len(phrases) <= 2:
                    errors.append(
                        f"{row_id}: evidence group {index} alternative "
                        f"{alternative_index} needs one or two phrases"
                    )
                signature = tuple(phrases)
                if signature in seen_alternatives:
                    errors.append(
                        f"{row_id}: evidence group {index} has duplicate alternatives"
                    )
                seen_alternatives.add(signature)
                for phrase in phrases:
                    if not _meaningful_phrase(phrase):
                        errors.append(f"{row_id}: weak evidence phrase {phrase!r}")
                    if _NAVIGATION_TERM.search(phrase):
                        errors.append(
                            f"{row_id}: navigation/URL evidence phrase {phrase!r}"
                        )
                    source_text = source_texts.get(source_file)
                    if (
                        source_text is not None
                        and _normalize(phrase).casefold() not in source_text.casefold()
                    ):
                        errors.append(
                            f"{row_id}: evidence phrase is absent from "
                            f"{source_file}: {phrase!r}"
                        )
        if intent_count > 1 and evidence_sources != set(sources):
            errors.append(f"{row_id}: multi-document evidence must cover every source")

    splits_by_source: dict[str, set[str]] = {}
    for row in positives:
        for source in _source_files(row):
            splits_by_source.setdefault(source, set()).add(str(row["split"]))
    leaked_sources = [
        source for source, splits in splits_by_source.items() if len(splits) != 1
    ]
    if leaked_sources:
        errors.append(f"sources cross calibration/test splits: {leaked_sources}")

    splits_by_semantic_group: dict[str, set[str]] = {}
    for row in rows:
        row_id = str(row.get("id") or "")
        match = _TRANSLATION_PAIR_ID.match(row_id)
        group = str(row.get("semantic_group") or (match.group(1) if match else ""))
        if group:
            splits_by_semantic_group.setdefault(group, set()).add(str(row.get("split")))
    leaked_groups = [
        group for group, splits in splits_by_semantic_group.items() if len(splits) != 1
    ]
    if leaked_groups:
        errors.append(f"semantic groups cross calibration/test splits: {leaked_groups}")

    dataset_files = {source for row in positives for source in _source_files(row)}
    if dataset_files != manifest_files:
        errors.append("dataset sources do not exactly match corpus_manifest.json")

    ragas_manifest = json.loads(ragas_sample_path.read_text(encoding="utf-8"))
    dataset_sha = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if ragas_manifest.get("dataset_sha256") != dataset_sha:
        errors.append("RAGAS sample is pinned to a different dataset SHA-256")
    by_id = {str(row["id"]): row for row in rows}
    sample_ids = [str(value) for value in ragas_manifest.get("sample_ids") or []]
    selected = [by_id[row_id] for row_id in sample_ids if row_id in by_id]
    if len(sample_ids) != 50 or len(selected) != 50 or len(set(sample_ids)) != 50:
        errors.append("RAGAS formal sample must resolve to 50 unique rows")
    elif any(
        row.get("split") != "test" or row.get("expected_retrieval") is not True
        for row in selected
    ):
        errors.append("RAGAS formal sample must be answerable and test-only")
    else:
        actual_quotas = {
            "samples": len(selected),
            "language": dict(Counter(str(row["language"]) for row in selected)),
            "difficulty": dict(Counter(str(row["difficulty"]) for row in selected)),
            "source_format": dict(Counter(_format_bucket(row) for row in selected)),
            "intent_count": dict(
                Counter(str(row["expected_intent_count"]) for row in selected)
            ),
        }
        declared = ragas_manifest.get("quotas") or {}
        if any(declared.get(key) != value for key, value in actual_quotas.items()):
            errors.append("RAGAS formal sample quotas do not match selected rows")
        if actual_quotas["language"] != {"zh": 25, "en": 25}:
            errors.append("RAGAS formal sample must be 25 Chinese and 25 English")
        if actual_quotas["difficulty"] != {
            "basic": 16,
            "intermediate": 17,
            "advanced": 17,
        }:
            errors.append("RAGAS formal sample difficulty quotas changed")
        if actual_quotas["intent_count"].get("2", 0) < 4:
            errors.append("RAGAS formal sample needs four multi-document rows")

    if errors:
        raise ValueError("RAG dataset validation failed:\n- " + "\n- ".join(errors))
    return {
        "dataset_sha256": dataset_sha,
        "rows": len(rows),
        "answerable": len(positives),
        "unanswerable": len(negatives),
        "trajectory_only": len(trajectories),
        "multi_document": len(multi_document),
        "languages": dict(Counter(str(row["language"]) for row in rows)),
        "difficulties": dict(Counter(str(row["difficulty"]) for row in positives)),
        "source_formats": dict(Counter(_format_bucket(row) for row in positives)),
        "source_documents": len(dataset_files),
        "evidence_groups": sum(len(row["evidence_groups"]) for row in positives),
        "evidence_alternatives": sum(
            len(group["alternatives"])
            for row in positives
            for group in row["evidence_groups"]
        ),
        "ragas_formal_samples": len(selected),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ragas-sample", type=Path, default=DEFAULT_RAGAS_SAMPLE)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    args = parser.parse_args()
    print(
        json.dumps(
            validate_dataset(
                args.dataset.resolve(),
                args.manifest.resolve(),
                args.ragas_sample.resolve(),
                args.corpus_dir.resolve(),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
