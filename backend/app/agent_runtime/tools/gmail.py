"""Concrete Gmail read ToolDefinition, composed only with a real adapter.

This module intentionally does not self-register.  A deployment must supply a
real ``GmailProviderAdapter`` backed by controlled credential infrastructure,
then register ``build_gmail_search_messages_tool(factory)`` in the existing
single Tool Registry.  Until then, the product must not advertise this Tool.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition
from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.schemas.gmail_integration import GmailSearchMessagesArgs
from app.services.gmail_integration_service import (
    GMAIL_READONLY_SCOPE,
    GmailAccountNotFoundError,
    GmailConnectionRequiredError,
    GmailIntegrationError,
    GmailProviderAdapter,
    GmailProviderAdapterError,
    search_messages,
)


GmailAdapterFactory = Callable[[], GmailProviderAdapter]


def build_gmail_search_messages_tool(
    adapter_factory: GmailAdapterFactory,
) -> ToolDefinition:
    """Build the real Tool only when deployment composition has an adapter."""

    async def handler(
        args: GmailSearchMessagesArgs,
        ctx: AgentToolContext,
    ) -> dict[str, Any]:
        return await _gmail_search_messages_handler(
            args,
            ctx,
            adapter=adapter_factory(),
        )

    return ToolDefinition(
        name="gmail_search_messages",
        description=(
            "Search the user's connected Gmail account with a narrow Gmail "
            "query and return bounded message metadata/snippets. This is "
            "read-only and does not send, modify, label, or delete email."
        ),
        args_model=GmailSearchMessagesArgs,
        handler=handler,
        effect=ToolEffect.READ,
        # Missing connection/scope must pause the untouched batch on this call.
        concurrency_safe=False,
        max_result_chars=12_000,
        emoji="📨",
    )


async def _gmail_search_messages_handler(
    args: GmailSearchMessagesArgs,
    ctx: AgentToolContext,
    *,
    adapter: GmailProviderAdapter,
) -> dict[str, Any]:
    with SessionLocal() as db:
        user_pk = resolve_user_pk(db, ctx.user_id)
        if user_pk is None:
            return {"error": "user_not_found", "provider": "gmail"}
        try:
            result = await search_messages(
                db,
                user_pk=user_pk,
                query=args.query,
                limit=args.limit,
                adapter=adapter,
            )
            return result.model_dump(mode="json")
        except (GmailAccountNotFoundError, GmailConnectionRequiredError) as exc:
            # Persist an invalid-grant transition produced by the read attempt.
            db.commit()
            return {
                "error": "connection_required",
                "reason": str(exc),
                "provider": "gmail",
                "required_scope": GMAIL_READONLY_SCOPE,
            }
        except GmailProviderAdapterError as exc:
            db.rollback()
            return {
                "error": "provider_request_failed",
                "provider": "gmail",
                "error_code": exc.code,
                "retryable": exc.retryable,
            }
        except GmailIntegrationError:
            db.rollback()
            return {
                "error": "gmail_read_failed",
                "provider": "gmail",
                "retryable": False,
            }
        except Exception:  # noqa: BLE001
            db.rollback()
            return {
                "error": "provider_request_failed",
                "provider": "gmail",
                "error_code": "unexpected_provider_error",
                "retryable": False,
            }


__all__ = [
    "GmailAdapterFactory",
    "build_gmail_search_messages_tool",
]
