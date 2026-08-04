"""Deterministic, evidence-backed cross-interview ability report."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any


_MASTERY_SCORE = {"weak": 35.0, "improving": 55.0, "stable": 75.0, "strong": 90.0}
_AXIS_BY_SKILL_TYPE = {
    "knowledge_topic": "知识与原理",
    "system_design": "系统设计",
    "project_deep_dive": "项目深挖",
    "communication": "沟通表达",
    "behavioral": "行为面试",
}
FIXED_AXES = tuple(_AXIS_BY_SKILL_TYPE.values())


def _evidence_count(raw: str | None) -> int:
    try:
        refs = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        refs = []
    return max(1, len(refs)) if isinstance(refs, list) else 1


def _extract_ability_records(db: Any, user_id: str) -> list[dict[str, Any]]:
    """Read active ability states in a report-friendly, traceable shape."""
    from app.services.memory import memory_ability_state_service

    records: list[dict[str, Any]] = []
    for state in memory_ability_state_service.load_active(user_id, db=db):
        records.append(
            {
                "topic": state.topic,
                "skill_type": state.skill_type,
                "mastery_level": state.mastery_level,
                "summary": state.summary or "",
                "score": _MASTERY_SCORE.get(state.mastery_level),
                "evidence_count": _evidence_count(state.evidence_refs_json),
                "time": state.last_evidence_at.isoformat()
                if state.last_evidence_at
                else "",
            }
        )
    return records


def _confidence(topic_count: int) -> str:
    if topic_count >= 4:
        return "high"
    if topic_count >= 2:
        return "medium"
    return "low"


def _build_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        axis = _AXIS_BY_SKILL_TYPE.get(str(record.get("skill_type") or ""))
        score = record.get("score")
        if axis and isinstance(score, (int, float)):
            grouped[axis].append(record)

    axes: list[dict[str, Any]] = []
    for name in FIXED_AXES:
        items = grouped.get(name, [])
        axes.append(
            {
                "k": name,
                "v": round(sum(float(item["score"]) for item in items) / len(items), 1)
                if items
                else None,
                "topic_count": len(items),
                "evidence_count": sum(
                    int(item.get("evidence_count") or 0) for item in items
                ),
                "confidence": _confidence(len(items)) if items else "none",
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
        (record for record in records if isinstance(record.get("score"), (int, float))),
        key=lambda record: (float(record["score"]), str(record.get("time") or "")),
        reverse=True,
    )
    strengths = [
        {
            "topic": str(record.get("topic") or ""),
            "evidence": str(record.get("summary") or ""),
            "mastery_level": record.get("mastery_level"),
            "evidence_count": int(record.get("evidence_count") or 0),
        }
        for record in ranked
        if float(record["score"]) >= _MASTERY_SCORE["stable"]
    ][:3]
    weaknesses = [
        {
            "k": str(record.get("topic") or ""),
            "v": float(record["score"]),
            "why": str(record.get("summary") or ""),
            "plan": (
                f"围绕「{record.get('topic') or '该主题'}」补齐定义、边界和实战例子，"
                "并在下一次模拟面试中复测。"
            ),
            "evidence_count": int(record.get("evidence_count") or 0),
        }
        for record in reversed(ranked)
        if float(record["score"]) <= _MASTERY_SCORE["improving"]
    ][:3]

    return {
        "status": "success",
        "overall": overall,
        "axes": axes,
        "totals": {
            "ability_topics": len(records),
            "evaluated_axes": len(measured),
            "evidence_refs": sum(
                int(record.get("evidence_count") or 0) for record in records
            ),
            "strongest_axis": strongest,
        },
        "strengths": strengths,
        "weaknesses": weaknesses,
        "overall_evaluation": (
            f"当前已覆盖 {len(measured)}/{len(FIXED_AXES)} 个能力维度；"
            "分数只汇总已有证据，未覆盖维度保持待评估。"
        ),
        "generated_from": "memory_ability_states",
    }


def _load_records(user_id: str) -> list[dict[str, Any]]:
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        return _extract_ability_records(db, user_id=user_id)


async def generate_comprehensive_report(
    limit: int = 20, user_id: str | None = None
) -> dict[str, Any]:
    if not user_id:
        return {"status": "empty", "message": "missing user id"}

    # The report endpoint is async, while SQLAlchemy is intentionally sync in
    # this service. Keep the event loop free for other requests.
    records = await asyncio.to_thread(_load_records, user_id)
    if not records:
        return {"status": "empty", "message": "暂无能力状态数据"}
    records.sort(key=lambda record: str(record.get("time") or ""), reverse=True)
    return _build_report(records[:limit])


__all__ = ["generate_comprehensive_report"]
