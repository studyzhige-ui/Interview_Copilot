"""Authenticated Gmail Observation, sync, review, and correction API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.gmail_integration import get_gmail_provider_adapter
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.gmail_observation import (
    GmailObservationCardResolve,
    GmailObservationRebaseline,
    GmailObservationResolutionView,
    GmailObservationRetract,
    GmailObservationReviewCardView,
    GmailObservationSyncView,
    GmailObservationView,
)
from app.services import (
    gmail_integration_service,
    gmail_observation_service,
    gmail_observation_sync_service,
)
from app.services.career_process_service import CareerProcessError


router = APIRouter(tags=["gmail-observations"])
logger = logging.getLogger(__name__)


def _observation_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, gmail_observation_service.GmailObservationNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, gmail_observation_service.GmailObservationConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, gmail_observation_service.GmailObservationScopeError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, gmail_integration_service.GmailConnectionRequiredError):
        return HTTPException(status_code=409, detail="gmail_connection_required")
    if isinstance(exc, gmail_integration_service.GmailProviderAdapterError):
        code = exc.code
        return HTTPException(
            status_code=(409 if code == "history_cursor_expired" else 502),
            detail=code,
        )
    if isinstance(exc, gmail_integration_service.GmailIntegrationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=422, detail="gmail_observation_command_failed")


def _require_adapter(adapter):
    if adapter is None:
        raise HTTPException(status_code=503, detail="gmail_adapter_unavailable")
    return adapter


def _sync_view(
    result: gmail_observation_sync_service.GmailObservationSyncResult,
) -> GmailObservationSyncView:
    turn_ids = list(result.admitted_turn_ids)
    return GmailObservationSyncView(
        initialized_cursor=result.initialized_cursor,
        cursor_after=result.cursor_after,
        observations_created=result.observations_created,
        snapshots_created=result.snapshots_created,
        triggers_created=result.triggers_created,
        turns_admitted=len(turn_ids),
        turn_ids=turn_ids,
    )


async def _perform_sync(
    db: Session,
    *,
    user_pk: int,
    adapter,
) -> GmailObservationSyncView:
    account = gmail_integration_service.get_account(db, user_pk=user_pk)
    if account is None:
        raise HTTPException(status_code=409, detail="gmail_connection_required")
    try:
        result = await gmail_observation_sync_service.sync_gmail_observations(
            db,
            user_pk=user_pk,
            account_id=account.id,
            adapter=adapter,
        )
        db.commit()
    except (
        gmail_integration_service.GmailProviderAdapterError,
        gmail_integration_service.GmailConnectionRequiredError,
    ) as exc:
        db.rollback()
        with db.begin():
            gmail_observation_sync_service.persist_sync_failure(
                db,
                user_pk=user_pk,
                account_id=account.id,
                error=exc,
            )
        raise _observation_http_error(exc) from exc
    except (
        gmail_integration_service.GmailIntegrationError,
        gmail_observation_service.GmailObservationError,
    ) as exc:
        db.rollback()
        raise _observation_http_error(exc) from exc

    try:
        gmail_observation_sync_service.dispatch_sync_admissions(result)
    except Exception:  # noqa: BLE001 - durable trigger/Turn repair owns retry
        logger.exception("Gmail Observation Turn dispatch deferred to repair")
    return _sync_view(result)


@router.get(
    "/gmail/observations",
    response_model=list[GmailObservationView],
)
def get_gmail_observations(
    statuses: list[str] = Query(default=[]),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed = {
        "unreviewed",
        "pending_confirmation",
        "applied",
        "dismissed",
        "retracted",
    }
    selected = set(statuses)
    if not selected.issubset(allowed):
        raise HTTPException(status_code=422, detail="unsupported_observation_status")
    return gmail_observation_service.list_observations(
        db,
        user_pk=current_user.id,
        statuses=selected or None,
        limit=limit,
    )


@router.post(
    "/gmail/observations/sync",
    response_model=GmailObservationSyncView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_gmail_observations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter=Depends(get_gmail_provider_adapter),
):
    return await _perform_sync(
        db,
        user_pk=current_user.id,
        adapter=_require_adapter(adapter),
    )


@router.post(
    "/gmail/observations/rebaseline",
    response_model=GmailObservationSyncView,
)
async def rebaseline_gmail_observations(
    body: GmailObservationRebaseline,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter=Depends(get_gmail_provider_adapter),
):
    del body  # Pydantic has already required explicit confirm_gap=true.
    account = gmail_integration_service.get_account(db, user_pk=current_user.id)
    if account is None:
        raise HTTPException(status_code=409, detail="gmail_connection_required")
    try:
        gmail_observation_service.rebaseline_history_cursor(
            db,
            user_pk=current_user.id,
            account_id=account.id,
        )
    except gmail_observation_service.GmailObservationError as exc:
        db.rollback()
        raise _observation_http_error(exc) from exc
    return await _perform_sync(
        db,
        user_pk=current_user.id,
        adapter=_require_adapter(adapter),
    )


@router.get(
    "/persistent-tasks/{task_id}/gmail-review-cards",
    response_model=list[GmailObservationReviewCardView],
)
def get_gmail_review_cards(
    task_id: str,
    statuses: list[str] = Query(default=[]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed = {"pending", "approved", "rejected", "skipped"}
    selected = set(statuses)
    if not selected.issubset(allowed):
        raise HTTPException(status_code=422, detail="unsupported_review_card_status")
    try:
        return gmail_observation_service.list_review_cards(
            db,
            user_pk=current_user.id,
            task_id=task_id,
            statuses=selected or None,
        )
    except gmail_observation_service.GmailObservationError as exc:
        raise _observation_http_error(exc) from exc


@router.post(
    "/persistent-tasks/{task_id}/gmail-review-cards/{card_id}/resolve",
    response_model=GmailObservationResolutionView,
)
def resolve_gmail_review_card(
    task_id: str,
    card_id: str,
    body: GmailObservationCardResolve,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = gmail_observation_service.resolve_review_card(
            db,
            user_pk=current_user.id,
            task_id=task_id,
            card_id=card_id,
            command=body,
        )
        db.commit()
        return GmailObservationResolutionView(
            outcome=result.outcome,
            observation=gmail_observation_service.get_observation(
                db,
                user_pk=current_user.id,
                observation_id=result.observation.id,
            ),
            review_card=gmail_observation_service.get_review_card(
                db,
                user_pk=current_user.id,
                task_id=task_id,
                card_id=card_id,
            ),
            process_event_id=result.process_event_id,
        )
    except (
        gmail_observation_service.GmailObservationError,
        CareerProcessError,
    ) as exc:
        db.rollback()
        if isinstance(exc, gmail_observation_service.GmailObservationError):
            raise _observation_http_error(exc) from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/gmail/observations/{observation_id}/retract",
    response_model=GmailObservationView,
)
def retract_gmail_observation(
    observation_id: str,
    body: GmailObservationRetract,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        gmail_observation_service.retract_applied_observation(
            db,
            user_pk=current_user.id,
            observation_id=observation_id,
            command=body,
        )
        db.commit()
        return gmail_observation_service.get_observation(
            db,
            user_pk=current_user.id,
            observation_id=observation_id,
        )
    except gmail_observation_service.GmailObservationError as exc:
        db.rollback()
        raise _observation_http_error(exc) from exc
    except CareerProcessError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["router"]
