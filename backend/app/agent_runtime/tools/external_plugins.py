"""Concrete read-only Canva and Notion tools backed by real OAuth adapters."""

from __future__ import annotations

from typing import Any

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import (
    AgentToolContext,
    ToolDefinition,
    ToolPreflightResult,
)
from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.schemas.external_plugin_connection import (
    CanvaSearchDesignsArgs,
    NotionSearchPagesArgs,
)
from app.services.oauth_plugin_connector import (
    ExternalPluginError,
    OAuthPluginConnector,
    external_plugin_account_handle,
    get_external_plugin_account,
)


def build_canva_search_designs_tool(connector: OAuthPluginConnector) -> ToolDefinition:
    async def handler(
        args: CanvaSearchDesignsArgs, ctx: AgentToolContext
    ) -> dict[str, Any]:
        return await _search_canva(args, ctx, connector=connector)

    return ToolDefinition(
        name="canva_search_designs",
        description=(
            "Search metadata for designs in the user's connected Canva account. "
            "This read-only tool does not edit, export, publish, or create designs."
        ),
        args_model=CanvaSearchDesignsArgs,
        handler=handler,
        effect=ToolEffect.READ,
        preflight=lambda args, ctx: _preflight("canva", ctx),
        concurrency_safe=False,
        max_result_chars=12_000,
        emoji="🎨",
    )


def build_notion_search_pages_tool(connector: OAuthPluginConnector) -> ToolDefinition:
    async def handler(
        args: NotionSearchPagesArgs, ctx: AgentToolContext
    ) -> dict[str, Any]:
        return await _search_notion(args, ctx, connector=connector)

    return ToolDefinition(
        name="notion_search_pages",
        description=(
            "Search titles of pages explicitly shared with the user's connected "
            "Notion connection. This read-only tool does not read an entire "
            "workspace or write pages."
        ),
        args_model=NotionSearchPagesArgs,
        handler=handler,
        effect=ToolEffect.READ,
        preflight=lambda args, ctx: _preflight("notion", ctx),
        concurrency_safe=False,
        max_result_chars=12_000,
        emoji="📓",
    )


def _preflight(provider: str, ctx: AgentToolContext) -> ToolPreflightResult:
    with SessionLocal() as db:
        user_pk = ctx.user_pk or resolve_user_pk(db, ctx.user_id)
        if user_pk is None:
            return ToolPreflightResult(
                connection_ready=False, hard_deny_reason="user_not_found"
            )
        account = get_external_plugin_account(db, user_pk=user_pk, provider=provider)  # type: ignore[arg-type]
        ready = bool(
            account is not None
            and account.status == "active"
            and account.credential_handle_ciphertext
        )
        return ToolPreflightResult(
            connection_ready=ready,
            resource_identities=(f"{provider}-account:{user_pk}",),
            provider_identity=provider,
            connection_identity=(
                f"{provider}-account:{account.id}" if ready and account else None
            ),
        )


async def _search_canva(
    args: CanvaSearchDesignsArgs,
    ctx: AgentToolContext,
    *,
    connector: OAuthPluginConnector,
) -> dict[str, Any]:
    return await _execute_search("canva", args, ctx, connector=connector)


async def _search_notion(
    args: NotionSearchPagesArgs,
    ctx: AgentToolContext,
    *,
    connector: OAuthPluginConnector,
) -> dict[str, Any]:
    return await _execute_search("notion", args, ctx, connector=connector)


async def _execute_search(
    provider: str,
    args: CanvaSearchDesignsArgs | NotionSearchPagesArgs,
    ctx: AgentToolContext,
    *,
    connector: OAuthPluginConnector,
) -> dict[str, Any]:
    with SessionLocal() as db:
        user_pk = ctx.user_pk or resolve_user_pk(db, ctx.user_id)
        if user_pk is None:
            return {"error": "user_not_found", "provider": provider}
        account = get_external_plugin_account(db, user_pk=user_pk, provider=provider)  # type: ignore[arg-type]
        if account is None or account.status != "active":
            return {"error": "connection_required", "provider": provider}
        try:
            handle = external_plugin_account_handle(account)
            if provider == "canva" and isinstance(args, CanvaSearchDesignsArgs):
                return await connector.search_canva_designs(
                    handle,
                    user_pk=user_pk,
                    query=args.query,
                    limit=args.limit,
                )
            if provider == "notion" and isinstance(args, NotionSearchPagesArgs):
                return await connector.search_notion_pages(
                    handle,
                    user_pk=user_pk,
                    query=args.query,
                    limit=args.limit,
                )
            return {"error": "invalid_request", "provider": provider}
        except ExternalPluginError as exc:
            return {
                "error": "connection_required"
                if exc.code == "invalid_grant"
                else "provider_request_failed",
                "provider": provider,
                "error_code": exc.code,
                "retryable": exc.retryable,
            }


__all__ = ["build_canva_search_designs_tool", "build_notion_search_pages_tool"]
