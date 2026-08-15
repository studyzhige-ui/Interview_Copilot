"""Scoring starts only after auditable QA projection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.interview.analysis import service as svc


class _FakeLLM:
    def __init__(self, acomplete):
        self.acomplete = acomplete


def test_raw_transcript_cannot_trigger_legacy_extraction() -> None:
    with pytest.raises(ValueError, match="v2 transcript evidence"):
        asyncio.run(svc.analyze_interview("untrusted raw transcript"))


def test_analyze_interview_routes_preverified_pairs_to_scoring(monkeypatch) -> None:
    expected = {"overall": {"score": 8.0}}
    analyze = AsyncMock(return_value=expected)
    monkeypatch.setattr(svc, "analyze_qa_batched", analyze)
    pairs = [{"question": "Q", "answer": "A", "phase": "technical"}]

    result = asyncio.run(svc.analyze_interview("display only", qa_pairs=pairs))

    assert result == expected
    assert analyze.await_args.args[0] == pairs


def test_failed_batch_is_ungraded_instead_of_silent_zero(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_ANALYSIS_RETRY_BASE_S", 0.0)
    llm = _FakeLLM(AsyncMock(side_effect=RuntimeError("provider 500")))

    result = asyncio.run(
        svc._analyze_batch(
            [
                {"index": 1, "question": "Q1", "answer": "A1", "phase": "technical"},
                {"index": 2, "question": "Q2", "answer": "A2", "phase": "technical"},
            ],
            [],
            [],
            resume_context="",
            jd_context="",
            llm=llm,
        )
    )

    assert [item["score"] for item in result] == [None, None]
    assert all(item["analysis_failed"] is True for item in result)


def test_deterministic_synthesis_keeps_real_zero_and_excludes_failures() -> None:
    questions = [
        {
            "index": 1,
            "phase": "technical",
            "question": "Q1",
            "answer": "A1",
            "score": 0.0,
            "critique": "错误",
            "tags": [],
        },
        {
            "index": 2,
            "phase": "technical",
            "question": "Q2",
            "answer": "A2",
            "score": None,
            "critique": "未评分",
            "tags": [],
            "analysis_failed": True,
        },
    ]
    llm = _FakeLLM(AsyncMock(side_effect=RuntimeError("down")))

    report = asyncio.run(svc._synthesize_report(questions, llm=llm))

    assert report["overall"]["score"] == 0.0
    assert report["generation_status"] == "partial"
