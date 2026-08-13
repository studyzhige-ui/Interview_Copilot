"""Resume intake reads only canonical Artifact state."""

from __future__ import annotations

import asyncio

import pytest

from app.models.resume import Resume
from app.models.user import User
from app.services.interview import analysis_intake
from app.services.resume import resume_artifact_service


def _user(db_session) -> User:
    user = User(username="alice", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return user


def test_resume_intake_accepts_migration_alias_but_reads_artifact_version(
    db_session,
):
    user = _user(db_session)
    resume = resume_artifact_service.create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="analysis-resume",
        title="迁移后的简历",
        file_asset_id=None,
        raw_text="canonical resume text",
        make_default=True,
    )
    resume.state.legacy_resume_id = "rsm_migrated"
    db_session.add(resume.state)
    db_session.commit()

    context = asyncio.run(
        analysis_intake.resolve_resume_context(
            db_session,
            user_id="alice",
            resume_id="rsm_migrated",
            resume_file_asset_id=None,
        )
    )

    assert context.resume_artifact_id == resume.artifact.id
    assert context.resume_artifact_version_id == resume.current_version.id
    assert context.resume_title_snapshot == "迁移后的简历"
    assert context.resume_text == "canonical resume text"
    assert not hasattr(context, "resume_id")


def test_resume_intake_rejects_unmigrated_legacy_row(db_session):
    user = _user(db_session)
    db_session.add(
        Resume(
            id="rsm_unmigrated",
            user_id=user.id,
            title="旧简历",
            raw_text_snapshot="must not be read",
            parse_status="ready",
        )
    )
    db_session.commit()

    with pytest.raises(analysis_intake.ResumeNotFound, match="migration 0029"):
        asyncio.run(
            analysis_intake.resolve_resume_context(
                db_session,
                user_id="alice",
                resume_id="rsm_unmigrated",
                resume_file_asset_id=None,
            )
        )
