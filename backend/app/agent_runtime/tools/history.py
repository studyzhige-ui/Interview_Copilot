"""Exact History Search Tool over canonical Interaction Records."""

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.agent_runtime.tool_policy import ToolEffect
from app.db.database import SessionLocal
from app.schemas.history_search import HistorySearchQuery
from app.services.interaction_history_service import (
    get_interaction_history_record,
    search_interaction_history,
)


class SearchInteractionHistoryArgs(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    conversation_id: str | None = Field(
        default=None,
        description="Optional exact Conversation identity; omit to search this user account.",
    )
    kinds: list[Literal["message", "tool_call"]] = Field(
        default_factory=lambda: ["message", "tool_call"]
    )
    limit: int = Field(default=10, ge=1, le=25)


class ReadInteractionHistoryArgs(BaseModel):
    identity: str = Field(
        min_length=3,
        max_length=300,
        description=(
            "Exact identity returned by search_interaction_history, such as "
            "conversation_message:123 or agent_tool_call:<turn_id>:<call_id>."
        ),
    )


async def _search_history_handler(
    args: SearchInteractionHistoryArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    if ctx.user_pk is None:
        return {"error": "history_owner_unavailable"}
    return await asyncio.to_thread(_search_history_sync, args, ctx)


def _search_history_sync(
    args: SearchInteractionHistoryArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    with SessionLocal() as db:
        view = search_interaction_history(
            db,
            user_pk=int(ctx.user_pk or 0),
            request=HistorySearchQuery(
                query=args.query,
                conversation_id=args.conversation_id,
                kinds=args.kinds,
                limit=args.limit,
            ),
        )
        return view.model_dump(mode="json")


async def _read_history_handler(
    args: ReadInteractionHistoryArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    if ctx.user_pk is None:
        return {"error": "history_owner_unavailable"}

    def read() -> dict[str, Any]:
        with SessionLocal() as db:
            return get_interaction_history_record(
                db,
                user_pk=int(ctx.user_pk or 0),
                identity=args.identity,
            ).model_dump(mode="json")

    return await asyncio.to_thread(read)


registry.register(
    ToolDefinition(
        name="search_interaction_history",
        description=(
            "Search the user's exact prior Conversation messages and Tool Call/Result "
            "records by text. Use this for what was actually said or executed in the "
            "past; it does not prove that an old claim is still currently true."
        ),
        args_model=SearchInteractionHistoryArgs,
        handler=_search_history_handler,
        effect=ToolEffect.READ,
        concurrency_safe=True,
        max_result_chars=12_000,
        emoji="🕘",
    )
)

registry.register(
    ToolDefinition(
        name="read_interaction_history",
        description=(
            "Read one exact prior Conversation message or Tool Call/Result by the "
            "stable identity returned from search_interaction_history. Use this "
            "instead of treating a search excerpt as the full historical record."
        ),
        args_model=ReadInteractionHistoryArgs,
        handler=_read_history_handler,
        effect=ToolEffect.READ,
        concurrency_safe=True,
        max_result_chars=20_000,
        emoji="🧾",
    )
)


__all__ = ["ReadInteractionHistoryArgs", "SearchInteractionHistoryArgs"]
