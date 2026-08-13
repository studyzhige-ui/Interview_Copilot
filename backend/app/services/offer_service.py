"""Application-service boundary for the single current Offer.

Incoming terms never silently overwrite an existing current Offer. A caller
first records a verified source; differences yield a typed confirmation
request and no write. After the user or a conclusive formal source decides
whether the candidate supplements or replaces current terms, the caller uses
the returned current token to update the same row under a lock.

There is intentionally no accept/decline function here. Those decisions are
``offer_accepted`` / ``offer_declined`` ProcessEvents owned by the career
process Application Service.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import TypeAlias

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.offer import Offer
from app.schemas.offer import OfferSourceInput, OfferTermsDiff, OfferTermsInput

JobOwnerChecker: TypeAlias = Callable[[Session, int, str], bool]
OfferSourceChecker: TypeAlias = Callable[[Session, int, str, str, str | None], bool]


class OfferDomainError(ValueError):
    pass


class OfferNotFoundError(OfferDomainError):
    pass


class OfferOwnershipError(OfferDomainError):
    pass


class OfferSourceUnavailableError(OfferDomainError):
    pass


class OfferOperationConflictError(OfferDomainError):
    pass


class OfferStaleConfirmationError(OfferDomainError):
    pass


class OfferTermsResolutionError(OfferDomainError):
    pass


class OfferTermsConfirmationRequired(OfferDomainError):
    """Candidate terms differ; persist this payload in the existing Interaction."""

    def __init__(
        self,
        *,
        offer_id: str,
        current_token: str,
        diff: OfferTermsDiff,
    ) -> None:
        self.offer_id = offer_id
        self.current_token = current_token
        self.diff = diff
        super().__init__("Offer terms differ; supplement/replace confirmation required")


def record_current_offer(
    db: Session,
    *,
    user_pk: int,
    job_opportunity_id: str,
    operation_key: str,
    terms: OfferTermsInput,
    source: OfferSourceInput,
    job_owner_checker: JobOwnerChecker,
    source_checker: OfferSourceChecker,
) -> Offer:
    """Create the unique Offer or return a confirmation-required difference.

    Exact content repeats are reads, not updates. Any differing current terms
    produce a diff and leave the Offer untouched.
    """

    job_id = _identity(job_opportunity_id, "job_opportunity_id", 35)
    key = _identity(operation_key, "operation_key", 128)
    _require_job_owner(db, user_pk, job_id, job_owner_checker)
    candidate = _terms_payload(terms)
    source_snapshot = _source_snapshot(source)
    source_excerpt = _source_excerpt(source_snapshot, terms)
    operation_fingerprint = _fingerprint(
        {
            "kind": "create_or_observe",
            "job_opportunity_id": job_id,
            "terms": candidate,
            "source_excerpt": source_excerpt,
        }
    )
    offer = _current_offer_locked(db, user_pk, job_id)
    if offer is not None and offer.creation_operation_key == key:
        if offer.creation_operation_fingerprint == operation_fingerprint:
            return offer
        raise OfferOperationConflictError(key)
    if offer is not None and offer.last_operation_key == key:
        if offer.last_operation_fingerprint == operation_fingerprint:
            return offer
        raise OfferOperationConflictError(key)

    _require_source(db, user_pk, source, source_checker)
    if offer is not None:
        if dict(offer.terms_json or {}) == candidate:
            excerpts = dict(offer.source_excerpts_json or {})
            excerpt_key = _source_key(source_snapshot)
            if excerpts.get(excerpt_key) != source_excerpt:
                excerpts[excerpt_key] = source_excerpt
                offer.source_excerpts_json = excerpts
                offer.last_operation_key = key
                offer.last_operation_fingerprint = operation_fingerprint
                offer.last_source_kind = source.kind
                offer.last_source_identity = source.identity
                offer.last_source_version = source.version
                offer.last_source_observed_at = source.observed_at
                offer.updated_at = utc_now()
                db.add(offer)
                db.flush()
            return offer
        raise OfferTermsConfirmationRequired(
            offer_id=offer.id,
            current_token=_current_token(offer),
            diff=_diff(dict(offer.terms_json or {}), candidate),
        )

    row = Offer(
        user_id=user_pk,
        job_opportunity_id=job_id,
        terms_json=candidate,
        term_sources_json={key: source_snapshot for key in candidate},
        source_excerpts_json={_source_key(source_snapshot): source_excerpt},
        creation_operation_key=key,
        creation_operation_fingerprint=operation_fingerprint,
        last_operation_key=key,
        last_operation_fingerprint=operation_fingerprint,
        last_source_kind=source.kind,
        last_source_identity=source.identity,
        last_source_version=source.version,
        last_source_observed_at=source.observed_at,
    )
    db.add(row)
    db.flush()
    return row


def confirm_offer_terms_change(
    db: Session,
    *,
    user_pk: int,
    offer_id: str,
    job_opportunity_id: str,
    operation_key: str,
    expected_current_token: str,
    resolution: str,
    terms: OfferTermsInput,
    candidate_source: OfferSourceInput,
    confirmation_source: OfferSourceInput,
    job_owner_checker: JobOwnerChecker,
    source_checker: OfferSourceChecker,
) -> Offer:
    """CAS-apply an explicitly resolved supplement or replacement."""

    confirmation_snapshot = _source_snapshot(confirmation_source)
    return _confirm_offer_terms_change(
        db,
        user_pk=user_pk,
        offer_id=offer_id,
        job_opportunity_id=job_opportunity_id,
        operation_key=operation_key,
        expected_current_token=expected_current_token,
        resolution=resolution,
        terms=terms,
        candidate_source=candidate_source,
        confirmation_snapshot=confirmation_snapshot,
        confirmation_source_kind=confirmation_source.kind,
        confirmation_source_identity=confirmation_source.identity,
        confirmation_source_version=confirmation_source.version,
        confirmation_observed_at=confirmation_source.observed_at,
        confirmation_source_to_validate=confirmation_source,
        job_owner_checker=job_owner_checker,
        source_checker=source_checker,
    )


def confirm_offer_terms_change_from_product_ui(
    db: Session,
    *,
    user_pk: int,
    offer_id: str,
    job_opportunity_id: str,
    operation_key: str,
    expected_current_token: str,
    resolution: str,
    terms: OfferTermsInput,
    candidate_source: OfferSourceInput,
    job_owner_checker: JobOwnerChecker,
    source_checker: OfferSourceChecker,
) -> Offer:
    """Apply the signed-in user's explicit first-party Offer-page decision."""

    normalized_key = _identity(operation_key, "operation_key", 128)
    confirmation_identity = f"product_ui:{normalized_key}"
    return _confirm_offer_terms_change(
        db,
        user_pk=user_pk,
        offer_id=offer_id,
        job_opportunity_id=job_opportunity_id,
        operation_key=normalized_key,
        expected_current_token=expected_current_token,
        resolution=resolution,
        terms=terms,
        candidate_source=candidate_source,
        confirmation_snapshot={
            "kind": "product_ui",
            "identity": confirmation_identity,
        },
        # A typed first-party command is the user's own assertion. Its durable
        # identity is the idempotent Offer command, not a fake chat message.
        confirmation_source_kind="user_assertion",
        confirmation_source_identity=confirmation_identity,
        confirmation_source_version=expected_current_token,
        confirmation_observed_at=None,
        confirmation_source_to_validate=None,
        job_owner_checker=job_owner_checker,
        source_checker=source_checker,
    )


