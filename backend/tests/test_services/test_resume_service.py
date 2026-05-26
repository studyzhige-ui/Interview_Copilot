"""Tests for app.services.resume.resume_service.

Local SQLite fixture — the shared conftest db_session fixture is broken
because it imports a removed ``app.models.interview`` module.
"""
import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def resume_db_session():
    import app.models.resume_section  # noqa: F401 — register on Base
    from app.db.database import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[Base.metadata.tables["resume_sections"]])
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _NoCloseSession:
    """Session proxy that turns close() into a flush — so cross-call state
    survives even though resume_service opens a fresh SessionLocal each time.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        try:
            self._inner.commit()
        except Exception:
            self._inner.rollback()


def test_resume_parse_and_store(monkeypatch, resume_db_session):
    """extract_and_store should run LLM parse + persist all valid sections."""
    from app.models.resume_section import ResumeSection
    from app.services.resume import resume_service as module

    class FakeResponse:
        def __init__(self, text):
            self.text = text

    class FakeLLM:
        async def acomplete(self, *args, **kwargs):
            return FakeResponse(
                json.dumps([
                    {
                        "section_type": "summary",
                        "title": "个人简介",
                        "content": "3年后端开发经验",
                        "metadata": None,
                    },
                    {
                        "section_type": "project",
                        "title": "推荐系统",
                        "content": "基于协同过滤的推荐系统项目",
                        "metadata": {"tech_stack": ["Python", "Redis"]},
                    },
                    {
                        "section_type": "skill",
                        "title": "技术技能",
                        "content": "Python, Go, Redis, MySQL",
                        "metadata": None,
                    },
                ])
            )

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(resume_db_session))
    monkeypatch.setattr(module, "agent_fast_llm", FakeLLM())

    service = module.ResumeService()
    sections = asyncio.run(
        service.extract_and_store(
            user_id="alice",
            upload_id="upload_resume_1",
            resume_text="我有3年后端开发经验...",
        )
    )

    assert len(sections) == 3
    types = {s.section_type for s in sections}
    assert types == {"summary", "project", "skill"}

    rows = resume_db_session.query(ResumeSection).filter(
        ResumeSection.upload_id == "upload_resume_1"
    ).all()
    assert len(rows) == 3


def test_format_for_context_filters_by_section_type(monkeypatch, resume_db_session):
    """format_for_context with section_types=[project] should only include project rows."""
    from app.models.resume_section import ResumeSection
    from app.services.resume import resume_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(resume_db_session))

    for i, (stype, title, content) in enumerate([
        ("summary", "简介", "3年经验"),
        ("project", "推荐系统", "协同过滤推荐"),
        ("project", "搜索引擎", "ElasticSearch搜索"),
        ("education", "本科", "计算机科学"),
    ]):
        resume_db_session.add(ResumeSection(
            id=f"rs_{i}",
            user_id="alice",
            upload_id="u1",
            section_type=stype,
            title=title,
            content=content,
        ))
    resume_db_session.commit()

    service = module.ResumeService()
    sections = service.get_sections_by_upload("u1", "alice")
    text = service.format_for_context(sections, section_types=["project"])

    assert "推荐系统" in text
    assert "搜索引擎" in text
    assert "简介" not in text  # filtered out


def test_reparse_replaces_old_sections(monkeypatch, resume_db_session):
    """Calling extract_and_store again for the same upload_id wipes old rows first."""
    from app.models.resume_section import ResumeSection
    from app.services.resume import resume_service as module

    class FakeResponse:
        def __init__(self, text):
            self.text = text

    class FakeLLM:
        def __init__(self):
            self.call_count = 0

        async def acomplete(self, *args, **kwargs):
            self.call_count += 1
            return FakeResponse(json.dumps([
                {"section_type": "summary", "title": f"Version {self.call_count}", "content": "Content"}
            ]))

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(resume_db_session))
    monkeypatch.setattr(module, "agent_fast_llm", FakeLLM())

    service = module.ResumeService()
    first = asyncio.run(service.extract_and_store("alice", "u1", "V1"))
    assert len(first) == 1
    assert first[0].title == "Version 1"

    second = asyncio.run(service.extract_and_store("alice", "u1", "V2"))
    assert len(second) == 1
    assert second[0].title == "Version 2"

    rows = resume_db_session.query(ResumeSection).filter(ResumeSection.upload_id == "u1").all()
    assert len(rows) == 1
    assert rows[0].title == "Version 2"  # old row replaced


def test_persist_handles_invalid_section_type(monkeypatch, resume_db_session):
    """Unknown section_type values get coerced to 'summary' rather than dropped."""
    from app.models.resume_section import ResumeSection
    from app.services.resume import resume_service as module

    class FakeLLM:
        async def acomplete(self, *args, **kwargs):
            class _R:
                text = json.dumps([
                    {"section_type": "garbage_value", "title": "Mystery", "content": "Some text"}
                ])
            return _R()

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(resume_db_session))
    monkeypatch.setattr(module, "agent_fast_llm", FakeLLM())

    sections = asyncio.run(module.ResumeService().extract_and_store("u", "up", "txt"))
    assert len(sections) == 1
    assert sections[0].section_type == "summary"
