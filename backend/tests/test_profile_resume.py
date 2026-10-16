"""Online-resume sections use the confirmed profile and its existing drafts."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.career.application import profile as service
from app.schemas.career_profile import ConfirmationInput, PersonalFactInput

FACTS = TypeAdapter(PersonalFactInput)


@pytest.mark.parametrize(
    "value",
    [
        {
            "kind": "personal",
            "name": "示例候选人",
            "career_status": "2027届毕业生",
            "availability": "一个月内",
        },
        {"kind": "summary", "text": "具备 Python 后端与智能体项目经验。"},
        {
            "kind": "certificate",
            "title": "英语六级",
            "issuer": "考试机构",
            "occurred_on": "2025-06-01",
        },
        {
            "kind": "organization",
            "organization": "技术社团",
            "role": "讲师",
            "start_date": "2024-01-01",
            "description": "组织编程分享",
        },
        {
            "kind": "volunteer",
            "organization": "技术会议",
            "hours": 10.5,
            "description": "协助会务",
        },
        {
            "kind": "skill",
            "name": "Python",
            "description": "使用 FastAPI 构建后端接口。",
        },
    ],
)
def test_resume_section_round_trips_through_confirmed_profile(db, owners, value):
    user = owners[0]
    profile = service.ensure_career_profile(db, user_pk=user.id)
    saved = service.upsert_personal_fact(
        db,
        user_pk=user.id,
        expected_profile_version=profile.version,
        fact=FACTS.validate_python(value),
        confirmation=ConfirmationInput(kind="user_edit"),
    )
    fact = saved.personal_facts[-1]
    for key, expected in value.items():
        assert fact.value.model_dump(mode="json")[key] == expected
    assert fact.confirmed_source_kind == "user_edit"
    reloaded = service.get_career_profile(db, user_pk=user.id)
    assert reloaded == saved


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "volunteer", "organization": "活动", "hours": -1},
        {
            "kind": "organization",
            "organization": "社团",
            "start_date": "2025-02-01",
            "end_date": "2025-01-01",
        },
        {"kind": "personal", "name": ""},
    ],
)
def test_resume_fields_reject_invalid_shapes(value):
    with pytest.raises(ValidationError):
        FACTS.validate_python(value)


def test_distinct_certificates_and_organizations_do_not_conflict():
    for first, second in [
        (
            {"kind": "certificate", "title": "证书A"},
            {"kind": "certificate", "title": "证书B"},
        ),
        (
            {"kind": "organization", "organization": "社团A"},
            {"kind": "organization", "organization": "社团B"},
        ),
    ]:
        assert service._fact_identity_key(
            FACTS.validate_python(first)
        ) != service._fact_identity_key(FACTS.validate_python(second))


@pytest.mark.parametrize(
    "start,end",
    [
        ("2024", "2027"),
        ("2024-09", "2027-06"),
        ("2024-09-01", "2024-09"),
        ("2024", "2024-06"),
    ],
)
def test_resume_dates_keep_source_precision(start, end):
    fact = FACTS.validate_python(
        {
            "kind": "education",
            "institution": "合成大学",
            "start_date": start,
            "end_date": end,
        }
    )
    value = fact.model_dump(mode="json")
    assert value["start_date"] == start and value["end_date"] == end


@pytest.mark.parametrize(
    "start,end",
    [
        ("2025-13", "2026"),
        ("2025-02-30", "2026"),
        ("2025-09", "2025-06"),
        ("2025", "2024"),
    ],
)
def test_resume_dates_reject_invalid_calendar_values_or_reversed_ranges(start, end):
    with pytest.raises(ValidationError):
        FACTS.validate_python(
            {
                "kind": "education",
                "institution": "合成大学",
                "start_date": start,
                "end_date": end,
            }
        )


def test_missing_end_date_is_not_an_ongoing_claim():
    fact = FACTS.validate_python(
        {"kind": "volunteer", "organization": "活动", "start_date": "2025-09"}
    )
    assert fact.ongoing is False
    with pytest.raises(ValidationError):
        FACTS.validate_python(
            {
                "kind": "volunteer",
                "organization": "活动",
                "ongoing": True,
                "end_date": "2025-10",
            }
        )


@pytest.mark.parametrize("kind,field", [("personal", "name"), ("summary", "text")])
def test_single_resume_header_sections_update_the_same_identity(
    db, owners, kind, field
):
    profile = service.ensure_career_profile(db, user_pk=owners[0].id)
    first = service.upsert_personal_fact(
        db,
        user_pk=owners[0].id,
        expected_profile_version=profile.version,
        fact=FACTS.validate_python({"kind": kind, field: "Original"}),
        confirmation=ConfirmationInput(kind="user_edit"),
    )
    updated = service.upsert_personal_fact(
        db,
        user_pk=owners[0].id,
        expected_profile_version=first.version,
        fact=FACTS.validate_python({"kind": kind, field: "Updated"}),
        confirmation=ConfirmationInput(kind="user_edit"),
    )
    assert len(updated.personal_facts) == 1
    assert updated.personal_facts[0].id == first.personal_facts[0].id
    assert getattr(updated.personal_facts[0].value, field) == "Updated"
