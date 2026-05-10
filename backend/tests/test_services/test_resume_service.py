import asyncio
import json

from app.models.resume_section import ResumeSection


def _make_fake_session(db_session):
    """Wrap db_session so it doesn't expire objects on commit."""
    db_session.expire_on_commit = False
    return db_session


def test_resume_parse_and_store(db_session, monkeypatch):
    from app.services import resume_service as module

    _make_fake_session(db_session)

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

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)
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
    assert sections[0].section_type == "summary"
    assert sections[1].section_type == "project"
    assert sections[2].section_type == "skill"

    rows = db_session.query(ResumeSection).filter(
        ResumeSection.upload_id == "upload_resume_1"
    ).all()
    assert len(rows) == 3


def test_format_for_context(db_session, monkeypatch):
    from app.services import resume_service as module

    _make_fake_session(db_session)
    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    for i, (stype, title, content) in enumerate([
        ("summary", "简介", "3年经验"),
        ("project", "推荐系统", "协同过滤推荐"),
        ("project", "搜索引擎", "ElasticSearch搜索"),
        ("education", "本科", "计算机科学"),
    ]):
        db_session.add(ResumeSection(
            id=f"rs_{i}",
            user_id="alice",
            upload_id="u1",
            section_type=stype,
            title=title,
            content=content,
        ))
    db_session.commit()

    service = module.ResumeService()
    sections = service.get_sections_by_upload("u1", "alice")
    text = service.format_for_context(sections, section_types=["project"])
    assert "推荐系统" in text
    assert "搜索引擎" in text
    assert "简介" not in text


def test_reparse_replaces_old_sections(db_session, monkeypatch):
    from app.services import resume_service as module

    _make_fake_session(db_session)

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

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(module, "agent_fast_llm", FakeLLM())

    service = module.ResumeService()
    first = asyncio.run(service.extract_and_store("alice", "u1", "V1"))
    assert len(first) == 1
    assert first[0].title == "Version 1"

    second = asyncio.run(service.extract_and_store("alice", "u1", "V2"))
    assert len(second) == 1
    assert second[0].title == "Version 2"

    rows = db_session.query(ResumeSection).filter(ResumeSection.upload_id == "u1").all()
    assert len(rows) == 1
