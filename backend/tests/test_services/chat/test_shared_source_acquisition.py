from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.conversation.chat_strategy import ChatPipelineStrategy
from app.conversation.strategy import StrategyContext, StrategyResult
from app.models.chat import Conversation, ConversationMessage
from app.models.user import User
from app.rag.grounding.builder import grounding_builder
from app.rag.domain.models import SearchIntent
from app.services.chat import shared_source_acquisition as acquisition
from app.services.chat.context_assembly_pipeline import AssembledContext
from app.services.chat.source_requests import (
    ArtifactSourceRequest,
    CareerDomainSourceRequest,
    HistorySourceRequest,
    ObservationSourceRequest,
    explicit_source_requests_from_object_references,
    extract_explicit_urls,
    fallback_source_requests,
)
from tests.conftest import NoCloseSession


def test_explicit_urls_are_deterministic_and_never_silently_truncated():
    assert extract_explicit_urls(
        "比较 https://example.com/a 和 https://example.com/a，"
        "再看 https://jobs.example.org/role?id=7。以及 https://third.test/x "
        "和 https://ignored.test/y"
    ) == (
        "https://example.com/a",
        "https://jobs.example.org/role?id=7",
        "https://third.test/x",
        "https://ignored.test/y",
    )


def test_admitted_typed_refs_become_exact_deduplicated_owner_requests():
    requests = explicit_source_requests_from_object_references(
        [
            {"kind": "job_opportunity", "object_id": "job-7"},
            {"kind": "job_opportunity", "object_id": "job-7"},
            {"kind": "artifact", "object_id": "artifact-3"},
            {"kind": "unknown", "object_id": "ignored"},
        ]
    )

    assert len(requests) == 2
    assert requests[0].kind == "career_domains"
    assert requests[0].reference_kind == "job_opportunity"
    assert requests[0].object_ids == ["job-7"]
    assert requests[0].include_process_events is True
    assert requests[1].kind == "artifacts"
    assert requests[1].artifact_ids == ["artifact-3"]


def test_fallback_requests_remain_closed_and_current_task_shaped():
    requests = fallback_source_requests("看看我之前的 Gmail 邮件和简历，申请进度如何")
    assert [request.kind for request in requests] == [
        "history",
        "observations",
        "artifacts",
        "career_domains",
    ]
    career = requests[-1]
    assert set(career.sections) == {"job_opportunities"}


def test_explicit_url_becomes_citable_versioned_source_result():
    async def fake_reader(url: str):
        assert url == "https://example.test/job"
        return {
            "url": "https://example.test/job?canonical=1",
            "title": "Backend Engineer",
            "content": "[External web content]\nRole requirements and salary.",
            "truncated": False,
        }

    bundle = asyncio.run(
        acquisition.acquire_shared_read_only_sources(
            user_id="owner",
            user_pk=7,
            session_id="conversation-1",
            turn_id="turn-1",
            current_query="分析这个岗位",
            explicit_urls=("https://example.test/job",),
            url_reader=fake_reader,
        )
    )

    assert bundle.attempted is True
    assert bundle.explicit_failures == ()
    assert bundle.result.state.retrieval_hit is True
    chunk = bundle.result.chunks[0]
    assert chunk["source_kind"] == "web_url"
    assert chunk["original_url"] == "https://example.test/job"
    assert chunk["source_url"] == "https://example.test/job?canonical=1"
    assert chunk["source_version"].startswith("sha256:")
    assert chunk["observed_at"]

    grounding = grounding_builder.build(bundle.result, token_budget=1_000)
    assert grounding.sources[0]["source_url"].endswith("canonical=1")
    assert grounding.sources[0]["source_version"] == chunk["source_version"]
    assert grounding.sources[0]["observed_at"] == chunk["observed_at"]


def test_explicit_url_failure_is_typed_and_never_citable():
    async def failed_reader(_url: str):
        return {"error": "refused by safety check: private address"}

    bundle = asyncio.run(
        acquisition.acquire_shared_read_only_sources(
            user_id="owner",
            user_pk=7,
            session_id="conversation-1",
            turn_id="turn-1",
            current_query="读取它",
            explicit_urls=("http://127.0.0.1/private",),
            url_reader=failed_reader,
        )
    )

    assert bundle.result.chunks == []
    assert bundle.result.state.retrieval_hit is False
    assert bundle.explicit_failures[0]["identity"] == "http://127.0.0.1/private"
    assert "private address" in bundle.explicit_failures[0]["detail"]
    assert '"status": "failed"' in bundle.status_manifest


