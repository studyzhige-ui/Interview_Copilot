from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent_runtime.tool_registry import AgentToolContext
from app.agent_runtime.tools import career


NOW = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)


class _Session:
    def close(self) -> None:
        return None


class _Profile:
    def model_dump(self, *, mode: str):
        assert mode == "json"
        return {"id": "cp-owner", "version": 4, "directions": []}


def _opportunity(opportunity_id: str, *, title: str):
    return SimpleNamespace(
        id=opportunity_id,
        user_id=17,
        company_name="Example",
        job_title=title,
        location="Shanghai",
        team="Platform",
        source_url="https://jobs.example.test/role",
        source_provider="lever",
        external_job_id="job-42",
        external_application_id=None,
        phase="in_process",
        current_step="面试中",
        outcome=None,
        archived_at=None,
        last_event_at=NOW,
        direction_version=0,
        direction_links=[],
        created_at=NOW,
        updated_at=NOW,
    )


def _event(index: int):
    return SimpleNamespace(
        id=f"pe-{index}",
        job_opportunity_id="jo-canonical",
        sequence=index,
        operation="assert",
        kind="hiring_step",
        occurred_at=NOW + timedelta(minutes=index),
        observed_at=NOW + timedelta(minutes=index),
        source_kind="user_assertion",
        source_identity=f"message-{index}",
        source_version=None,
        description=f"step {index}",
        step_summary=f"第 {index} 步",
        analysis_context_json={},
        jd_snapshot_id=None,
        jd_snapshot_version=None,
        corrects_event_id=None,
        created_at=NOW + timedelta(minutes=index),
    )


def test_event_history_requires_an_explicit_opportunity():
    with pytest.raises(ValidationError, match="opportunity_id"):
        career.CareerContextArgs(include_events=True)


def test_read_resolves_active_merge_and_returns_bounded_events_and_current_jd(
    monkeypatch,
):
    calls: dict[str, object] = {}
    active_merge = SimpleNamespace(
        id="jom-active",
        duplicate_opportunity_id="jo-duplicate",
        canonical_opportunity_id="jo-canonical",
        status="active",
        version=2,
        reason="same posting",
        confirmation_source_identity="message-10",
        created_at=NOW,
        updated_at=NOW,
    )
    retracted_merge = SimpleNamespace(
        id="jom-retracted",
        duplicate_opportunity_id="jo-old",
        canonical_opportunity_id="jo-canonical",
        status="retracted",
        version=3,
        reason="incorrect merge",
        confirmation_source_identity="message-11",
        created_at=NOW,
        updated_at=NOW,
    )
    jd = SimpleNamespace(
        id="jds-current",
        job_opportunity_id="jo-canonical",
        version=3,
        original_url="https://jobs.example.test/role?utm_source=x",
        normalized_url="https://jobs.example.test/role",
        observed_at=NOW,
        provider="lever",
        canonical_content="Python, distributed systems, and ownership.",
        content_checksum="sha256:jd-current",
        source_kind="tool_result",
        source_identity="call-search-detail",
        source_version="receipt-3",
        created_at=NOW,
    )

    monkeypatch.setattr(career, "SessionLocal", _Session)
    monkeypatch.setattr(
        career, "get_career_profile", lambda _db, *, user_pk: _Profile()
    )

    def list_merges(_db, *, user_pk):
        calls["merge_user_pk"] = user_pk
        return [active_merge, retracted_merge]

    def list_opportunities(
        _db,
        *,
        user_pk,
        include_archived,
        limit,
        offset=0,
    ):
        calls["opportunity_args"] = (user_pk, include_archived, limit, offset)
        return [
            _opportunity("jo-duplicate", title="Duplicate Backend"),
            _opportunity("jo-canonical", title="Backend Engineer"),
        ]

    def list_events(_db, *, user_pk, opportunity_id):
        calls["event_scope"] = (user_pk, opportunity_id)
        return [_event(index) for index in range(1, 8)]

    def current_jd(_db, *, user_pk, opportunity_id, at_or_before=None):
        calls["jd_scope"] = (user_pk, opportunity_id, at_or_before)
        return jd

    monkeypatch.setattr(career, "list_opportunity_merges", list_merges)
    monkeypatch.setattr(career, "list_job_opportunities", list_opportunities)
    monkeypatch.setattr(career, "list_process_events", list_events)
    monkeypatch.setattr(career, "current_job_description_snapshot", current_jd)
    monkeypatch.setattr(career, "list_next_actions", lambda *_args, **_kwargs: [])

    result = asyncio.run(
        career.read_career_context(
            career.CareerContextArgs(
                opportunity_id="jo-duplicate",
                include_events=True,
                event_limit=3,
            ),
            AgentToolContext(
                user_id="owner",
                user_pk=17,
                session_id="conversation-owner",
                turn_id="turn-owner",
            ),
        )
    )

    assert calls["merge_user_pk"] == 17
    assert calls["event_scope"] == (17, "jo-canonical")
    assert calls["jd_scope"] == (17, "jo-canonical", None)
    assert result["selected_opportunity_id"] == "jo-canonical"
    assert [row["id"] for row in result["job_opportunities"]] == ["jo-canonical"]
    assert result["job_opportunity_merges"] == [
        {
            "id": "jom-active",
            "duplicate_opportunity_id": "jo-duplicate",
            "canonical_opportunity_id": "jo-canonical",
            "status": "active",
            "version": 2,
            "reason": "same posting",
            "confirmation_source_identity": "message-10",
            "created_at": NOW,
            "updated_at": NOW,
        }
    ]
    assert [row["sequence"] for row in result["process_events"]] == [5, 6, 7]
    assert result["job_description_snapshot"]["id"] == "jds-current"
    assert result["job_description_snapshot"]["canonical_content"].startswith("Python")


def test_read_without_selected_opportunity_does_not_load_events_or_jd(monkeypatch):
    monkeypatch.setattr(career, "SessionLocal", _Session)
    monkeypatch.setattr(
        career,
        "get_career_profile",
        lambda _db, *, user_pk: _Profile(),
    )
    monkeypatch.setattr(career, "list_opportunity_merges", lambda *_a, **_k: [])
    monkeypatch.setattr(career, "list_job_opportunities", lambda *_a, **_k: [])
    monkeypatch.setattr(career, "list_next_actions", lambda *_a, **_k: [])
    monkeypatch.setattr(
        career,
        "list_process_events",
        lambda *_a, **_k: pytest.fail("unselected history must not be loaded"),
    )
    monkeypatch.setattr(
        career,
        "current_job_description_snapshot",
        lambda *_a, **_k: pytest.fail("unselected JD must not be loaded"),
    )

    result = asyncio.run(
        career.read_career_context(
            career.CareerContextArgs(),
            AgentToolContext(
                user_id="owner",
                user_pk=17,
                session_id="conversation-owner",
            ),
        )
    )
    assert result["process_events"] == []
    assert result["job_description_snapshot"] is None
