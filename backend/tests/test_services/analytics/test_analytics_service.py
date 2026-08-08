"""Evidence semantics for the deterministic cross-interview report."""

from unittest.mock import patch

import pytest

_SVC = "app.services.analytics.diagnostics_report_service"


@pytest.mark.asyncio
async def test_generate_report_empty_when_no_ability_records():
    with patch(f"{_SVC}._extract_ability_records", return_value=[]):
        from app.services.analytics.diagnostics_report_service import (
            generate_comprehensive_report,
        )

        result = await generate_comprehensive_report(limit=20, user_id="u1")
    assert result["status"] == "empty"


@pytest.mark.asyncio
async def test_generate_report_empty_when_no_user():
    from app.services.analytics.diagnostics_report_service import (
        generate_comprehensive_report,
    )

    result = await generate_comprehensive_report(limit=20, user_id=None)
    assert result["status"] == "empty"


@pytest.mark.asyncio
async def test_report_aggregates_observed_axes_without_model_call():
    records = [
        {
            "topic": "Redis 分布式锁",
            "skill_type": "system_design",
            "mastery_level": "weak",
            "summary": "锁续期与 fencing token 不清楚",
            "score": 35.0,
            "evidence_count": 2,
            "time": "2026-01-01T00:00:00",
        },
        {
            "topic": "容量估算",
            "skill_type": "system_design",
            "mastery_level": "stable",
            "summary": "能完成基础估算",
            "score": 75.0,
            "evidence_count": 1,
            "time": "2026-01-02T00:00:00",
        },
        {
            "topic": "项目表达",
            "skill_type": "communication",
            "mastery_level": "strong",
            "summary": "能用结果和数据说明贡献",
            "score": 90.0,
            "evidence_count": 3,
            "time": "2026-01-03T00:00:00",
        },
    ]
    with patch(f"{_SVC}._extract_ability_records", return_value=records):
        from app.services.analytics.diagnostics_report_service import (
            generate_comprehensive_report,
        )

        result = await generate_comprehensive_report(limit=20, user_id="u1")

    axes = {axis["k"]: axis for axis in result["axes"]}
    assert axes["系统设计"]["v"] == 55.0
    assert axes["系统设计"]["evidence_count"] == 3
    assert axes["沟通表达"]["v"] == 90.0
    assert axes["知识与原理"]["v"] is None
    assert result["totals"]["evaluated_axes"] == 2
    assert result["totals"]["ability_topics"] == 3
    assert result["score_scale"]["version"] == "evidence-v2"
    assert result["score_scale"]["range"] == [0, 100]
    assert result["score_scale"]["missing"] == "unknown_not_zero"


@pytest.mark.asyncio
async def test_missing_evidence_is_unknown_not_zero():
    records = [
        {
            "topic": "MySQL 索引",
            "skill_type": "knowledge_topic",
            "mastery_level": "stable",
            "summary": "能解释联合索引",
            "score": 75.0,
            "evidence_count": 1,
            "time": "2026-01-01",
        }
    ]
    with patch(f"{_SVC}._extract_ability_records", return_value=records):
        from app.services.analytics.diagnostics_report_service import (
            generate_comprehensive_report,
        )

        result = await generate_comprehensive_report(user_id="u1")

    unknown = [axis for axis in result["axes"] if axis["k"] != "知识与原理"]
    assert all(axis["v"] is None and axis["confidence"] == "none" for axis in unknown)
    assert result["overall"] == 75.0


@pytest.mark.asyncio
async def test_unknown_score_scale_is_rejected_instead_of_silently_reinterpreted():
    records = [
        {
            "topic": "Redis",
            "skill_type": "knowledge_topic",
            "mastery_level": "stable",
            "summary": "有证据",
            "evidence_count": 1,
            "time": "2026-01-01",
        }
    ]
    with patch(f"{_SVC}._extract_ability_records", return_value=records):
        from app.services.analytics.diagnostics_report_service import (
            generate_comprehensive_report,
        )

        with pytest.raises(ValueError, match="unknown ability score scale"):
            await generate_comprehensive_report(
                user_id="u1", scale_version="evidence-v3"
            )


@pytest.mark.asyncio
async def test_legacy_label_without_numeric_evidence_is_not_given_a_fake_score():
    records = [
        {
            "topic": "旧状态",
            "skill_type": "knowledge_topic",
            "mastery_level": "strong",
            "summary": "只有历史定性标签",
            "score": None,
            "score_version": None,
            "evidence_count": 0,
            "time": "2026-01-01",
        }
    ]
    with patch(f"{_SVC}._extract_ability_records", return_value=records):
        from app.services.analytics.diagnostics_report_service import (
            generate_comprehensive_report,
        )

        result = await generate_comprehensive_report(user_id="u1")

    assert result["overall"] is None
    assert result["totals"]["scored_topics"] == 0
    assert all(axis["v"] is None for axis in result["axes"])
