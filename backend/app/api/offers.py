"""Read and confirm the single current Offer for a JobOpportunity."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.agent_execution import AgentToolCall
from app.models.artifact import Artifact, ArtifactVersion
from app.models.chat import Conversation, ConversationMessage
from app.models.file_asset import FileAsset
from app.models.job_opportunity import JobOpportunity
from app.models.user import User
from app.schemas.offer import (
    OfferConfirmationRequiredView,
    OfferConfirmTermsRequest,
    OfferCurrentResponse,
    OfferRecordRequest,
    OfferView,
)
from app.services import offer_service
from app.services.uploads.file_asset_service import READABLE_UPLOAD_STATUSES

router = APIRouter(prefix="/career-process/opportunities", tags=["offers"])


def _owned_job_checker(db: Session, user_pk: int, job_id: str) -> bool:
    return (
        db.query(JobOpportunity.id)
        .filter(JobOpportunity.id == job_id, JobOpportunity.user_id == user_pk)
        .scalar()
        is not None
    )


def _require_owned_job(
    db: Session,
    user_pk: int,
    job_id: str,
    *,
    active: bool,
) -> JobOpportunity:
    job = (
        db.query(JobOpportunity)
        .filter(JobOpportunity.id == job_id, JobOpportunity.user_id == user_pk)
        .one_or_none()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="JobOpportunity not found")
    if active and job.outcome is not None:
        raise HTTPException(
            status_code=409,
            detail="A terminal JobOpportunity cannot change its current Offer",
        )
    return job


def _offer_source_checker(
    db: Session,
    user_pk: int,
    source_kind: str,
    source_identity: str,
    source_version: str | None,
) -> bool:
    """Resolve concrete source owners; unsupported future types fail closed."""

    if source_kind == "user_assertion":
        if source_version is not None or not source_identity.isdigit():
            return False
        return (
            db.query(ConversationMessage.id)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .filter(
                ConversationMessage.id == int(source_identity),
                func.lower(ConversationMessage.role) == "user",
                Conversation.user_id == user_pk,
            )
            .scalar()
            is not None
        )
    if source_kind == "artifact":
        row = (
            db.query(ArtifactVersion.version_no)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .filter(
                ArtifactVersion.id == source_identity,
                Artifact.user_id == user_pk,
            )
            .scalar()
        )
        return row is not None and (
            source_version is None or source_version == str(row)
        )
    if source_kind == "file_asset":
        asset = (
            db.query(FileAsset)
            .filter(
                FileAsset.id == source_identity,
                FileAsset.user_id == user_pk,
                FileAsset.deleted_at.is_(None),
            )
            .one_or_none()
        )
        if (
            asset is None
            or asset.upload_status not in READABLE_UPLOAD_STATUSES
            or asset.validation_status != "passed"
        ):
            return False
        checksum = (asset.checksum_sha256 or "").strip().lower()
        exact_version = f"sha256:{checksum}" if checksum else f"file_asset:{asset.id}"
        return source_version is None or source_version == exact_version
    if source_kind == "tool_result":
        if not source_identity.isdigit():
            return False
        row = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.id == int(source_identity),
                AgentToolCall.user_id == user_pk,
                AgentToolCall.status == "completed",
            )
            .one_or_none()
        )
        return bool(
            row is not None
            and row.result_json is not None
            and (
                source_version is None or source_version == str(row.dispatch_generation)
            )
        )
    # No canonical Observation or ProviderReceipt owner exists yet. Do not
    # convert an unverified external string into a source record.
    return False


def _offer_response(row) -> OfferCurrentResponse:
    return OfferCurrentResponse(
        offer=OfferView.model_validate(row),
        current_token=offer_service.current_offer_token(row),
    )


def _raise_offer_http(exc: offer_service.OfferDomainError) -> None:
    if isinstance(
        exc,
        (offer_service.OfferNotFoundError, offer_service.OfferOwnershipError),
    ):
        raise HTTPException(status_code=404, detail="Offer or owner not found") from exc
    if isinstance(exc, offer_service.OfferSourceUnavailableError):
        raise HTTPException(
            status_code=422, detail="Offer source is not verifiable"
        ) from exc
    if isinstance(
        exc,
        (
            offer_service.OfferOperationConflictError,
            offer_service.OfferStaleConfirmationError,
            offer_service.OfferTermsResolutionError,
        ),
    ):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{job_opportunity_id}/offer", response_model=OfferCurrentResponse)
def read_current_offer(
    job_opportunity_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_owned_job(db, current_user.id, job_opportunity_id, active=False)
    try:
        offer = offer_service.get_current_offer(
            db,
            user_pk=current_user.id,
            job_opportunity_id=job_opportunity_id,
            job_owner_checker=_owned_job_checker,
        )
    except offer_service.OfferDomainError as exc:
        _raise_offer_http(exc)
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    return _offer_response(offer)


@router.post("/{job_opportunity_id}/offer", response_model=OfferCurrentResponse)
def record_current_offer(
    job_opportunity_id: str,
    body: OfferRecordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_owned_job(db, current_user.id, job_opportunity_id, active=True)
    try:
        offer = offer_service.record_current_offer(
            db,
            user_pk=current_user.id,
            job_opportunity_id=job_opportunity_id,
            operation_key=body.operation_key,
            terms=body.terms,
            source=body.source,
            job_owner_checker=_owned_job_checker,
            source_checker=_offer_source_checker,
        )
        db.commit()
        return _offer_response(offer)
    except offer_service.OfferTermsConfirmationRequired as exc:
        db.rollback()
        payload = OfferConfirmationRequiredView(
            offer_id=exc.offer_id,
            current_token=exc.current_token,
            diff=exc.diff,
        )
        return JSONResponse(
            status_code=409,
            content={"detail": payload.model_dump(mode="json")},
        )
    except offer_service.OfferDomainError as exc:
        db.rollback()
        _raise_offer_http(exc)


@router.post(
    "/{job_opportunity_id}/offer/confirm-terms",
    response_model=OfferCurrentResponse,
)
def confirm_offer_terms(
    job_opportunity_id: str,
    body: OfferConfirmTermsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_owned_job(db, current_user.id, job_opportunity_id, active=True)
    if (
        body.confirmation_source is not None
        and body.confirmation_source.kind != "user_assertion"
    ):
        raise HTTPException(
            status_code=422,
            detail="The current API requires a persisted user confirmation message",
        )
    try:
        common = {
            "user_pk": current_user.id,
            "offer_id": body.offer_id,
            "job_opportunity_id": job_opportunity_id,
            "operation_key": body.operation_key,
            "expected_current_token": body.expected_current_token,
            "resolution": body.resolution,
            "terms": body.terms,
            "candidate_source": body.candidate_source,
            "job_owner_checker": _owned_job_checker,
            "source_checker": _offer_source_checker,
        }
        if body.ui_confirmation is not None:
            offer = offer_service.confirm_offer_terms_change_from_product_ui(
                db,
                **common,
            )
        else:
            assert body.confirmation_source is not None
            offer = offer_service.confirm_offer_terms_change(
                db,
                confirmation_source=body.confirmation_source,
                **common,
            )
        db.commit()
        return _offer_response(offer)
    except offer_service.OfferDomainError as exc:
        db.rollback()
        _raise_offer_http(exc)


__all__ = ["router"]
