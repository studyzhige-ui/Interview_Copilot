import pytest
from app.models.user import User
from app.services.capabilities import skill_service

SKILL = """---
name: interview-plan
description: Build an interview preparation plan
---

# Workflow

Create a plan from the job description and resume.
"""


@pytest.fixture
def user(db_session):
    row = User(username="skill-user", hashed_password="x")
    db_session.add(row)
    db_session.commit()
    return row


def test_parse_and_crud_skill(db_session, user):
    created = skill_service.create_skill(db_session, user.id, SKILL, True)
    assert created["name"] == "interview-plan"
    assert created["enabled"] is True

    updated = skill_service.update_skill(
        db_session,
        user.id,
        created["id"],
        content=None,
        enabled=False,
    )
    assert updated["enabled"] is False
    assert skill_service.list_skills(db_session, user.id, enabled_only=True) == []
    assert skill_service.delete_skill(db_session, user.id, created["id"]) is True


def test_skill_requires_standard_frontmatter():
    with pytest.raises(ValueError, match="frontmatter"):
        skill_service.parse_skill("# no metadata")


def test_duplicate_skill_name_is_rejected(db_session, user):
    skill_service.create_skill(db_session, user.id, SKILL, True)
    with pytest.raises(ValueError, match="already exists"):
        skill_service.create_skill(db_session, user.id, SKILL, True)


def test_search_prefers_exact_name():
    rows = [
        {"name": "resume", "description": "Review a resume"},
        {"name": "resume-gap", "description": "Compare a resume and JD"},
    ]
    assert skill_service.search(rows, "resume")[0]["name"] == "resume"
