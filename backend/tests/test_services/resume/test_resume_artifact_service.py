from __future__ import annotations

import uuid

import pytest

from app.models.artifact import Artifact, ArtifactResumeState, ArtifactVersion
from app.models.career_profile import CareerProfileCandidateItem
from app.models.resume import Resume
from app.models.user import User
from app.schemas.career_profile import SkillFactInput
from app.services.career_profile_service import get_career_profile
from app.services.interview.interview_record_service import interview_record_service
from app.services.resume.resume_artifact_service import (
    ExtractedProfileCandidates,
    add_resume_version,
    claim_resume_parse,
    create_resume_artifact,
    list_resume_artifacts,
    mark_parse_state,
    persist_extracted_resume,
    ResumeArtifactStaleVersionError,
)


def _user(db_session) -> User:
    user = User(
        username=f"resume-artifact-{uuid.uuid4().hex}",
        hashed_password="test-hash",
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_resume_production_owner_is_artifact_and_versions_are_append_only(db_session):
    user = _user(db_session)
    first = create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="import-first",
        title="通用简历",
        file_asset_id=None,
        raw_text="Python backend engineer",
        make_default=True,
    )
    updated = add_resume_version(
        db_session,
        user_pk=user.id,
        resume_id=first.artifact.id,
        operation_key="resume-edit-2",
        title="通用简历 v2",
        file_asset_id=None,
        raw_text="Python and Go backend engineer",
    )

    assert db_session.query(Resume).filter(Resume.user_id == user.id).count() == 0
    assert db_session.get(Artifact, first.artifact.id).kind == "resume"
    assert db_session.query(ArtifactResumeState).filter_by(user_id=user.id).count() == 1
    versions = (
        db_session.query(ArtifactVersion)
        .filter(ArtifactVersion.artifact_id == first.artifact.id)
        .order_by(ArtifactVersion.version_no)
        .all()
    )
    assert [row.version_no for row in versions] == [1, 2]
    assert versions[0].content_text == "Python backend engineer"
    assert updated.current_version.content_text == "Python and Go backend engineer"
    assert list_resume_artifacts(db_session, user_pk=user.id)[0].state.is_default
    assert updated.state.parse_version_id == updated.current_version.id


def test_resume_retry_and_parser_state_are_scoped_to_the_current_version(db_session):
    user = _user(db_session)
    first = create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="retry-first",
        title="第一份",
        file_asset_id=None,
        raw_text="v1",
        make_default=True,
    )
    create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="second-resume",
        title="第二份",
        file_asset_id=None,
        raw_text="other",
        make_default=False,
    )
    replay = create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="retry-first",
        title="第一份",
        file_asset_id=None,
        raw_text="v1",
        make_default=True,
    )
    assert replay.artifact.id == first.artifact.id
    assert len(list_resume_artifacts(db_session, user_pk=user.id)) == 2

    claimed = claim_resume_parse(
        db_session,
        user_pk=user.id,
        resume_id=first.artifact.id,
    )
    assert claimed is not None
    assert claimed.state.parse_status == "processing"
    assert (
        claim_resume_parse(
            db_session,
            user_pk=user.id,
            resume_id=first.artifact.id,
        )
        is None
    )

    newer = add_resume_version(
        db_session,
        user_pk=user.id,
        resume_id=first.artifact.id,
        operation_key="retry-new-version",
        title="第一份 v2",
        file_asset_id=None,
        raw_text="v2",
    )
    assert newer.state.parse_status == "pending"
    assert newer.state.parse_version_id == newer.current_version.id
    with pytest.raises(ResumeArtifactStaleVersionError):
        mark_parse_state(
            db_session,
            user_pk=user.id,
            resume_id=first.artifact.id,
            status="failed",
            source_version_id=first.current_version.id,
        )


def test_resume_extraction_creates_noncanonical_profile_candidates(db_session):
    user = _user(db_session)
    resume = create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="import-candidates",
        title="候选简历",
        file_asset_id=None,
        raw_text="Python",
        make_default=True,
    )
    parsed = persist_extracted_resume(
        db_session,
        user_pk=user.id,
        resume_id=resume.artifact.id,
        source_version_id=resume.current_version.id,
        text="Python",
        candidates=ExtractedProfileCandidates(
            facts=[SkillFactInput(kind="skill", name="Python")],
            directions=[],
        ),
    )

    assert parsed.pending_draft_id is not None
    profile = get_career_profile(db_session, user_pk=user.id)
    assert profile.personal_facts == []
    candidate = (
        db_session.query(CareerProfileCandidateItem)
        .filter(CareerProfileCandidateItem.draft_id == parsed.pending_draft_id)
        .one()
    )
    assert candidate.status == "pending"
    assert candidate.payload_json["fact"]["name"] == "Python"


def test_interview_freezes_the_exact_resume_artifact_version(db_session):
    user = _user(db_session)
    resume = create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="interview-version-one",
        title="面试简历",
        file_asset_id=None,
        raw_text="version one",
        make_default=True,
    )
    record = interview_record_service.create_for_mock(
        user_id=user.username,
        resume_artifact_id=resume.artifact.id,
        resume_artifact_version_id=resume.current_version.id,
        resume_text_snapshot="version one",
        db=db_session,
    )
    newer = add_resume_version(
        db_session,
        user_pk=user.id,
        resume_id=resume.artifact.id,
        operation_key="interview-version-two",
        title="面试简历 v2",
        file_asset_id=None,
        raw_text="version two",
    )

    assert newer.current_version.id != resume.current_version.id
    assert record.resume_artifact_id == resume.artifact.id
    assert record.resume_artifact_version_id == resume.current_version.id
    assert record.resume_text_snapshot == "version one"
