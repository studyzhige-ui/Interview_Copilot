"""Safe Gmail OAuth lifecycle and account-state API.

The callback accepts only Google's short-lived authorization code and one-time
state. OAuth tokens and opaque credential handles remain inside the controlled
provider adapter and are never accepted from, or returned to, product clients.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.rate_limit import RATE_AUTH, limiter
from app.db.database import get_db
from app.models.gmail_integration import GmailIntegrationAccount
from app.models.user import User
from app.schemas.gmail_integration import (
    GmailIntegrationAccountView,
    GmailIntegrationStatusView,
    GmailOAuthAuthorizationView,
)
from app.services import gmail_integration_service
from app.services.google_gmail_connector import (
    GmailOAuthCompletion,
    GmailOAuthFlowError,
    GoogleGmailConnector,
    build_configured_google_gmail_connector,
)


router = APIRouter(prefix="/integrations/gmail", tags=["integrations"])
_OAUTH_STATE_COOKIE = "gmail_oauth_state_binding"

_SAFE_CALLBACK_ERROR_CODES = frozenset(
    {
        "gmail_readonly_scope_required",
        "google_email_unverified",
        "invalid_grant",
        "oauth_authorization_denied",
        "oauth_code_invalid",
        "oauth_exchange_failed",
        "oauth_state_expired",
        "oauth_state_invalid",
        "provider_timeout",
        "provider_unavailable",
        "refresh_token_missing",
    }
)


def get_gmail_provider_adapter() -> (
    gmail_integration_service.GmailProviderAdapter | None
):
    """Deployment seam; incomplete OAuth configuration fails closed."""

    return build_configured_google_gmail_connector()


def get_gmail_oauth_connector() -> GoogleGmailConnector | None:
    """OAuth-flow seam kept distinct for focused API dependency overrides."""

    return build_configured_google_gmail_connector()


def _view(
    row: GmailIntegrationAccount | None,
    *,
    adapter_available: bool,
) -> GmailIntegrationStatusView:
    return GmailIntegrationStatusView(
        adapter_available=adapter_available,
        connection_required=row is None or row.status != "active",
        account=(
            GmailIntegrationAccountView.model_validate(row) if row is not None else None
        ),
    )


def _require_adapter(
    row: GmailIntegrationAccount | None,
    adapter: gmail_integration_service.GmailProviderAdapter | None,
) -> gmail_integration_service.GmailProviderAdapter:
    if row is None or row.status == "revoked":
        raise HTTPException(status_code=409, detail="gmail_connection_required")
    if adapter is None:
        raise HTTPException(status_code=503, detail="gmail_adapter_unavailable")
    return adapter


def _integration_http_error(
    exc: gmail_integration_service.GmailIntegrationError,
) -> HTTPException:
    if isinstance(exc, GmailOAuthFlowError):
        if exc.code in {
            "oauth_state_invalid",
            "oauth_state_expired",
            "oauth_authorization_denied",
            "oauth_code_invalid",
            "refresh_token_missing",
            "gmail_readonly_scope_required",
            "google_email_unverified",
        }:
            return HTTPException(status_code=400, detail=exc.code)
        if exc.code == "oauth_state_store_failed":
            return HTTPException(status_code=503, detail=exc.code)
        return HTTPException(status_code=502, detail=exc.code)
    if isinstance(
        exc,
        (
            gmail_integration_service.GmailAccountNotFoundError,
            gmail_integration_service.GmailConnectionRequiredError,
            gmail_integration_service.GmailCredentialHandleError,
        ),
    ):
        return HTTPException(status_code=409, detail="gmail_connection_required")
    if isinstance(exc, gmail_integration_service.GmailProviderAdapterError):
        return HTTPException(status_code=502, detail=exc.code)
    return HTTPException(status_code=422, detail=str(exc))


def _require_oauth_connector(
    connector: GoogleGmailConnector | None,
) -> GoogleGmailConnector:
    if connector is None:
        raise HTTPException(status_code=503, detail="gmail_adapter_unavailable")
    return connector


def _callback_error_code(
    exc: gmail_integration_service.GmailIntegrationError,
) -> str:
    code = getattr(exc, "code", str(exc))
    return code if code in _SAFE_CALLBACK_ERROR_CODES else "provider_error"


def _oauth_redirect(
    connector: GoogleGmailConnector,
    *,
    outcome: str,
    error_code: str | None = None,
) -> RedirectResponse:
    response = RedirectResponse(
        connector.product_return_url(
            outcome=outcome,
            error_code=error_code,
        ),
        status_code=303,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )
    response.delete_cookie(
        _OAUTH_STATE_COOKIE,
        path=connector.callback_cookie_path,
        secure=connector.callback_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


async def _cleanup_failed_rebind(
    db: Session,
    connector: GoogleGmailConnector,
    completion: GmailOAuthCompletion,
    *,
    error_code: str,
) -> None:
    """Best-effort remote cleanup plus an honest public account transition."""

    try:
        await connector.revoke_grant(
            completion.credential_handle,
            user_pk=completion.user_pk,
        )
    except Exception:
        # The encrypted broker row is retained when Google did not confirm
        # revocation, allowing the user to retry revoke from the invalid state.
        pass
    try:
        gmail_integration_service.mark_reconnect_required(
            db,
            user_pk=completion.user_pk,
            error_code=error_code,
        )
        db.commit()
    except Exception:
        db.rollback()


@router.get("", response_model=GmailIntegrationStatusView)
def get_gmail_integration(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    connector: GoogleGmailConnector | None = Depends(get_gmail_oauth_connector),
):
    return _view(
        gmail_integration_service.get_account(db, user_pk=current_user.id),
        adapter_available=connector is not None,
    )


@router.post("/authorize", response_model=GmailOAuthAuthorizationView)
@limiter.limit(RATE_AUTH)
def authorize_gmail_integration(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    connector: GoogleGmailConnector | None = Depends(get_gmail_oauth_connector),
):
    concrete_connector = _require_oauth_connector(connector)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        authorization = concrete_connector.begin_authorization(user_pk=current_user.id)
        response.set_cookie(
            _OAUTH_STATE_COOKIE,
            authorization.state_binding,
            max_age=authorization.expires_in_seconds,
            path=concrete_connector.callback_cookie_path,
            secure=concrete_connector.callback_cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return GmailOAuthAuthorizationView(
            authorization_url=authorization.authorization_url,
            expires_in_seconds=authorization.expires_in_seconds,
        )
    except gmail_integration_service.GmailIntegrationError as exc:
        raise _integration_http_error(exc) from exc


@router.get("/callback", response_class=RedirectResponse)
@limiter.limit(RATE_AUTH)
async def complete_gmail_authorization(
    request: Request,
    state: str | None = Query(default=None),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
    connector: GoogleGmailConnector | None = Depends(get_gmail_oauth_connector),
):
    concrete_connector = _require_oauth_connector(connector)
    # Validate manually so malformed real-browser callbacks still return to
    # the product page with a fixed error enum; framework 422 JSON would strand
    # the browser on the API endpoint and could reflect validation details.
    if state is None or not 20 <= len(state) <= 512:
        return _oauth_redirect(
            concrete_connector,
            outcome="failed",
            error_code="oauth_state_invalid",
        )
    cookie_state = request.cookies.get(_OAUTH_STATE_COOKIE)
    if (
        cookie_state is None
        or not 20 <= len(cookie_state) <= 512
        or not secrets.compare_digest(state, cookie_state)
    ):
        # Do not claim/delete the durable state. The original browser can
        # still complete its own flow, while a different browser or login-CSRF
        # attempt gets only a bounded failure redirect.
        return _oauth_redirect(
            concrete_connector,
            outcome="failed",
            error_code="oauth_state_invalid",
        )
    if code is not None and not 1 <= len(code) <= 4096:
        return _oauth_redirect(
            concrete_connector,
            outcome="failed",
            error_code="oauth_code_invalid",
        )
    if error is not None and not 1 <= len(error) <= 128:
        # The provider's prose is not part of our public error contract.
        error = "provider_error"
    completion = None
    try:
        completion = await concrete_connector.complete_authorization(
            state=state,
            code=code,
            provider_error=error,
        )
        await gmail_integration_service.bind_verified_grant(
            db,
            user_pk=completion.user_pk,
            credential_handle=completion.credential_handle,
            adapter=concrete_connector,
        )
        db.commit()
        return _oauth_redirect(concrete_connector, outcome="connected")
    except gmail_integration_service.GmailIntegrationError as exc:
        db.rollback()
        callback_error_code = _callback_error_code(exc)
        if completion is not None:
            # The broker grant supersedes any previous per-user grant before
            # public binding. If binding then fails, the old public row must
            # not keep advertising an active connection to that now-replaced
            # credential generation.
            await _cleanup_failed_rebind(
                db,
                concrete_connector,
                completion,
                error_code=callback_error_code,
            )
        return _oauth_redirect(
            concrete_connector,
            outcome="failed",
            error_code=callback_error_code,
        )
    except Exception:
        db.rollback()
        if completion is not None:
            await _cleanup_failed_rebind(
                db,
                concrete_connector,
                completion,
                error_code="provider_error",
            )
        return _oauth_redirect(
            concrete_connector,
            outcome="failed",
            error_code="provider_error",
        )


@router.post("/test", response_model=GmailIntegrationStatusView)
async def test_gmail_integration(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: gmail_integration_service.GmailProviderAdapter | None = Depends(
        get_gmail_provider_adapter
    ),
):
    current = gmail_integration_service.get_account(db, user_pk=current_user.id)
    concrete_adapter = _require_adapter(current, adapter)
    try:
        row = await gmail_integration_service.test_account(
            db,
            user_pk=current_user.id,
            adapter=concrete_adapter,
        )
        db.commit()
        return _view(row, adapter_available=True)
    except gmail_integration_service.GmailIntegrationError as exc:
        db.rollback()
        raise _integration_http_error(exc) from exc
    except Exception:
        db.rollback()
        raise


@router.post("/revoke", response_model=GmailIntegrationStatusView)
async def revoke_gmail_integration(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: gmail_integration_service.GmailProviderAdapter | None = Depends(
        get_gmail_provider_adapter
    ),
):
    current = gmail_integration_service.get_account(db, user_pk=current_user.id)
    concrete_adapter = _require_adapter(current, adapter)
    try:
        row = await gmail_integration_service.revoke_account(
            db,
            user_pk=current_user.id,
            adapter=concrete_adapter,
        )
        db.commit()
        return _view(row, adapter_available=True)
    except gmail_integration_service.GmailIntegrationError as exc:
        db.rollback()
        raise _integration_http_error(exc) from exc
    except Exception:
        db.rollback()
        raise


__all__ = [
    "get_gmail_oauth_connector",
    "get_gmail_provider_adapter",
    "router",
]
