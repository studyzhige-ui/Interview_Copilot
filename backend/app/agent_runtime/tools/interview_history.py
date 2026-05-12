"""Interview history tool: read_interview_history.

Wraps InterviewRecordService to read past interview records and analysis.
"""

import json
from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry


class ReadInterviewHistoryArgs(BaseModel):
    record_id: str = Field(default="", description="Specific record ID. Empty = list recent.")
    limit: int = Field(default=5, ge=1, le=20, description="Max records when listing")


async def _read_interview_history_handler(
    args: ReadInterviewHistoryArgs, ctx: AgentToolContext
) -> dict[str, Any]:
    from app.services.interview_record_service import interview_record_service

    if args.record_id:
        record = interview_record_service.get(args.record_id, ctx.user_id)
        if record is None:
            return {"error": "Interview record not found", "record_id": args.record_id}
        analysis = {}
        if record.analysis_json:
            try:
                analysis = json.loads(record.analysis_json)
            except json.JSONDecodeError:
                pass
        overall = analysis.get("overall", {})
        return {
            "record_id": record.id,
            "source": record.source,
            "title": record.title,
            "status": record.status,
            "created_at": record.created_at.isoformat() if record.created_at else "",
            "overall_score": overall.get("score"),
            "grade": overall.get("grade", ""),
            "verdict": overall.get("verdict", ""),
            "overall_feedback": overall.get("feedback", ""),
            "strengths": overall.get("strengths", []),
            "weaknesses": overall.get("weaknesses", []),
            "improvement_plan": overall.get("improvement_plan", []),
        }

    records = interview_record_service.list_by_user(ctx.user_id, limit=args.limit)
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
        items.append({
            "record_id": r.id, "source": r.source, "title": r.title,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "overall_score": overall.get("score"),
            "overall_feedback": str(overall.get("feedback", ""))[:200],
        })
    return {"count": len(items), "records": items}


registry.register(ToolEntry(
    name="read_interview_history",
    description="Read past interview records and analysis. Without record_id: lists recent interviews with scores. With record_id: returns detailed analysis including strengths, weaknesses, and improvement suggestions.",
    args_model=ReadInterviewHistoryArgs,
    handler=_read_interview_history_handler,
    max_result_chars=10000,
    emoji="📊",
))