def _confirm_offer_terms_change(
    db: Session,
    *,
    user_pk: int,
    offer_id: str,
    job_opportunity_id: str,
    operation_key: str,
    expected_current_token: str,
    resolution: str,
    terms: OfferTermsInput,
    candidate_source: OfferSourceInput,
    confirmation_snapshot: dict[str, object],
    confirmation_source_kind: str,
    confirmation_source_identity: str,
    confirmation_source_version: str | None,
    confirmation_observed_at: datetime | None,
    confirmation_source_to_validate: OfferSourceInput | None,
    job_owner_checker: JobOwnerChecker,
    source_checker: OfferSourceChecker,
) -> Offer:
    """Shared locked implementation for message and first-party UI decisions."""

    normalized_offer_id = _identity(offer_id, "offer_id", 35)
    job_id = _identity(job_opportunity_id, "job_opportunity_id", 35)
    key = _identity(operation_key, "operation_key", 128)
    if resolution not in {"supplement", "replace"}:
        raise OfferTermsResolutionError(resolution)
    _require_job_owner(db, user_pk, job_id, job_owner_checker)
    candidate = _terms_payload(terms)
    candidate_source_snapshot = _source_snapshot(candidate_source)
    candidate_source_excerpt = _source_excerpt(candidate_source_snapshot, terms)
    operation_fingerprint = _fingerprint(
        {
            "kind": "confirmed_change",
            "offer_id": normalized_offer_id,
            "job_opportunity_id": job_id,
            "expected_current_token": expected_current_token,
            "resolution": resolution,
            "terms": candidate,
            "candidate_source_excerpt": candidate_source_excerpt,
            "confirmation_source": confirmation_snapshot,
        }
    )
    offer = (
        db.query(Offer)
        .filter(
            Offer.id == normalized_offer_id,
            Offer.user_id == user_pk,
            Offer.job_opportunity_id == job_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if offer is None:
        raise OfferNotFoundError(normalized_offer_id)
    if offer.last_operation_key == key:
        if offer.last_operation_fingerprint == operation_fingerprint:
            return offer
        raise OfferOperationConflictError(key)
    if _current_token(offer) != expected_current_token:
        raise OfferStaleConfirmationError(normalized_offer_id)

    _require_source(db, user_pk, candidate_source, source_checker)
    if confirmation_source_to_validate is not None:
        _require_source(db, user_pk, confirmation_source_to_validate, source_checker)
    current = dict(offer.terms_json or {})
    current_sources = dict(offer.term_sources_json or {})
    if resolution == "replace":
        resolved = candidate
        resolved_sources = {
            term_key: candidate_source_snapshot for term_key in candidate
        }
    else:
        resolved, added_keys = _supplement(current, candidate)
        resolved_sources = current_sources
        for term_key in added_keys:
            resolved_sources[term_key] = candidate_source_snapshot

    offer.terms_json = resolved
    offer.term_sources_json = resolved_sources
    source_excerpts = dict(offer.source_excerpts_json or {})
    source_excerpts[_source_key(candidate_source_snapshot)] = candidate_source_excerpt
    offer.source_excerpts_json = source_excerpts
    offer.last_operation_key = key
    offer.last_operation_fingerprint = operation_fingerprint
    offer.last_source_kind = candidate_source.kind
    offer.last_source_identity = candidate_source.identity
    offer.last_source_version = candidate_source.version
    offer.last_source_observed_at = candidate_source.observed_at
    offer.last_confirmation_source_kind = confirmation_source_kind
    offer.last_confirmation_source_identity = confirmation_source_identity
    offer.last_confirmation_source_version = confirmation_source_version
    offer.last_confirmation_observed_at = confirmation_observed_at or utc_now()
    offer.updated_at = utc_now()
    db.add(offer)
    db.flush()
    return offer


def get_current_offer(
    db: Session,
    *,
    user_pk: int,
    job_opportunity_id: str,
    job_owner_checker: JobOwnerChecker,
) -> Offer | None:
    job_id = _identity(job_opportunity_id, "job_opportunity_id", 35)
    _require_job_owner(db, user_pk, job_id, job_owner_checker)
    return (
        db.query(Offer)
        .filter(
            Offer.user_id == user_pk,
            Offer.job_opportunity_id == job_id,
        )
        .one_or_none()
    )


def current_offer_token(offer: Offer) -> str:
    """Public opaque CAS token for a confirmation Interaction payload."""

    return _current_token(offer)


def _current_offer_locked(
    db: Session,
    user_pk: int,
    job_opportunity_id: str,
) -> Offer | None:
    return (
        db.query(Offer)
        .filter(
            Offer.user_id == user_pk,
            Offer.job_opportunity_id == job_opportunity_id,
        )
        .with_for_update()
        .one_or_none()
    )


def _terms_payload(terms: OfferTermsInput) -> dict[str, object]:
    payload = terms.model_dump(mode="json", exclude_none=True)
    # These describe the actual source, not one synthetic current term. The
    # source excerpt map preserves every source's wording and formality.
    payload.pop("original_text")
    payload.pop("formality")
    return payload


def _source_snapshot(source: OfferSourceInput) -> dict[str, object]:
    return source.model_dump(mode="json", exclude_none=True)


def _source_excerpt(
    source_snapshot: dict[str, object],
    terms: OfferTermsInput,
) -> dict[str, object]:
    return {
        "source": source_snapshot,
        "formality": terms.formality,
        "original_text": terms.original_text,
    }


def _source_key(source_snapshot: dict[str, object]) -> str:
    return _fingerprint(source_snapshot)


def _diff(current: dict[str, object], candidate: dict[str, object]) -> OfferTermsDiff:
    current_keys = set(current)
    candidate_keys = set(candidate)
    return OfferTermsDiff(
        added={key: candidate[key] for key in sorted(candidate_keys - current_keys)},
        changed={
            key: {"current": current[key], "proposed": candidate[key]}
            for key in sorted(current_keys & candidate_keys)
            if current[key] != candidate[key]
        },
        removed={key: current[key] for key in sorted(current_keys - candidate_keys)},
    )


def _supplement(
    current: dict[str, object],
    candidate: dict[str, object],
) -> tuple[dict[str, object], set[str]]:
    resolved = dict(current)
    added: set[str] = set()
    for key, value in candidate.items():
        if key not in current:
            resolved[key] = value
            added.add(key)
        elif current[key] != value:
            raise OfferTermsResolutionError(
                f"supplement cannot overwrite current term: {key}"
            )
    return resolved, added


def _current_token(offer: Offer) -> str:
    return _fingerprint(
        {
            "offer_id": offer.id,
            "terms": dict(offer.terms_json or {}),
            "term_sources": dict(offer.term_sources_json or {}),
            "source_excerpts": dict(offer.source_excerpts_json or {}),
        }
    )


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_job_owner(
    db: Session,
    user_pk: int,
    job_opportunity_id: str,
    checker: JobOwnerChecker,
) -> None:
    if not checker(db, user_pk, job_opportunity_id):
        raise OfferOwnershipError(job_opportunity_id)


def _require_source(
    db: Session,
    user_pk: int,
    source: OfferSourceInput,
    checker: OfferSourceChecker,
) -> None:
    if not checker(
        db,
        user_pk,
        source.kind,
        source.identity,
        source.version,
    ):
        raise OfferSourceUnavailableError(source.identity)


def _identity(value: str, field: str, max_length: int) -> str:
    normalized = (value or "").strip()
    if not normalized or len(normalized) > max_length:
        raise OfferDomainError(field)
    return normalized


__all__ = [
    "OfferDomainError",
    "OfferNotFoundError",
    "OfferOperationConflictError",
    "OfferOwnershipError",
    "OfferSourceUnavailableError",
    "OfferStaleConfirmationError",
    "OfferTermsConfirmationRequired",
    "OfferTermsResolutionError",
    "confirm_offer_terms_change",
    "confirm_offer_terms_change_from_product_ui",
    "current_offer_token",
    "get_current_offer",
    "record_current_offer",
]
