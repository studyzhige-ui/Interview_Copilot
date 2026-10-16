"""Deterministic cross-interview report over canonical AbilitySignal state."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from app.core.scoring import SCORE_SCALE_VERSION, read_historical_score, validate_score

ABILITY_SCORE_SCALE_VERSION = SCORE_SCALE_VERSION
_SUPPORTED_SCORE_VERSIONS = {ABILITY_SCORE_SCALE_VERSION}


def _extract_ability_records(db: Any, user_id: str) -> list[dict[str, Any]]:
    """Read the one canonical inferred-state owner used by product surfaces."""
    from app.core.user_identity import resolve_user_pk
    from app.models.ability_signal import AbilitySignal, AbilitySignalSourceRef

    records: list[dict[str, Any]] = []
    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        return records
    states = (
        db.query(AbilitySignal)
        .filter(
            AbilitySignal.user_id == user_pk,
            AbilitySignal.status.in_(("active", "disputed")),
        )
        .order_by(AbilitySignal.formed_at.desc(), AbilitySignal.id.desc())
        .all()
    )
    for state in states:
        source_count = (
            db.query(AbilitySignalSourceRef.id)
            .filter(AbilitySignalSourceRef.ability_signal_id == state.id)
            .count()
        )
        records.append(
            {
                "topic": state.topic,
                "summary": state.summary or "",
                "score": read_historical_score(state.score, state.score_scale_version),
                "score_version": SCORE_SCALE_VERSION,
                "rubric_version": state.rubric_version,
                "scope_kind": state.scope_kind,
                "scope_ref_id": state.scope_ref_id,
                "evidence_count": source_count,
                "time": state.formed_at.isoformat() if state.formed_at else "",
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


def _valid_score(value: object) -> bool:
    try:
        validate_score(value)
    except ValueError:
        return False
    return True


def _build_report(
    records: list[dict[str, Any]], *, scale_version: str
) -> dict[str, Any]:
    _validate_score_version(scale_version)
    scored_records = [
        record
        for record in records
        if isinstance(record.get("score"), (int, float))
        and not isinstance(record.get("score"), bool)
        and record.get("score_version") == scale_version
        and _valid_score(record.get("score"))
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["topic"])].append(record)

    axes: list[dict[str, Any]] = []
    for name, topic_records in grouped.items():
        items = [item for item in scored_records if item["topic"] == name]
        evidence_count = sum(int(item.get("evidence_count") or 0) for item in items)
        axes.append(
            {
                "k": name,
                "v": round(sum(float(item["score"]) for item in items) / len(items), 1)
                if items
                else None,
                "assessment_count": len(items),
                "evidence_count": evidence_count,
                "confidence": _confidence(evidence_count) if items else "none",
                "summary": max(
                    items or topic_records, key=lambda item: str(item.get("time") or "")
                ).get("summary")
                or "",
            }
        )

    measured = [axis for axis in axes if axis["v"] is not None]
    overall = (
        round(sum(float(axis["v"]) for axis in measured) / len(measured), 1)
        if measured
        else None
    )
    strongest = max(measured, key=lambda axis: axis["v"])["k"] if measured else None

    ranked = sorted(measured, key=lambda axis: float(axis["v"]), reverse=True)
    strengths = [
        {
            "topic": record["k"],
            "evidence": record["summary"],
            "score": record["v"],
            "evidence_count": record["evidence_count"],
        }
        for record in ranked
        if float(record["v"]) >= 7.5
    ][:3]
    weaknesses = [
        {
            "topic": record["k"],
            "score": record["v"],
            "flaw": record["summary"],
            "plan": (
                f"围绕「{record['k']}」补齐定义、边界和实战例子，"
                "并在下一次模拟面试中复测。"
            ),
            "evidence_count": int(record.get("evidence_count") or 0),
        }
        for record in reversed(ranked)
        if float(record["v"]) < 6.0
    ][:3]

    return {
        "status": "success",
        "score_scale": {
            "version": scale_version,
            "range": [0, 10],
            "bands": {
                "weak": [0, 3.9],
                "improving": [4, 5.9],
                "stable": [6, 7.9],
                "strong": [8, 10],
            },
            "aggregation": "mean_per_topic_then_equal_topic_mean",
            "missing": "unknown_not_zero",
            "meaning": "基于实际表现证据的连续成长分，不是心理测量或招聘录用结论",
        },
        "overall": overall,
        "axes": axes,
        "totals": {
            "ability_topics": len(axes),
            "scored_topics": len(measured),
            "assessment_count": len(scored_records),
            "evidence_refs": sum(
                int(record.get("evidence_count") or 0) for record in scored_records
            ),
            "strongest_axis": strongest,
        },
        "strengths": strengths,
        "weaknesses": weaknesses,
        "overall_evaluation": (
            f"当前 {len(measured)}/{len(axes)} 个能力主题具有连续评分；"
            "旧的定性状态不会被伪造为数值。"
        ),
        "generated_from": "ability_signals",
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
    topics = set(list(dict.fromkeys(record["topic"] for record in records))[:limit])
    return _build_report(
        [record for record in records if record["topic"] in topics],
        scale_version=scale_version,
    )


__all__ = ["ABILITY_SCORE_SCALE_VERSION", "generate_comprehensive_report"]
