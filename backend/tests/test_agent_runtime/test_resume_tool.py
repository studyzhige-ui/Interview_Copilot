"""read_resume tool handler — happy paths + error handling."""

import asyncio


def test_read_resume_reads_personal_entity(monkeypatch):
    """``read_resume`` reads the user's default personal ``resumes`` entity:
    structured ``resume_sections`` first, else the entity's
    ``raw_text_snapshot``. Resumes are a personal entity — never knowledge
    documents, so there is no knowledge-chunk / docstore fallback.

    Covers three branches:
      (1) parsed sections present → structured result
      (2) no sections → raw_text_snapshot fallback (source='raw_text_snapshot')
      (3) no resumes at all → raw_resume_available=False + error
    """
    from contextlib import contextmanager

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.resume import _read_resume_handler, ReadResumeArgs

    # ``read_resume`` opens ``with SessionLocal() as db`` and passes db straight
    # to the (stubbed) entity service — a dummy context manager is enough.
    @contextmanager
    def _fake_session():
        yield object()

    monkeypatch.setattr("app.db.database.SessionLocal", _fake_session)

    class _Resume:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class _Section:
        def __init__(self, section_type, title, content):
            self.section_type = section_type
            self.title = title
            self.content = content

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    args = ReadResumeArgs(section_types=[])

    default_resume = _Resume(
        id="rsm_1",
        title="我的简历",
        is_default=True,
        parse_status="ready",
        raw_text_snapshot="三年后端开发经验，主导推荐系统",
    )
    monkeypatch.setattr(
        "app.services.resume.resume_entity_service.list_resumes",
        lambda db, *, user_id: [default_resume],
    )

    # --- Branch 1: parsed sections present → structured result ---------
    monkeypatch.setattr(
        "app.services.resume.resume_service.resume_service.get_sections_by_resume",
        lambda resume_id, user_id=None: [
            _Section("summary", "简介", "三年后端开发经验"),
            _Section("project", "推荐系统", "协同过滤推荐"),
        ],
    )
    monkeypatch.setattr(
        "app.services.resume.resume_service.resume_service.format_for_context",
        lambda sections, **k: "[summary] 简介\n三年后端开发经验",
    )
    result = asyncio.run(_read_resume_handler(args, ctx))
    assert result["resume_id"] == "rsm_1"
    assert result["section_count"] == 2
    assert result["sections"][0]["type"] == "summary"
    assert "简介" in result["formatted_text"]

    # --- Branch 2: no sections → raw_text_snapshot fallback ------------
    monkeypatch.setattr(
        "app.services.resume.resume_service.resume_service.get_sections_by_resume",
        lambda resume_id, user_id=None: [],
    )
    result = asyncio.run(_read_resume_handler(args, ctx))
    assert result["source"] == "raw_text_snapshot"
    assert result["raw_resume_available"] is True
    assert "推荐系统" in result["full_text"]

    # --- Branch 3: no resumes at all → no-resume error ----------------
    monkeypatch.setattr(
        "app.services.resume.resume_entity_service.list_resumes",
        lambda db, *, user_id: [],
    )
    result = asyncio.run(_read_resume_handler(args, ctx))
    assert result["raw_resume_available"] is False
    assert "error" in result


class TestResumeErrorHandling:
    """read_resume must catch service errors."""

    def test_service_error_returns_error_dict(self, monkeypatch):
        from contextlib import contextmanager

        @contextmanager
        def _fake_session():
            yield object()

        monkeypatch.setattr("app.db.database.SessionLocal", _fake_session)

        def _boom(db, *, user_id):
            raise RuntimeError("DB unavailable")

        monkeypatch.setattr(
            "app.services.resume.resume_entity_service.list_resumes",
            _boom,
        )

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.resume import ReadResumeArgs, _read_resume_handler

        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(_read_resume_handler(ReadResumeArgs(), ctx))
        assert "error" in result
        assert result["section_count"] == 0
