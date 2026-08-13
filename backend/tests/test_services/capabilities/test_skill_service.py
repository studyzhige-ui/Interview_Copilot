import pytest
from app.models.user import User
from app.services.capabilities import skill_service

SKILL = """---
name: interview-plan
description: Build an interview preparation plan
profiles: [career, debrief]
required-tools: [read_file]
allowed-tools: [read_file, search_jobs]
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
    assert created["revision"] == 1
    assert created["applicable_profiles"] == ["career", "debrief"]
    assert created["required_tools"] == ["read_file"]
    assert created["allowed_tools"] == ["read_file", "search_jobs"]

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


def test_resources_are_versioned_and_path_scoped(db_session, user):
    created = skill_service.create_skill(db_session, user.id, SKILL, True)

    updated = skill_service.replace_resources(
        db_session,
        user_pk=user.id,
        skill_id=created["id"],
        resources=[
            {
                "path": "references/rubric.md",
                "kind": "reference",
                "content": "Use this rubric only when the workflow requests it.",
            },
            {
                "path": "templates/answer.md",
                "kind": "template",
                "content": "# Answer\n",
            },
        ],
    )

    assert updated is not None
    assert updated["revision"] == 2
    assert [item["path"] for item in updated["resources"]] == [
        "references/rubric.md",
        "templates/answer.md",
    ]
    resource = skill_service.load_resource(
        db_session,
        user_pk=user.id,
        skill_id=created["id"],
        path="references/rubric.md",
    )
    assert resource is not None
    assert resource.content.startswith("Use this rubric")
    with pytest.raises(ValueError, match="safe relative path"):
        skill_service.replace_resources(
            db_session,
            user_pk=user.id,
            skill_id=created["id"],
            resources=[{"path": "../secret", "kind": "reference", "content": "x"}],
        )
