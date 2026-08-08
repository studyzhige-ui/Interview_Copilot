from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from evaluation.validate_rag_dataset import validate_dataset
from evaluation.index_provenance import validate_manifest_files


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = PROJECT_ROOT / "evaluation" / "rag_dataset.jsonl"
MANIFEST_PATH = PROJECT_ROOT / "evaluation" / "corpus_manifest.json"


def _rows() -> list[dict]:
    return [
        json.loads(line)
        for line in DATASET_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_rag_dataset_stays_broad_and_evidence_anchored() -> None:
    rows = _rows()
    positives = [row for row in rows if row.get("expected_retrieval") is True]
    hard_negatives = [row for row in rows if row.get("expected_retrieval") is False]
    route_negatives = [row for row in rows if row.get("layer") == "trajectory"]
    multi_intent = [
        row for row in positives if int(row.get("expected_intent_count", 0)) > 1
    ]

    assert len(rows) >= 400
    assert len(positives) >= 300
    assert len(hard_negatives) >= 40
    assert len(route_negatives) >= 20
    assert len(multi_intent) >= 10
    assert len({row["domain"] for row in positives}) >= 20
    assert {row["language"] for row in rows} == {"en", "zh"}
    assert len({row["id"] for row in rows}) == len(rows)
    formats = {
        Path(source).suffix.lower()
        for row in positives
        for source in row.get("source_files") or [row["source_file"]]
    }
    assert ".pdf" in formats
    assert len(formats - {".pdf"}) >= 3

    for row in positives:
        assert row.get("relevant_document_ids")
        assert row.get("reference_terms")
        assert 1 <= len(row.get("evidence_groups") or []) <= 3
        assert row.get("split") in {"calibration", "test"}
        assert row["expected_planner_retrieval"] is True
        assert row["expected_intent_count"] >= 1

        sources = row.get("source_files") or [row["source_file"]]
        assert len(row["relevant_document_ids"]) == len(sources)
        for group in row["evidence_groups"]:
            assert group["source_file"] in sources
            assert "all_of" not in group
            assert group["alternatives"]
            for alternative in group["alternatives"]:
                assert 1 <= len(alternative["all_of"]) <= 2

    assert any(
        len(group["alternatives"]) > 1
        for row in positives
        for group in row["evidence_groups"]
    )

    for row in rows:
        expected_retrieval = row.get("expected_planner_retrieval")
        if expected_retrieval is None:
            expected_retrieval = True
        expected_count = row.get("expected_intent_count")
        if expected_count is not None:
            assert isinstance(expected_count, int)
            assert expected_count >= int(bool(expected_retrieval))

    for row in multi_intent:
        assert row["split"] == "test"
        assert row["layer"] == "all"
        assert len(row["source_files"]) >= 2
        assert not row.get("source_file")
        assert len(row["relevant_document_ids"]) == len(row["source_files"])
        assert {group["source_file"] for group in row["evidence_groups"]} == set(
            row["source_files"]
        )

    splits_by_source: dict[str, set[str]] = {}
    for row in positives:
        for source in row.get("source_files") or [row["source_file"]]:
            splits_by_source.setdefault(source, set()).add(row["split"])
    assert all(len(splits) == 1 for splits in splits_by_source.values())

    splits_by_semantic_group: dict[str, set[str]] = {}
    for row in rows:
        if group := row.get("semantic_group"):
            splits_by_semantic_group.setdefault(group, set()).add(row["split"])
    assert all(len(splits) == 1 for splits in splits_by_semantic_group.values())


def test_rag_dataset_sources_are_pinned_in_manifest() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest_files = {document["file"] for document in manifest["documents"]}
    dataset_files = {
        source
        for row in _rows()
        if row.get("expected_retrieval") is True
        for source in row.get("source_files") or [row["source_file"]]
    }

    assert len(manifest_files) >= 20
    assert dataset_files == manifest_files
    assert all(document.get("sha256") for document in manifest["documents"])


def test_rag_dataset_release_validator_passes() -> None:
    result = validate_dataset()

    assert result["rows"] >= 400
    assert result["multi_document"] >= 10
    assert result["source_documents"] == 25
    assert result["evidence_alternatives"] >= result["evidence_groups"]
    assert result["ragas_formal_samples"] == 50


def test_formal_sample_is_balanced_and_contains_multi_document_cases() -> None:
    manifest = json.loads(
        (PROJECT_ROOT / "evaluation" / "ragas_formal_sample.json").read_text(
            encoding="utf-8"
        )
    )
    by_id = {row["id"]: row for row in _rows()}
    selected = [by_id[row_id] for row_id in manifest["sample_ids"]]

    assert Counter(row["language"] for row in selected) == {"zh": 25, "en": 25}
    assert Counter(row["difficulty"] for row in selected) == {
        "basic": 16,
        "intermediate": 17,
        "advanced": 17,
    }
    assert sum(row["expected_intent_count"] == 2 for row in selected) == 4


def test_corpus_files_match_pinned_hashes() -> None:
    corpus_dir = PROJECT_ROOT / "data" / "evaluation" / "corpus"
    if not corpus_dir.is_dir():
        pytest.skip("release corpus is downloaded by the explicit evaluation setup")
    result = validate_manifest_files()

    assert len(result["entries"]) >= 20
    assert result["fingerprint"]


def test_manifest_file_validation_uses_actual_content(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    source = corpus_dir / "sample.md"
    source.write_text("pinned content", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "file": source.name,
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = validate_manifest_files(corpus_dir, manifest_path=manifest)
    assert result["entries"] == [
        {"file": "sample.md", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    ]

    source.write_text("modified", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate_manifest_files(corpus_dir, manifest_path=manifest)