def test_fourth_explicit_url_is_a_typed_failure_not_a_silent_drop():
    calls = []

    async def fake_reader(url: str):
        calls.append(url)
        return {"url": url, "title": url, "content": f"content for {url}"}

    urls = tuple(f"https://example.test/{index}" for index in range(4))
    bundle = asyncio.run(
        acquisition.acquire_shared_read_only_sources(
            user_id="owner",
            user_pk=7,
            session_id="conversation-1",
            turn_id="turn-overflow",
            current_query="read four URLs",
            explicit_urls=urls,
            url_reader=fake_reader,
        )
    )

    assert calls == list(urls[:3])
    assert len(bundle.result.chunks) == 3
    assert bundle.explicit_failures == (
        {
            "kind": "url",
            "identity": "explicit_url_overflow",
            "status": "failed",
            "detail": "Explicit URL limit is 3; 1 additional URL(s) were not read",
            "source_version": None,
            "observed_at": None,
            "explicit": True,
            "count": 1,
        },
    )


def test_missing_explicit_owner_source_is_typed_failure(monkeypatch, db_session):
    monkeypatch.setattr(acquisition, "SessionLocal", lambda: NoCloseSession(db_session))
    monkeypatch.setattr(
        acquisition.artifact_service,
        "list_artifacts",
        lambda *_args, **_kwargs: [],
    )
    bundle = asyncio.run(
        acquisition.acquire_shared_read_only_sources(
            user_id="owner",
            user_pk=7,
            session_id="conversation-1",
            turn_id="turn-owner-missing",
            current_query="read attached artifact",
            explicit_requests=(
                ArtifactSourceRequest(
                    query="artifact-missing",
                    artifact_ids=["artifact-missing"],
                    limit=1,
                ),
            ),
        )
    )

    assert bundle.result.chunks == []
    assert bundle.explicit_failures[0]["kind"] == "artifacts"
    assert bundle.explicit_failures[0]["identity"] == "artifact-missing"
    assert bundle.explicit_failures[0]["explicit"] is True


def test_explicit_owner_boundary_failure_remains_typed(monkeypatch):
    def fail_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(acquisition, "SessionLocal", fail_session)
    bundle = asyncio.run(
        acquisition.acquire_shared_read_only_sources(
            user_id="owner",
            user_pk=7,
            session_id="conversation-1",
            turn_id="turn-owner-boundary",
            current_query="read attached artifact",
            explicit_requests=(
                ArtifactSourceRequest(
                    query="artifact-7",
                    artifact_ids=["artifact-7"],
                    limit=1,
                ),
            ),
        )
    )

    assert bundle.result.chunks == []
    assert bundle.explicit_failures[0]["identity"] == "artifact-7"
    assert bundle.explicit_failures[0]["explicit"] is True
    assert "source boundary failed" in bundle.explicit_failures[0]["detail"]


