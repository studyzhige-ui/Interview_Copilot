"""Deterministic, evidence-backed cross-interview ability report."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

ABILITY_SCORE_SCALE_VERSION = "evidence-v2"
_SUPPORTED_SCORE_VERSIONS = {ABILITY_SCORE_SCALE_VERSION}
_AXIS_BY_SKILL_TYPE = {
    "knowledge_topic": "知识与原理",
    "system_design": "系统设计",
    "project_deep_dive": "项目深挖",
    "communication": "沟通表达",
    "behavioral": "行为面试",
}
FIXED_AXES = tuple(_AXIS_BY_SKILL_TYPE.values())


def _evidence_count(refs: Any) -> int:
    if not isinstance(refs, list):
        return 0
    return len(
        {
            (str(ref.get("type") or ""), str(ref.get("id") or ""))
            for ref in refs
            if isinstance(ref, dict) and ref.get("id")
        }
    )


def _extract_ability_records(db: Any, user_id: str) -> list[dict[str, Any]]:
    """Read active states without inventing scores for legacy label-only rows."""
    from app.services.memory import memory_ability_state_service

    records: list[dict[str, Any]] = []
    for state in memory_ability_state_service.load_active(user_id, db=db):
        records.append(
            {
                "topic": state.topic,
                "skill_type": state.skill_type,
                "mastery_level": state.mastery_level,
                "summary": state.summary or "",
                "score": state.ability_score,
                "score_version": state.score_version,
                "evidence_count": _evidence_count(state.evidence_refs_json),
                "time": state.last_evidence_at.isoformat()
                if state.last_evidence_at
                else "",
            }
        )
    return records


def _confidence(evidence_count: int) -> str:
    if evidence_count >= 4:
        return "high"
    if evidence_count >= 2:
        return "medium"
    if evidence_count == 1:
        return "low"
    return "none"


def _validate_score_version(version: str) -> None:
    if version not in _SUPPORTED_SCORE_VERSIONS:
        raise ValueError(f"unknown ability score scale: {version}")


def _build_report(
    records: list[dict[str, Any]], *, scale_version: str
) -> dict[str, Any]:
    _validate_score_version(scale_version)
    scored_records = [
        record
        for record in records
        if isinstance(record.get("score"), (int, float))
        and not isinstance(record.get("score"), bool)
        and record.get("score_version") in (None, scale_version)
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in scored_records:
        axis = _AXIS_BY_SKILL_TYPE.get(str(record.get("skill_type") or ""))
        if axis:
            grouped[axis].append(record)

    axes: list[dict[str, Any]] = []
    for name in FIXED_AXES:
        items = grouped.get(name, [])
        evidence_count = sum(int(item.get("evidence_count") or 0) for item in items)
        axes.append(
            {
                "k": name,
                "v": round(sum(float(item["score"]) for item in items) / len(items), 1)
                if items
                else None,
                "topic_count": len(items),
                "evidence_count": evidence_count,
                "confidence": _confidence(evidence_count) if items else "none",
            }
        )

    measured = [axis for axis in axes if axis["v"] is not None]
    overall = (
        round(sum(float(axis["v"]) for axis in measured) / len(measured), 1)
        if measured
        else None
    )
    strongest = max(measured, key=lambda axis: axis["v"])["k"] if measured else None

    ranked = sorted(
        scored_records,
        key=lambda record: (float(record["score"]), str(record.get("time") or "")),
        reverse=True,
    )
    strengths = [
        {
            "topic": str(record.get("topic") or ""),
            "evidence": str(record.get("summary") or ""),
            "score": round(float(record["score"]), 1),
            "mastery_level": record.get("mastery_level"),
            "evidence_count": int(record.get("evidence_count") or 0),
        }
        for record in ranked
        if float(record["score"]) >= 75.0
    ][:3]
    weaknesses = [
        {
            "k": str(record.get("topic") or ""),
            "v": round(float(record["score"]), 1),
            "why": str(record.get("summary") or ""),
            "plan": (
                f"围绕「{record.get('topic') or '该主题'}」补齐定义、边界和实战例子，"
                "并在下一次模拟面试中复测。"
            ),
            "evidence_count": int(record.get("evidence_count") or 0),
        }
        for record in reversed(ranked)
        if float(record["score"]) < 60.0
    ][:3]

    return {
        "status": "success",
        "score_scale": {
            "version": scale_version,
            "range": [0, 100],
            "bands": {
                "weak": [0, 39.9],
                "improving": [40, 59.9],
                "stable": [60, 79.9],
                "strong": [80, 100],
            },
            "aggregation": "mean_of_scored_topics_per_axis_then_equal_axis_mean",
            "missing": "unknown_not_zero",
            "meaning": "基于实际表现证据的连续成长分，不是心理测量或招聘录用结论",
        },
        "overall": overall,
        "axes": axes,
        "totals": {
            "ability_topics": len(records),
            "scored_topics": len(scored_records),
            "evaluated_axes": len(measured),
            "evidence_refs": sum(
                int(record.get("evidence_count") or 0) for record in scored_records
            ),
            "strongest_axis": strongest,
        },
        "strengths": strengths,
        "weaknesses": weaknesses,
        "overall_evaluation": (
            f"当前 {len(scored_records)}/{len(records)} 个能力主题具有连续评分，"
            f"覆盖 {len(measured)}/{len(FIXED_AXES)} 个能力维度；"
            "旧的定性状态不会被伪造为数值。"
        ),
        "generated_from": "memory_ability_states",
    }


def _load_records(user_id: str) -> list[dict[str, Any]]:
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        return _extract_ability_records(db, user_id=user_id)


async def generate_comprehensive_report(
    limit: int = 20,
    user_id: str | None = None,
    scale_version: str = ABILITY_SCORE_SCALE_VERSION,
) -> dict[str, Any]:
    if not user_id:
        return {"status": "empty", "message": "missing user id"}
    _validate_score_version(scale_version)

    records = await asyncio.to_thread(_load_records, user_id)
    if not records:
        return {"status": "empty", "message": "暂无能力状态数据"}
    records.sort(key=lambda record: str(record.get("time") or ""), reverse=True)
    return _build_report(records[:limit], scale_version=scale_version)


__all__ = ["ABILITY_SCORE_SCALE_VERSION", "generate_comprehensive_report"]
