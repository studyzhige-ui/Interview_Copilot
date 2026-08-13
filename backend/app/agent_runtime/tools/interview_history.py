"""Interview history tool: read_interview_history.

Wraps InterviewRecordService to read past interview records and analysis.
"""

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, Field, PositiveInt

from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.agent_runtime.tool_policy import ToolEffect

logger = logging.getLogger(__name__)


class ReadInterviewHistoryArgs(BaseModel):
    record_id: str = Field(
        default="",
        description="Specific record ID. Empty = list recent.",
    )
    question_indexes: list[PositiveInt] = Field(
        default_factory=list,
        description="1-based question indexes to read in full; requires record_id.",
    )
    limit: int = Field(default=5, ge=1, le=20, description="Max records when listing")


async def _read_interview_history_handler(
    args: ReadInterviewHistoryArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    return await asyncio.to_thread(_read_interview_history_sync, args, ctx)


def _read_interview_history_sync(
    args: ReadInterviewHistoryArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    try:
        from app.services.interview.interview_record_service import (
            interview_record_service,
        )

        if args.question_indexes and not args.record_id:
            return {"error": "question_indexes requires record_id"}
        if args.record_id:
            return _read_single_record(args, ctx, interview_record_service)
        return _list_records(args, ctx, interview_record_service)
    except Exception as exc:
        logger.warning("read_interview_history failed (%s)", type(exc).__name__)
        return {
            "error": "Failed to read interview history",
            "record_id": args.record_id,
        }


def _read_single_record(args, ctx, service) -> dict[str, Any]:
    record = service.get(args.record_id, ctx.user_id)
    if record is None:
        return {"error": "Interview record not found", "record_id": args.record_id}
    analysis = {}
    if record.analysis_json:
        try:
            analysis = json.loads(record.analysis_json)
        except json.JSONDecodeError:
            pass
    overall = analysis.get("overall", {})
    result = {
        "record_id": record.id,
        "source": record.source,
        "title": record.title,
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "overall_score": overall.get("score"),
        "overall_summary": overall.get("summary") or overall.get("feedback", ""),
        "strengths": overall.get("strengths", []),
        "weaknesses": overall.get("weaknesses", []),
        "key_growth_areas": overall.get("key_growth_areas", []),
    }
    if args.question_indexes:
        requested = list(dict.fromkeys(args.question_indexes))
        qa_by_index = {row.order_idx + 1: row for row in service.list_qa(record.id)}
        result["question_details"] = [
            {
                "index": index,
                "phase": qa_by_index[index].phase,
                "question": qa_by_index[index].question,
                "answer": qa_by_index[index].answer,
                "score": qa_by_index[index].score,
                "critique": qa_by_index[index].critique,
                "improved_answer": qa_by_index[index].improved_answer,
                "tags": _parse_tags(qa_by_index[index].key_points_json),
            }
            for index in requested
            if index in qa_by_index
        ]
        missing = [index for index in requested if index not in qa_by_index]
        if missing:
            result["missing_question_indexes"] = missing
    return result


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _list_records(args, ctx, service) -> dict[str, Any]:
    records = service.list_by_user(ctx.user_id, limit=args.limit)
    if not records:
        return {"message": "No interview records found", "count": 0, "records": []}

    items = []
    for r in records:
        a = {}
        if r.analysis_json:
            try:
                a = json.loads(r.analysis_json)
            except json.JSONDecodeError:
                pass
        overall = a.get("overall", {})
        items.append(
            {
                "record_id": r.id,
                "source": r.source,
                "title": r.title,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "overall_score": overall.get("score"),
                "overall_summary": str(
                    overall.get("summary") or overall.get("feedback", ""),
                )[:200],
            }
        )
    return {"count": len(items), "records": items}


registry.register(
    ToolDefinition(
        name="read_interview_history",
        description=(
            "Read past interview records and analysis. Without record_id: "
            "lists recent interviews with scores. With record_id: returns "
            "the overall report. Add question_indexes to fetch one or more "
            "questions' full answers, scores, critiques, and improved answers "
            "in one call."
        ),
        args_model=ReadInterviewHistoryArgs,
        handler=_read_interview_history_handler,
        effect=ToolEffect.READ,
        concurrency_safe=True,
        max_result_chars=10_000,
        emoji="📊",
    )
)
