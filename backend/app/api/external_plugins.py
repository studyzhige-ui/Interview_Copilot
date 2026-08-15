"""Marketplace-native Canva and Notion OAuth lifecycle API."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_AUTH, limiter
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.external_plugin_connection import ExternalPluginAccount
from app.models.user import User
from app.schemas.external_plugin_connection import (
    ExternalPluginAccountView,
    ExternalPluginOAuthAuthorizationView,
    ExternalPluginProvider,
    ExternalPluginStatusView,
)
from app.services.oauth_plugin_connector import (
    ExternalPluginError,
    OAuthPluginConnector,
    bind_external_plugin_account,
    configured_external_plugin_connectors,
    get_external_plugin_account,
    revoke_external_plugin_account,
    test_external_plugin_account,
)


router = APIRouter(prefix="/integrations/plugins", tags=["integrations"])


def get_external_plugin_connectors() -> dict[
    ExternalPluginProvider, OAuthPluginConnector
]:
    return configured_external_plugin_connectors()


def _connector(
    provider: ExternalPluginProvider,
    connectors: dict[ExternalPluginProvider, OAuthPluginConnector],
) -> OAuthPluginConnector:
    connector = connectors.get(provider)
    if connector is None:
        raise HTTPException(status_code=503, detail="plugin_adapter_unavailable")
    return connector


def _view(
    provider: ExternalPluginProvider,
    row: ExternalPluginAccount | None,
    *,
    adapter_available: bool,
) -> ExternalPluginStatusView:
    return ExternalPluginStatusView(
        provider=provider,
        adapter_available=adapter_available,
        connection_required=row is None or row.status != "active",
        account=ExternalPluginAccountView.model_validate(row)
        if row is not None
        else None,
    )


def _cookie_name(provider: ExternalPluginProvider) -> str:
    return f"plugin_oauth_state_{provider}"


def _redirect(
    connector: OAuthPluginConnector,
    *,
    outcome: str,
    error_code: str | None = None,
) -> RedirectResponse:
    response = RedirectResponse(
        connector.product_return_url(outcome=outcome, error_code=error_code),
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    response.delete_cookie(
        _cookie_name(connector.provider),
        path=connector.callback_cookie_path,
        secure=connector.callback_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/{provider}", response_model=ExternalPluginStatusView)
def get_plugin_status(
    provider: ExternalPluginProvider,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    connectors: dict[ExternalPluginProvider, OAuthPluginConnector] = Depends(
        get_external_plugin_connectors
    ),
):
    return _view(
        provider,
        get_external_plugin_account(db, user_pk=current_user.id, provider=provider),
        adapter_available=provider in connectors,
    )


@router.post(
    "/{provider}/authorize", response_model=ExternalPluginOAuthAuthorizationView
)
@limiter.limit(RATE_AUTH)
def authorize_plugin(
    request: Request,
    response: Response,
    provider: ExternalPluginProvider,
    current_user: User = Depends(get_current_user),
    connectors: dict[ExternalPluginProvider, OAuthPluginConnector] = Depends(
        get_external_plugin_connectors
    ),
):
    connector = _connector(provider, connectors)
    authorization = connector.begin_authorization(user_pk=current_user.id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(
        _cookie_name(provider),
        authorization.state_binding,
        max_age=authorization.expires_in_seconds,
        path=connector.callback_cookie_path,
        secure=connector.callback_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return ExternalPluginOAuthAuthorizationView(
        provider=provider,
        authorization_url=authorization.authorization_url,
        expires_in_seconds=authorization.expires_in_seconds,
    )


@router.get("/{provider}/callback", response_class=RedirectResponse)
@limiter.limit(RATE_AUTH)
async def complete_plugin_authorization(
    request: Request,
    provider: ExternalPluginProvider,
    state: str | None = Query(default=None),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
    connectors: dict[ExternalPluginProvider, OAuthPluginConnector] = Depends(
        get_external_plugin_connectors
    ),
):
    connector = _connector(provider, connectors)
    if state is None or not 20 <= len(state) <= 512:
        return _redirect(connector, outcome="failed", error_code="oauth_state_invalid")
    cookie_state = request.cookies.get(_cookie_name(provider))
    if cookie_state is None or not secrets.compare_digest(state, cookie_state):
        return _redirect(connector, outcome="failed", error_code="oauth_state_invalid")
    if code is not None and not 1 <= len(code) <= 4096:
        return _redirect(connector, outcome="failed", error_code="oauth_code_invalid")
    if error is not None and not 1 <= len(error) <= 128:
        error = "provider_error"
    try:
        completion = await connector.complete_authorization(
            state=state,
            code=code,
            provider_error=error,
        )
        bind_external_plugin_account(db, completion)
        db.commit()
        return _redirect(connector, outcome="connected")
    except ExternalPluginError as exc:
        db.rollback()
        return _redirect(connector, outcome="failed", error_code=exc.code)
    except Exception:
        db.rollback()
        return _redirect(connector, outcome="failed", error_code="provider_error")


@router.post("/{provider}/test", response_model=ExternalPluginStatusView)
async def test_plugin(
    provider: ExternalPluginProvider,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    connectors: dict[ExternalPluginProvider, OAuthPluginConnector] = Depends(
        get_external_plugin_connectors
    ),
):
    connector = _connector(provider, connectors)
    if (
        get_external_plugin_account(db, user_pk=current_user.id, provider=provider)
        is None
    ):
        raise HTTPException(status_code=409, detail="plugin_connection_required")
    row = await test_external_plugin_account(
        db, user_pk=current_user.id, connector=connector
    )
    db.commit()
    return _view(provider, row, adapter_available=True)


@router.post("/{provider}/revoke", response_model=ExternalPluginStatusView)
async def revoke_plugin(
    provider: ExternalPluginProvider,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    connectors: dict[ExternalPluginProvider, OAuthPluginConnector] = Depends(
        get_external_plugin_connectors
    ),
):
    connector = _connector(provider, connectors)
    if (
        get_external_plugin_account(db, user_pk=current_user.id, provider=provider)
        is None
    ):
        raise HTTPException(status_code=409, detail="plugin_connection_required")
    try:
        row = await revoke_external_plugin_account(
            db, user_pk=current_user.id, connector=connector
        )
        db.commit()
        return _view(provider, row, adapter_available=True)
    except ExternalPluginError as exc:
        db.rollback()
        status = 409 if exc.code == "invalid_grant" else 502
        raise HTTPException(status_code=status, detail=exc.code) from exc


__all__ = ["get_external_plugin_connectors", "router"]
