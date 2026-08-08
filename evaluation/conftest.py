"""Read-only quality gates for reports produced by the official CLI."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(scope="session")
def evaluation_report() -> dict[str, Any]:
    configured = os.getenv("RAG_EVAL_REPORT", "").strip()
    if not configured:
        pytest.skip(
            "Set RAG_EVAL_REPORT to an eval_runner report directory or report.json."
        )
    path = Path(configured).resolve()
    if path.is_dir():
        path = path / "report.json"
    if not path.is_file():
        pytest.fail(f"RAG evaluation report does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    run = payload.get("run") or {}
    expected_dataset_sha = hashlib.sha256(
        (Path(__file__).with_name("rag_dataset.jsonl")).read_bytes()
    ).hexdigest()
    expected_manifest_sha = hashlib.sha256(
        (Path(__file__).with_name("corpus_manifest.json")).read_bytes()
    ).hexdigest()
    if run.get("dataset_sha256") != expected_dataset_sha:
        pytest.fail("Selected report belongs to a different RAG dataset")
    if run.get("corpus_manifest_sha256") != expected_manifest_sha:
        pytest.fail("Selected report belongs to a different corpus manifest")
    from evaluation.rag_release import evaluation_code_sha256

    if run.get("evaluation_code_sha256") != evaluation_code_sha256():
        pytest.fail("Selected report belongs to a different evaluation code contract")
    if payload.get("generation") is not None:
        from evaluation.ragas_runner import _generation_contract_sha256

        if run.get("generation_contract_sha256") != _generation_contract_sha256():
            pytest.fail("Selected report belongs to a different generation contract")
        if not run.get("ragas_evaluation_contract"):
            pytest.fail("Formal report does not identify its RAGAS contract")
        if not run.get("release_run_fingerprint"):
            pytest.fail("Formal report is not bound to a CUDA release campaign")
    if payload.get("retrieval") is not None or payload.get("generation") is not None:
        from evaluation.index_provenance import validate_evaluation_index

        current_index = validate_evaluation_index()
        reported_index = run.get("index_provenance") or {}
        if reported_index.get("fingerprint") != current_index.get("fingerprint"):
            pytest.fail("Selected report belongs to a different evaluation index")
    return payload


def _layer(report: dict[str, Any], name: str) -> dict[str, Any]:
    payload = report.get(name)
    if not isinstance(payload, dict):
        pytest.skip(f"The selected report has no {name} layer.")
    return payload


@pytest.fixture(scope="session")
def retrieval_metrics(evaluation_report: dict[str, Any]) -> dict[str, Any]:
    return _layer(evaluation_report, "retrieval")


@pytest.fixture(scope="session")
def generation_metrics(evaluation_report: dict[str, Any]) -> dict[str, Any]:
    return _layer(evaluation_report, "generation")


@pytest.fixture(scope="session")
def trajectory_metrics(evaluation_report: dict[str, Any]) -> dict[str, Any]:
    return _layer(evaluation_report, "trajectory")
