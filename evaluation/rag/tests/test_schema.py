"""Unit tests for the gold-dataset + detail schema loaders/validation (plan §3.1).

Run from the repo root: ``python -m pytest evaluation/rag/tests/ -q``.
"""
from __future__ import annotations

import json

import pytest

from evaluation.rag import schema as s


def _write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


def test_empty_reason_shared_with_retriever():
    """The eval trace schema reuses the retriever's empty_reason enum (one
    definition site) rather than redeclaring it."""
    from app.rag.retrieval_state import EMPTY_REASONS as live
    assert s.EMPTY_REASONS is live
    assert "no_candidates" in s.EMPTY_REASONS


def test_load_jsonl_skips_blanks_and_reports_bad_line(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a": 1}\n\n{"b": 2}\n', encoding="utf-8")
    assert s.load_jsonl(p) == [{"a": 1}, {"b": 2}]

    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"a": 1}\n{not json}\n', encoding="utf-8")
    with pytest.raises(s.DatasetError) as exc:
        s.load_jsonl(bad)
    assert "bad.jsonl:2" in str(exc.value)


def test_load_jsonl_missing_file_raises(tmp_path):
    with pytest.raises(s.DatasetError):
        s.load_jsonl(tmp_path / "nope.jsonl")


def test_retrieval_gold_valid_and_defaults(tmp_path):
    p = _write(tmp_path, "ret.jsonl", [{
        "id": "ret_001", "query": "Redis 缓存雪崩怎么解决？", "user_id": "eval_user",
        "query_type": "single_query", "expected_chunk_ids": ["dch_1"],
        "expected_content": "过期时间随机化、限流、降级、多级缓存。",
    }])
    [g] = s.load_dataset("retrieval", p)
    assert g.id == "ret_001" and g.expected_chunk_ids == ["dch_1"]
    assert g.min_content_coverage == 0.75      # default
    assert g.expected_node_ids == []           # optional default


def test_retrieval_gold_requires_chunk_ids_and_query_type(tmp_path):
    bad_qt = _write(tmp_path, "a.jsonl", [{
        "id": "r", "query": "q", "user_id": "u", "query_type": "weird",
        "expected_chunk_ids": ["c"], "expected_content": "x",
    }])
    with pytest.raises(s.DatasetError):
        s.load_dataset("retrieval", bad_qt)

    empty_ids = _write(tmp_path, "b.jsonl", [{
        "id": "r", "query": "q", "user_id": "u", "query_type": "single_query",
        "expected_chunk_ids": [], "expected_content": "x",
    }])
    with pytest.raises(s.DatasetError):
        s.load_dataset("retrieval", empty_ids)


def test_planner_gold_valid(tmp_path):
    p = _write(tmp_path, "plan.jsonl", [{
        "id": "plan_001", "user_message": "雪崩和击穿怎么处理？",
        "recent_turns": [{"role": "User", "content": "Redis 缓存异常有哪些？"}],
        "expected_needs_retrieval": True, "expected_dense_contains": ["缓存雪崩"],
        "expected_sparse_terms": ["缓存雪崩"], "expected_sub_query_count": 2,
        "query_type": "multi_query",
    }])
    [g] = s.load_dataset("planner", p)
    assert g.expected_needs_retrieval is True and g.expected_sub_query_count == 2


def test_planner_gold_requires_needs_retrieval(tmp_path):
    p = _write(tmp_path, "plan.jsonl", [{
        "id": "p", "user_message": "q", "query_type": "single_query",
    }])
    with pytest.raises(s.DatasetError):
        s.load_dataset("planner", p)


def test_generation_gold_valid(tmp_path):
    p = _write(tmp_path, "gen.jsonl", [{
        "id": "gen_001", "query": "缓存雪崩方案？", "query_type": "single_query",
        "expected_chunk_ids": ["dch_1"], "expected_content": "随机化、限流、降级。",
        "reference_answer_points": ["过期时间随机化", "限流降级"],
        "expected_citation_required": True, "expected_refusal": False,
    }])
    [g] = s.load_dataset("generation", p)
    assert g.reference_answer_points == ["过期时间随机化", "限流降级"]
    assert g.expected_citation_required is True


def test_generation_gold_requires_chunk_ids(tmp_path):
    """Empty expected_chunk_ids is rejected (symmetric with RetrievalGold)."""
    p = _write(tmp_path, "gen.jsonl", [{
        "id": "g", "query": "q", "query_type": "single_query",
        "expected_chunk_ids": [], "expected_content": "x",
        "reference_answer_points": ["p"],
    }])
    with pytest.raises(s.DatasetError):
        s.load_dataset("generation", p)


def test_bad_case_valid_and_enum_checks(tmp_path):
    good = _write(tmp_path, "bad.jsonl", [{
        "id": "bad_001", "query": "q", "query_type": "single_query",
        "failure_type": "missed_recall", "expected_behavior": "应召回 chunk X",
        "status": "open",
    }])
    [c] = s.load_dataset("bad_cases", good)
    assert c.failure_type == "missed_recall" and c.status == "open"

    bad_ft = _write(tmp_path, "bad2.jsonl", [{
        "id": "b", "query": "q", "query_type": "single_query",
        "failure_type": "not_a_type", "expected_behavior": "x", "status": "open",
    }])
    with pytest.raises(s.DatasetError):
        s.load_dataset("bad_cases", bad_ft)


def test_unknown_dataset_kind_raises(tmp_path):
    with pytest.raises(s.DatasetError):
        s.load_dataset("nope", tmp_path / "x.jsonl")


def test_base_detail_carries_required_fields():
    row = s.base_detail(sample_id="ret_001", query_type="single_query", status="ok",
                        trace_id="t-1", latency_ms=12.5, recall_at_5=0.8)
    for f in s.DETAIL_REQUIRED_FIELDS:
        assert f in row
    assert row["recall_at_5"] == 0.8  # extra passthrough
