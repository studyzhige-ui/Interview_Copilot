"""Canonical ``read_resume`` Tool behavior and cut-over regressions."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

from app.agent_runtime.tool_registry import AgentToolContext
from app.agent_runtime.tools.resume import ReadResumeArgs, _read_resume_handler
from app.models.file_asset import FileAsset
from app.models.resume import Resume
from app.models.user import User
from app.services.resume import resume_artifact_service


def _seed_user(db_session) -> User:
    user = User(username="alice", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return user


def _use_test_session(monkeypatch, db_session) -> None:
    @contextmanager
    def _session():
        yield db_session

    monkeypatch.setattr("app.db.database.SessionLocal", _session)


def _invoke() -> dict:
    return asyncio.run(
        _read_resume_handler(
            ReadResumeArgs(),
            AgentToolContext(user_id="alice", session_id="s1"),
        )
    )


def test_read_resume_returns_default_canonical_artifact(db_session, monkeypatch):
    user = _seed_user(db_session)
    resume = resume_artifact_service.create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="read-resume-canonical",
        title="我的简历",
        file_asset_id=None,
        raw_text="三年后端开发经验，主导推荐系统",
        make_default=True,
    )
    db_session.commit()
    _use_test_session(monkeypatch, db_session)

    result = _invoke()

    assert result == {
        "resume_id": resume.artifact.id,
        "artifact_version_id": resume.current_version.id,
        "title": "我的简历",
        "is_default": True,
        "section_count": 0,
        "raw_resume_available": True,
        "source": "artifact_version",
        "parse_status": "pending",
        "pending_profile_draft_id": None,
        "full_text": "三年后端开发经验，主导推荐系统",
    }


def test_read_resume_never_falls_back_to_unmigrated_legacy_row(db_session, monkeypatch):
    user = _seed_user(db_session)
    db_session.add(
        Resume(
            id="rsm_unmigrated",
            user_id=user.id,
            title="旧简历",
            raw_text_snapshot="不得被生产 Tool 读取",
            parse_status="ready",
        )
    )
    db_session.commit()
    _use_test_session(monkeypatch, db_session)

    result = _invoke()

    assert result["error"] == "resume_artifact_not_found"
    assert result["raw_resume_available"] is False
    assert "migration 0029" in result["message"]
    assert "不得被生产 Tool 读取" not in str(result)


def test_read_resume_reports_canonical_artifact_not_ready(db_session, monkeypatch):
    user = _seed_user(db_session)
    asset = FileAsset(
        id="fa_pending_resume",
        user_id=user.id,
        purpose="resume",
        original_filename="resume.pdf",
        object_key="uploads/alice/fa_pending_resume/resume.pdf",
        storage_uri="s3://test/uploads/alice/fa_pending_resume/resume.pdf",
        upload_status="uploaded",
        validation_status="passed",
    )
    db_session.add(asset)
    db_session.flush()
    resume = resume_artifact_service.create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="read-resume-pending",
        title="仍在解析的简历",
        file_asset_id=asset.id,
        raw_text=None,
        make_default=True,
    )
    db_session.commit()
    _use_test_session(monkeypatch, db_session)

    result = _invoke()

    assert result["error"] == "resume_artifact_not_ready"
    assert result["resume_id"] == resume.artifact.id
    assert result["artifact_version_id"] == resume.current_version.id
    assert result["parse_status"] == "pending"
    assert result["raw_resume_available"] is False


def test_read_resume_service_error_returns_error_dict(db_session, monkeypatch):
    _seed_user(db_session)
    db_session.commit()
    _use_test_session(monkeypatch, db_session)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("DB unavailable")

    monkeypatch.setattr(resume_artifact_service, "list_resume_artifacts", _boom)

    result = _invoke()

    assert result == {"error": "Failed to read resume", "section_count": 0}
