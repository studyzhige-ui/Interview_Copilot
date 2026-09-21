"""One user journey: saved facts/JD -> review -> export -> pinned practice."""

import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.models.user import User
from app.models.artifact import ArtifactVersion
from app.models.career_profile import CareerProfile
from app.career.application.resumes import resume_artifact_service as resumes
from app.interviews.application import preparation as service, mock_flow
from app.schemas.mock_preparation import MockPreparationRequest


@pytest.fixture
def sources(db_session):
    user = User(username=f"prep-{uuid.uuid4().hex}", hashed_password="test")
    db_session.add(user)
    db_session.flush()
    text = "Python API project: built retries and audited failures.\n负责 PostgreSQL 数据库事务与并发控制。\nVolunteer coaching."
    saved = resumes.create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="resume-prep",
        make_default=True,
        title="Source resume",
        file_asset_id=None,
        raw_text=text,
    )
    jd = "Build Python APIs with reliable retries.\n熟悉 PostgreSQL 数据库事务。\nKubernetes administration required."
    return user, saved, text, jd


def command(sources, **updates):
    return MockPreparationRequest(
        resume_id=sources[1].artifact.id, jd_text=sources[3], **updates
    )


def test_sources_are_exact_and_preview_never_creates_or_confirms_facts(
    db_session, sources
):
    user, saved, text, jd = sources
    before = db_session.query(ArtifactVersion).count()
    facts = db_session.query(CareerProfile).count()
    result = service.build_preparation(
        db_session, user_pk=user.id, command=command(sources)
    )
    assert result == service.build_preparation(
        db_session, user_pk=user.id, command=command(sources)
    )
    assert result.start_request.resume_version_id == saved.current_version.id
    assert result.resume_sha256 == service.content_hash(text)
    assert result.jd_sha256 == service.content_hash(jd)
    assert result.items[0].evidence_candidates[0].text == text.splitlines()[0]
    assert result.items[-1].status == "evidence_not_located"
    assert result.items[-1].evidence_candidates == []
    for item in result.items:
        assert (
            jd[item.requirement.start : item.requirement.end] == item.requirement.text
        )
        for quote in item.evidence_candidates:
            assert text[quote.start : quote.end] == quote.text
        assert len(item.practice_focus) <= 1000
    for quote in result.resume_excerpts:
        assert text[quote.start : quote.end] == quote.text
    assert "不是能力" in result.disclaimer
    assert result.snapshot_id in result.markdown
    assert db_session.query(ArtifactVersion).count() == before
    assert db_session.query(CareerProfile).count() == facts


def test_other_owner_and_archived_resume_cannot_enter_preparation(db_session, sources):
    user, saved, _, _ = sources
    with pytest.raises(resumes.ResumeArtifactNotFoundError):
        service.build_preparation(
            db_session, user_pk=user.id + 100, command=command(sources)
        )
    resumes.archive_resume_artifact(
        db_session, user_pk=user.id, resume_id=saved.artifact.id
    )
    with pytest.raises(resumes.ResumeArtifactNotFoundError):
        service.build_preparation(db_session, user_pk=user.id, command=command(sources))


def test_replaced_resume_or_edited_jd_is_rejected_before_model_or_run_creation(
    db_session, sources, monkeypatch
):
    user, saved, text, jd = sources
    brief = service.build_preparation(
        db_session, user_pk=user.id, command=command(sources)
    )
    model = Mock(side_effect=AssertionError("must reject before model"))
    monkeypatch.setattr(mock_flow.mock_interview_service, "generate_plan", model)
    resumes.add_resume_version(
        db_session,
        user_pk=user.id,
        resume_id=saved.artifact.id,
        operation_key="replace",
        title="New source",
        file_asset_id=None,
        raw_text=text + "\nNew version.",
    )
    payload = brief.start_request.model_dump(exclude={"input_mode"})
    with pytest.raises(service.PreparationSourceChanged):
        mock_flow.start_mock(db_session, username=user.username, **payload)
    model.assert_not_called()
    with pytest.raises(service.PreparationSourceChanged):
        service.check_preparation_sources(
            brief.start_request,
            resume_version_id=saved.current_version.id,
            resume_text=text,
            jd_text=jd + "changed",
        )
    # A changed parse result under the same version also fails the content fence.
    with pytest.raises(service.PreparationSourceChanged):
        service.check_preparation_sources(
            brief.start_request,
            resume_version_id=saved.current_version.id,
            resume_text=text + "changed",
            jd_text=jd,
        )


def test_source_fence_schema_pairing_and_hashes():
    base = {"purpose": "focused_practice", "focus": "transactions"}
    for extras in (
        {"resume_version_id": "v"},
        {"resume_sha256": "0" * 64},
        {"resume_version_id": "v", "resume_sha256": "0" * 64},
        {"jd_sha256": "0" * 64},
        {"jd_sha256": "not-a-hash"},
    ):
        with pytest.raises(ValidationError):
            MockPreparationRequest(**base, **extras)


def test_capacity_is_explicit_and_excerpt_partition_does_not_drop_long_lines():
    text = "abc" * 600
    result = service._excerpts(text, "r", maximum=3)
    assert "".join(x.text for x in result) == text
    assert all(text[x.start : x.end] == x.text for x in result)
    with pytest.raises(ValueError, match="capacity"):
        service._excerpts("a\n" * 129, "r", maximum=128)


def test_http_and_application_use_identical_scoped_operation(db_session, sources):
    from app.api.interviews.preparation import router
    from app.core.security import get_current_user
    from app.db.database import get_db

    user, _, _, _ = sources
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db_session
    expected = service.build_preparation(
        db_session, user_pk=user.id, command=command(sources)
    )
    with TestClient(app) as client:
        response = client.post(
            "/mock-interviews/preparation", json=command(sources).model_dump()
        )
        assert response.status_code == 200
        assert response.json() == expected.model_dump(mode="json")
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user.id + 100
        )
        assert (
            client.post(
                "/mock-interviews/preparation", json=command(sources).model_dump()
            ).status_code
            == 404
        )
