"""Tests for the lightweight citation check (generation plan §2.5)."""

from __future__ import annotations

from app.services.chat.citation import validate_citations


def _sources(*refs: str) -> list[dict]:
    return [{"ref": r, "chunk_id": f"dch_{r}"} for r in refs]


def test_all_citations_valid():
    report = validate_citations(
        "缓存击穿见 [K1]，缓存雪崩见 [K2]。",
        _sources("K1", "K2"),
        retrieval_hit=True,
    )
    assert report.ok
    assert report.cited_refs == ["K1", "K2"]
    assert report.valid_refs == ["K1", "K2"]
    assert report.invalid_refs == []
    assert report.missing_citation is False


def test_invalid_ref_flagged_not_rewritten():
    report = validate_citations(
        "见 [K1] 和 [K9]。",  # K9 not in sources
        _sources("K1"),
        retrieval_hit=True,
    )
    assert report.invalid_refs == ["K9"]
    assert report.valid_refs == ["K1"]
    assert report.ok is False


def test_missing_citation_when_retrieval_hit():
    report = validate_citations(
        "Redis 缓存击穿是热点 key 失效导致的。",  # no [K#] at all
        _sources("K1", "K2"),
        retrieval_hit=True,
    )
    assert report.missing_citation is True
    assert report.ok is False


def test_no_missing_warning_without_retrieval_hit():
    """A turn with no retrieved evidence isn't expected to cite anything."""
    report = validate_citations(
        "这是一个通用回答。",
        sources=[],
        retrieval_hit=False,
    )
    assert report.missing_citation is False
    assert report.ok is True


def test_duplicate_refs_deduped_in_order():
    report = validate_citations(
        "[K2] ... [K1] ... [K2] again",
        _sources("K1", "K2"),
        retrieval_hit=True,
    )
    assert report.cited_refs == ["K2", "K1"]


def test_empty_sources_with_hit_but_no_refs_is_ok():
    """retrieval_hit True but zero sources (shouldn't happen, but be safe):
    no source refs means nothing to miss."""
    report = validate_citations("answer", sources=[], retrieval_hit=True)
    assert report.missing_citation is False
    assert report.ok is True