def test_history_request_reads_exact_owned_record(monkeypatch, db_session):
    owner = User(username="shared-history-owner", hashed_password="x")
    other = User(username="shared-history-other", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.flush()
    owned = Conversation(
        id="shared-history-owned",
        user_id=owner.id,
        title="缓存复盘",
        type="debrief",
    )
    foreign = Conversation(
        id="shared-history-foreign",
        user_id=other.id,
        title="其他用户",
        type="general",
    )
    db_session.add_all([owned, foreign])
    db_session.flush()
    db_session.add_all(
        [
            ConversationMessage(
                conversation_id=owned.id,
                seq=1,
                role="User",
                content="我们确认过蓝鲸缓存策略。",
            ),
            ConversationMessage(
                conversation_id=foreign.id,
                seq=1,
                role="User",
                content="蓝鲸 foreign secret",
            ),
        ]
    )
    db_session.flush()
    monkeypatch.setattr(
        acquisition,
        "SessionLocal",
        lambda: NoCloseSession(db_session),
    )

    bundle = asyncio.run(
        acquisition.acquire_shared_read_only_sources(
            user_id=owner.username,
            user_pk=owner.id,
            session_id=owned.id,
            turn_id="turn-history",
            current_query="这个对话之前的蓝鲸结论",
            requests=(
                HistorySourceRequest(
                    query="蓝鲸",
                    scope="current_conversation",
                    limit=3,
                ),
            ),
        )
    )

    assert len(bundle.result.chunks) == 1
    text = bundle.result.chunks[0]["text"]
    assert "我们确认过蓝鲸缓存策略" in text
    assert "foreign secret" not in text
    assert bundle.result.chunks[0]["source_kind"] == "interaction_record"


def test_owner_helpers_read_named_services_with_bounded_projections(monkeypatch):
    observed_at = datetime(2026, 8, 13, tzinfo=timezone.utc)
    observation_calls = []
    artifact_calls = []
    profile_calls = []

    def list_observations(_db, **kwargs):
        observation_calls.append(kwargs)
        return [
            {
                "id": "observation-1",
                "version": 2,
                "latest_snapshot": {
                    "id": "snapshot-2",
                    "subject": "Interview invitation",
                    "snapshot_version": "gmail-history:2",
                    "observed_at": observed_at,
                },
            },
            {
                "id": "observation-2",
                "version": 1,
                "latest_snapshot": {
                    "id": "snapshot-1",
                    "subject": "Interview follow-up",
                    "snapshot_version": "gmail-history:1",
                    "observed_at": observed_at,
                },
            },
        ]

    artifact = SimpleNamespace(id="artifact-1", kind="resume", archived_at=None)
    version = SimpleNamespace(
        id="artifact-version-3",
        version_no=3,
        title="Backend resume",
        content_text="Python and distributed systems",
        content_format="markdown",
        file_asset_id="file-1",
        file_asset_version="sha256:file-v1",
        origin_kind="conversation_attachment",
        created_at=observed_at,
    )

    def list_artifacts(_db, **kwargs):
        artifact_calls.append(kwargs)
        return [(artifact, version)]

    profile = SimpleNamespace(
        id="profile-1",
        version=4,
        updated_at=observed_at,
        model_dump=lambda **_kwargs: {
            "id": "profile-1",
            "headline": "Backend engineer",
            "version": 4,
        },
    )

    def get_career_profile(_db, **kwargs):
        profile_calls.append(kwargs)
        return profile

    monkeypatch.setattr(
        acquisition.gmail_observation_service,
        "list_observations",
        list_observations,
    )
    monkeypatch.setattr(
        acquisition.artifact_service,
        "list_artifacts",
        list_artifacts,
    )
    monkeypatch.setattr(
        acquisition.career_profile_service,
        "get_career_profile",
        get_career_profile,
    )
    intent = SearchIntent(intent_id="shared:test", query="current sources")

    observation_chunks = acquisition._read_observations(
        object(),
        request=ObservationSourceRequest(query="邮件", limit=1),
        intent=intent,
        user_pk=17,
    )
    artifact_chunks = acquisition._read_artifacts(
        object(),
        request=ArtifactSourceRequest(query="简历", limit=1),
        intent=intent,
        user_pk=17,
    )
    domain_chunks = acquisition._read_career_domains(
        object(),
        request=CareerDomainSourceRequest(
            query="个人详情",
            sections=["career_profile"],
            limit=1,
        ),
        intent=intent,
        user_pk=17,
    )

    assert observation_calls == [{"user_pk": 17, "statuses": None, "limit": 50}]
    assert artifact_calls == [{"user_pk": 17, "include_archived": False, "limit": 100}]
    assert profile_calls == [{"user_pk": 17}]
    assert [chunk["source_kind"] for chunk in observation_chunks] == [
        "gmail_observation"
    ]
    assert [chunk["source_kind"] for chunk in artifact_chunks] == ["artifact_version"]
    assert [chunk["source_kind"] for chunk in domain_chunks] == ["career_profile"]
    assert artifact_chunks[0]["file_asset_id"] == "file-1"
    assert artifact_chunks[0]["file_asset_version"] == "sha256:file-v1"


def test_chat_blocks_before_model_when_explicit_url_read_failed():
    strategy = ChatPipelineStrategy()
    assembled = AssembledContext(
        sources=[{"ref": "K1", "document_title": "successful sibling"}]
    )
    ctx = StrategyContext(
        user_id="owner",
        user_pk=7,
        session_id="conversation-1",
        turn_id="turn-1",
        user_message="分析这个 URL",
        assembled=assembled,
        needs_knowledge_retrieval=True,
        extras={
            "explicit_source_failures": [
                {
                    "kind": "url",
                    "identity": "https://blocked.example/job",
                    "detail": "HTTP 403",
                }
            ]
        },
    )
    result = StrategyResult()

    async def collect():
        return [event async for event in strategy.execute(ctx, result)]

    events = asyncio.run(collect())
    assert result.outcome == "blocked"
    assert "https://blocked.example/job" in result.final_answer
    assert "HTTP 403" in result.final_answer
    assert assembled.sources == []
    assert [event.type.value for event in events] == ["status", "text_delta"]
