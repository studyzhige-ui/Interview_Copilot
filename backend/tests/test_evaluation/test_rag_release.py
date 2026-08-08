from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from evaluation.rag_release import (
    FIXED_PROFILE,
    _claim_heldout_once,
    _current_runtime_contract,
    _retrieval_failures,
    apply_release_profile,
    evaluation_code_sha256,
    load_release_profile,
    profile_sha256,
)


def _write_report(
    path: Path,
    *,
    profile: dict[str, object],
    device: str = "cuda",
    release_ready: bool = True,
    status: str = "completed",
) -> None:
    path.write_text(
        json.dumps(
            {
                "release_ready": release_ready,
                "status": status,
                "device": device,
                "selected_profile": profile,
                "selected_profile_sha256": profile_sha256(profile),
                "run_identity": {
                    "evaluation_code_sha256": evaluation_code_sha256(),
                    "runtime_contract": _current_runtime_contract(),
                },
            }
        ),
        encoding="utf-8",
    )


def test_fixed_release_profile_matches_community_defaults() -> None:
    assert FIXED_PROFILE == {
        "chunk_tokens": 384,
        "chunk_overlap": 64,
        "candidate_count": 20,
        "final_count": 3,
    }
    assert settings.RAG_CHUNK_TOKENS == FIXED_PROFILE["chunk_tokens"]
    assert settings.RAG_CHUNK_OVERLAP == FIXED_PROFILE["chunk_overlap"]
    assert settings.RAG_CANDIDATE_COUNT == FIXED_PROFILE["candidate_count"]
    assert settings.RAG_FINAL_COUNT == FIXED_PROFILE["final_count"]


def test_load_release_profile_requires_fixed_cuda_result(tmp_path: Path) -> None:
    profile = {**FIXED_PROFILE, "min_score": 0.87, "score_margin": 0.01}
    path = tmp_path / "cuda.json"
    _write_report(path, profile=profile)

    assert load_release_profile(path) == (profile, profile_sha256(profile), "cuda")

    _write_report(path, profile=profile, device="cpu")
    with pytest.raises(ValueError, match="CUDA"):
        load_release_profile(path)

    changed = {**profile, "chunk_tokens": 320}
    _write_report(path, profile=changed)
    with pytest.raises(ValueError, match="fixed Community profile"):
        load_release_profile(path)


def test_load_release_profile_requires_calibrated_gate(tmp_path: Path) -> None:
    path = tmp_path / "cuda.json"
    _write_report(path, profile=dict(FIXED_PROFILE))

    with pytest.raises(ValueError, match="calibrated evidence gate"):
        load_release_profile(path)


def test_load_release_profile_rejects_runtime_drift(tmp_path: Path) -> None:
    profile = {**FIXED_PROFILE, "min_score": 0.87, "score_margin": 0.01}
    path = tmp_path / "cuda.json"
    _write_report(path, profile=profile)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["run_identity"]["runtime_contract"]["reranker_model"] = "changed"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="runtime contract"):
        load_release_profile(path)


@pytest.mark.parametrize(
    ("release_ready", "status"),
    [(False, "completed"), (True, "failed"), (True, "heldout_running")],
)
def test_load_release_profile_rejects_non_release_reports(
    tmp_path: Path,
    release_ready: bool,
    status: str,
) -> None:
    profile = {**FIXED_PROFILE, "min_score": 0.87, "score_margin": 0.01}
    path = tmp_path / "cuda.json"
    _write_report(
        path,
        profile=profile,
        release_ready=release_ready,
        status=status,
    )

    with pytest.raises(ValueError, match="completed, release-ready"):
        load_release_profile(path)


def test_apply_release_profile_includes_calibrated_evidence_gate() -> None:
    target = SimpleNamespace(
        RAG_CHUNK_TOKENS=1,
        RAG_CHUNK_OVERLAP=0,
        RAG_CANDIDATE_COUNT=1,
        RAG_FINAL_COUNT=1,
        RAG_MIN_SCORE=0.0,
        RAG_SCORE_MARGIN=None,
    )

    apply_release_profile(
        target,
        {**FIXED_PROFILE, "min_score": 0.89, "score_margin": 0.02},
    )

    assert target.RAG_CHUNK_TOKENS == 384
    assert target.RAG_CHUNK_OVERLAP == 64
    assert target.RAG_CANDIDATE_COUNT == 20
    assert target.RAG_FINAL_COUNT == 3
    assert target.RAG_MIN_SCORE == 0.89
    assert target.RAG_SCORE_MARGIN == 0.02


def test_release_failure_details_only_keep_answerable_reranker_misses() -> None:
    failures = _retrieval_failures(
        {
            "per_sample_details": [
                {
                    "id": "miss",
                    "expected_retrieval": True,
                    "reranked_passage_hit_at_3": 0,
                },
                {
                    "id": "hit",
                    "expected_retrieval": True,
                    "reranked_passage_hit_at_3": 1,
                },
                {
                    "id": "negative",
                    "expected_retrieval": False,
                    "reranked_passage_hit_at_3": None,
                },
            ]
        }
    )

    assert [item["id"] for item in failures] == ["miss"]


def test_heldout_campaign_cannot_be_reopened_with_another_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "evaluation.rag_release.CAMPAIGN_LEDGER_ROOT",
        tmp_path / "campaigns",
    )
    _claim_heldout_once(
        campaign_fingerprint="campaign",
        output=tmp_path / "first.json",
        selected_profile_sha256="profile",
    )

    with pytest.raises(RuntimeError, match="already opened"):
        _claim_heldout_once(
            campaign_fingerprint="campaign",
            output=tmp_path / "other.json",
            selected_profile_sha256="profile",
        )
