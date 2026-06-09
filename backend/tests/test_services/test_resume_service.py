"""Tests for app.services.resume.resume_service.

Local SQLite fixture — the shared conftest db_session fixture is broken
because it imports a removed ``app.models.interview`` module.

Resume sections now hang off the first-class ``resumes`` entity (``resume_id``),
not an upload id; ``extract_and_store`` takes the stable ``user_pk`` directly.
"""
import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def resume_db_session():
    import app.models.file_asset  # noqa: F401 — resumes.file_asset_id FK target
    import app.models.resume  # noqa: F401 — register resumes on Base
    import app.models.resume_section  # noqa: F401 — register on Base
    import app.models.user  # noqa: F401
    from app.db.database import Base
    from app.models.resume import Resume
    from app.models.user import User

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Base.metadata.tables["users"],
            Base.metadata.tables["file_assets"],
            Base.metadata.tables["resumes"],
            Base.metadata.tables["resume_sections"],
        ],
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    user = User(username="alice", hashed_password="x")
    session.add(user)
    session.commit()
    # Seed the default resume entity the tests parse into.
    session.add(Resume(id="rsm_1", user_id=user.id, title="我的简历", is_default=True))
    session.commit()
    session.user_pk = user.id  # stash for convenience
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


def _patch(monkeypatch, module, session, llm):
    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(session))
    monkeypatch.setattr(module, "agent_fast_llm", llm)
    # Vectorization + the delete-then-insert index sync hit the real embed model
    # and Milvus — out of scope for these persistence tests, and they block when
    # those services are offline. Stub both.
    monkeypatch.setattr(module.ResumeService, "_vectorize_sections", staticmethod(lambda sections: None))
    from app.services.resume import resume_vector_service as rvs
    monkeypatch.setattr(rvs.resume_vector_service, "delete_by_resume", lambda resume_id: None)


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
                    {"section_type": "summary", "title": "个人简介", "content": "3年后端开发经验", "metadata": None},
                    {"section_type": "project", "title": "推荐系统", "content": "基于协同过滤的推荐系统项目",
                     "metadata": {"tech_stack": ["Python", "Redis"]}},
                    {"section_type": "skill", "title": "技术技能", "content": "Python, Go, Redis, MySQL", "metadata": None},
                ])
            )

    _patch(monkeypatch, module, resume_db_session, FakeLLM())

    service = module.ResumeService()
    sections = asyncio.run(
        service.extract_and_store(
            user_pk=resume_db_session.user_pk,
            resume_id="rsm_1",
            resume_text="我有3年后端开发经验...",
        )
    )

    assert len(sections) == 3
    assert {s.section_type for s in sections} == {"summary", "project", "skill"}
    rows = resume_db_session.query(ResumeSection).filter(ResumeSection.resume_id == "rsm_1").all()
    assert len(rows) == 3
    # order_idx is assigned by parse order.
    assert sorted(r.order_idx for r in rows) == [0, 1, 2]


def test_format_for_context_filters_by_section_type(monkeypatch, resume_db_session):
    """format_for_context with section_types=[project] should only include project rows."""
    from app.models.resume_section import ResumeSection
    from app.services.resume import resume_service as module

    _patch(monkeypatch, module, resume_db_session, object())

    for i, (stype, title, content) in enumerate([
        ("summary", "简介", "3年经验"),
        ("project", "推荐系统", "协同过滤推荐"),
        ("project", "搜索引擎", "ElasticSearch搜索"),
        ("education", "本科", "计算机科学"),
    ]):
        resume_db_session.add(ResumeSection(
            id=f"rs_{i}",
            user_id=resume_db_session.user_pk,
            resume_id="rsm_1",
            section_type=stype,
            title=title,
            content=content,
            order_idx=i,
        ))
    resume_db_session.commit()

    service = module.ResumeService()
    sections = service.get_sections_by_resume("rsm_1", "alice")
    text = service.format_for_context(sections, section_types=["project"])

    assert "推荐系统" in text
    assert "搜索引擎" in text
    assert "简介" not in text  # filtered out


def test_reparse_replaces_old_sections(monkeypatch, resume_db_session):
    """Calling extract_and_store again for the same resume_id wipes old rows first."""
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

    _patch(monkeypatch, module, resume_db_session, FakeLLM())

    service = module.ResumeService()
    first = asyncio.run(service.extract_and_store(
        user_pk=resume_db_session.user_pk, resume_id="rsm_1", resume_text="V1"))
    assert len(first) == 1
    assert first[0].title == "Version 1"

    second = asyncio.run(service.extract_and_store(
        user_pk=resume_db_session.user_pk, resume_id="rsm_1", resume_text="V2"))
    assert len(second) == 1
    assert second[0].title == "Version 2"

    rows = resume_db_session.query(ResumeSection).filter(ResumeSection.resume_id == "rsm_1").all()
    assert len(rows) == 1
    assert rows[0].title == "Version 2"  # old row replaced


def test_persist_handles_invalid_section_type(monkeypatch, resume_db_session):
    """Unknown section_type values get coerced to 'summary' rather than dropped."""
    from app.services.resume import resume_service as module

    class FakeLLM:
        async def acomplete(self, *args, **kwargs):
            class _R:
                text = json.dumps([
                    {"section_type": "garbage_value", "title": "Mystery", "content": "Some text"}
                ])
            return _R()

    _patch(monkeypatch, module, resume_db_session, FakeLLM())

    sections = asyncio.run(module.ResumeService().extract_and_store(
        user_pk=resume_db_session.user_pk, resume_id="rsm_1", resume_text="txt"))
    assert len(sections) == 1
    assert sections[0].section_type == "summary"
