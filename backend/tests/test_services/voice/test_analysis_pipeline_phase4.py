"""Phase 4 analysis-pipeline behaviors: span extraction (ANA-2), reused
qa_pairs (ANA-1), grading-failure policy (ANA-6)."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.voice import interview_analysis_service as svc


def _resp(payload) -> SimpleNamespace:
    return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))


class _FakeLLM:
    def __init__(self, acomplete):
        self.acomplete = acomplete


# ── ANA-2: span coercion / slicing ───────────────────────────────────────


def test_coerce_ranges_accepts_single_and_multi():
    assert svc._coerce_ranges([3, 5]) == [(3, 5)]
    assert svc._coerce_ranges([[1, 2], [4, 6]]) == [(1, 2), (4, 6)]
    assert svc._coerce_ranges([["2", "3"]]) == [(2, 3)]
    assert svc._coerce_ranges([[5, 2]]) == [(2, 5)]  # swapped bounds tolerated
    assert svc._coerce_ranges("nope") == []
    assert svc._coerce_ranges([]) == []
    assert svc._coerce_ranges([["a", "b"]]) == []


def test_slice_lines_clamps_out_of_window_ranges():
    lines = ["L1 text", "L2 text", "L3 text"]
    assert svc._slice_lines(lines, [(2, 2)], 0) == "L2 text"
    assert svc._slice_lines(lines, [(2, 99)], 0) == "L2 text\nL3 text"
    assert svc._slice_lines(lines, [(90, 99)], 0) == ""
    # offset: global line 12 maps to local index 1 when offset=10
    assert svc._slice_lines(lines, [(12, 12)], 10) == "L2 text"


def test_extraction_slices_original_text_from_spans():
    """The LLM outputs only line spans; the pipeline must return the exact
    original transcript text (fidelity by construction)."""
    transcript = (
        "**[Speaker 1]**: 请做个自我介绍。\n"
        "**[Speaker 2]**: 我叫张三，做了五年后端。\n"
        "**[Speaker 2]**: 主要用 Go 和 Python。\n"
        "**[Speaker 1]**: 讲讲你对索引的理解？\n"
        "**[Speaker 2]**: B+ 树……\n"
    )
    payload = {
        "qa_pairs": [
            {
                "question_lines": [[1, 1]],
                "answer_lines": [[2, 3]],
                "question_summary": "自我介绍",
                "phase": "self_intro",
                "is_follow_up": False,
                "parent_qa_index": None,
            },
            {
                "question_lines": [4, 4],  # single-range shorthand
                "answer_lines": [[5, 5]],
                "question_summary": "索引理解",
                "phase": "technical",
                "is_follow_up": False,
                "parent_qa_index": None,
            },
        ]
    }
    llm = _FakeLLM(AsyncMock(return_value=_resp(payload)))

    from app.core import llm_client_factory

    pairs = asyncio.run(
        svc._extract_single_pass(
            [ln for ln in transcript.split("\n") if ln.strip()],
            llm=llm,
        )
    )
    assert len(pairs) == 2
    assert pairs[0]["question"] == "**[Speaker 1]**: 请做个自我介绍。"
    assert pairs[0]["answer"] == (
        "**[Speaker 2]**: 我叫张三，做了五年后端。\n**[Speaker 2]**: 主要用 Go 和 Python。"
    )
    assert pairs[1]["question_summary"] == "索引理解"
    # The numbered transcript (not raw) went into the prompt.
    prompt_sent = llm.acomplete.await_args.args[0]
    assert "L1|" in prompt_sent and "L5|" in prompt_sent


def test_extraction_drops_pairs_with_invented_lines():
    payload = {
        "qa_pairs": [
            {"question_lines": [[100, 120]], "answer_lines": [[130, 140]],
             "question_summary": "hallucinated", "phase": "general"},
        ]
    }
    llm = _FakeLLM(AsyncMock(return_value=_resp(payload)))
    pairs = asyncio.run(svc._extract_single_pass(["only line"], llm=llm))
    assert pairs == []


# ── ANA-1: analyze_interview reuses pre-extracted pairs ──────────────────


def test_analyze_interview_skips_extraction_when_pairs_given(monkeypatch):
    async def _boom(*a, **k):
        raise AssertionError("extraction must not run when qa_pairs are given")

    monkeypatch.setattr(svc, "extract_qa_pairs_with_llm", _boom)

    graded = {
        "score": 7, "critique": "还行", "improved_answer": "", "tags": [],
    }
    synthesis = {
        "overall": {"score": 7, "summary": "ok", "strengths": [], "weaknesses": [],
                    "key_growth_areas": []},
        "phase_summary": [], "skill_radar": {},
    }
    calls = {"n": 0}

    async def _acomplete(prompt, **kwargs):
        calls["n"] += 1
        # per-question calls then the synthesis call
        return _resp(graded if "评分" not in prompt or True else synthesis) \
            if calls["n"] <= 1 else _resp(synthesis)

    monkeypatch.setattr(
        svc, "get_llm_for_role", lambda role, user_id=None: _FakeLLM(_acomplete),
    )

    report = asyncio.run(svc.analyze_interview(
        "transcript text",
        qa_pairs=[{
            "index": 1, "question": "Q1", "answer": "A1", "phase": "technical",
        }],
    ))
    assert report["per_question"], report


# ── ANA-6: failed grading is 未评分, not a silent zero ────────────────────


def test_failed_question_scores_none_not_zero(monkeypatch):
    monkeypatch.setattr(svc, "_ANALYSIS_RETRY_BASE_S", 0.0)
    llm = _FakeLLM(AsyncMock(side_effect=RuntimeError("provider 500")))
    out = asyncio.run(svc._analyze_single_question(
        {"index": 3, "question": "Q", "answer": "A", "phase": "technical"},
        context_text="", total_questions=5, llm=llm,
    ))
    assert out["score"] is None
    assert out["analysis_failed"] is True
    # retried before giving up
    assert llm.acomplete.await_count == svc._ANALYSIS_MAX_ATTEMPTS


def test_retry_succeeds_on_second_attempt(monkeypatch):
    monkeypatch.setattr(svc, "_ANALYSIS_RETRY_BASE_S", 0.0)
    ok = _resp({"score": 8, "critique": "好", "improved_answer": "", "tags": []})
    llm = _FakeLLM(AsyncMock(side_effect=[RuntimeError("blip"), ok]))
    out = asyncio.run(svc._analyze_single_question(
        {"index": 1, "question": "Q", "answer": "A", "phase": "technical"},
        context_text="", total_questions=1, llm=llm,
    ))
    assert out["score"] == 8.0
    assert "analysis_failed" not in out


def test_synthesis_excludes_failed_and_reports_count():
    per_question = [
        {"index": 1, "phase": "technical", "question": "Q1", "answer": "A1",
         "score": 8.0, "critique": "好", "tags": []},
        {"index": 2, "phase": "technical", "question": "Q2", "answer": "A2",
         "score": None, "critique": "该题分析失败", "tags": [],
         "analysis_failed": True},
    ]
    # Synthesis LLM fails → fallback aggregation path (deterministic).
    llm = _FakeLLM(AsyncMock(side_effect=RuntimeError("down")))
    report = asyncio.run(svc._synthesize_report(per_question, llm=llm))
    assert report["interview_metadata"]["failed_count"] == 1
    # Average over graded only — a silent 0 would have halved it.
    assert report["overall"]["score"] == 8.0
