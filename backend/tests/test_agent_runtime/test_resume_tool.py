"""Canonical ``read_resume`` Tool behavior and cut-over regressions."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import contextmanager

from app.agent_runtime.tool_registry import AgentToolContext
from app.agent_runtime.tools.resume import ReadResumeArgs, _read_resume_handler
from app.models.file_asset import FileAsset
from app.models.resume import Resume
from app.models.user import User
from app.career.application.resumes import resume_artifact_service


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
        "text_sha256": hashlib.sha256(
            "三年后端开发经验，主导推荐系统".encode()
        ).hexdigest(),
        "text_offset": 0,
        "text_total_characters": len("三年后端开发经验，主导推荐系统"),
        "text_complete": True,
        "next_offset": None,
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


def test_resume_pages_have_explicit_coverage_and_reject_changed_source(
    db_session, monkeypatch
):
    from app.agent_runtime.tools.resume import _read_resume_inner

    user = _seed_user(db_session)
    original = "Python\n" * 3000
    saved = resume_artifact_service.create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key="large",
        title="Long resume",
        file_asset_id=None,
        raw_text=original,
        make_default=True,
    )
    _use_test_session(monkeypatch, db_session)
    ctx = AgentToolContext(user_id="alice", session_id="s1")
    first = _read_resume_inner(ctx)
    assert first["text_complete"] is False and first["next_offset"] == 18000
    args = ReadResumeArgs(
        resume_id=saved.artifact.id,
        artifact_version_id=first["artifact_version_id"],
        text_sha256=first["text_sha256"],
        offset=first["next_offset"],
    )
    tail = _read_resume_inner(ctx, args)
    assert first["full_text"] + tail["full_text"] == original.strip()
    assert tail["next_offset"] is None and tail["text_complete"] is False
    resume_artifact_service.add_resume_version(
        db_session,
        user_pk=user.id,
        resume_id=saved.artifact.id,
        operation_key="changed",
        title="new",
        file_asset_id=None,
        raw_text="New resume contents",
    )
    assert _read_resume_inner(ctx, args)["error"] == "resume_version_changed"


def test_resume_page_offset_requires_all_source_fences():
    import pytest
    from pydantic import ValidationError

    for fields in (
        {},
        {"resume_id": "r"},
        {"resume_id": "r", "artifact_version_id": "v"},
    ):
        with pytest.raises(ValidationError):
            ReadResumeArgs(offset=1, **fields)
