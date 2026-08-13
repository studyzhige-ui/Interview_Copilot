"""Focused tests for the single-current-Offer domain boundary."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.offer import Offer
from app.models.user import User
from app.schemas.offer import OfferSourceInput, OfferTermsInput
from app.services.offer_service import (
    OfferOperationConflictError,
    OfferOwnershipError,
    OfferSourceUnavailableError,
    OfferStaleConfirmationError,
    OfferTermsConfirmationRequired,
    OfferTermsResolutionError,
    confirm_offer_terms_change,
    current_offer_token,
    get_current_offer,
    record_current_offer,
)


NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def _user(db, name: str) -> User:
    row = User(username=name, email=f"{name}@example.com", hashed_password="x")
    db.add(row)
    db.flush()
    return row


def _job_id(user: User) -> str:
    return f"jo_{user.id:032d}"


def _job_owner(_db, user_pk: int, job_id: str) -> bool:
    return job_id == f"jo_{user_pk:032d}"


def _source_checker(
    _db,
    user_pk: int,
    kind: str,
    identity: str,
    _version: str | None,
) -> bool:
    return identity.startswith(f"{kind}:{user_pk}:")


def _source(user: User, kind: str = "file_asset", suffix: str = "one"):
    return OfferSourceInput(
        kind=kind,
        identity=f"{kind}:{user.id}:{suffix}",
        version="v1",
        observed_at=NOW,
    )


def _terms(salary: str = "100000", **updates) -> OfferTermsInput:
    values = {
        "position_title": "Backend Engineer",
        "base_salary_amount": salary,
        "currency": "cny",
        "pay_period": "annual",
        "tax_basis": "gross",
        "formality": "written",
        "original_text": f"Annual base salary CNY {salary}, gross.",
    }
    values.update(updates)
    return OfferTermsInput(**values)


def test_one_current_offer_per_job_and_creation_retry_is_idempotent(db_session):
    user = _user(db_session, "alice")
    terms = _terms()
    source = _source(user)
    offer = record_current_offer(
        db_session,
        user_pk=user.id,
        job_opportunity_id=_job_id(user),
        operation_key="offer-create-1",
        terms=terms,
        source=source,
        job_owner_checker=_job_owner,
        source_checker=_source_checker,
    )
    retry = record_current_offer(
        db_session,
        user_pk=user.id,
        job_opportunity_id=_job_id(user),
        operation_key="offer-create-1",
        terms=terms,
        source=source,
        job_owner_checker=_job_owner,
        source_checker=lambda *_args: False,
    )

    assert retry.id == offer.id
    assert db_session.query(Offer).count() == 1
    assert (
        get_current_offer(
            db_session,
            user_pk=user.id,
            job_opportunity_id=_job_id(user),
            job_owner_checker=_job_owner,
        ).id
        == offer.id
    )

    with pytest.raises(OfferOperationConflictError):
        record_current_offer(
            db_session,
            user_pk=user.id,
            job_opportunity_id=_job_id(user),
            operation_key="offer-create-1",
            terms=_terms("110000"),
            source=source,
            job_owner_checker=_job_owner,
            source_checker=_source_checker,
        )


def test_owner_and_actual_source_are_required(db_session):
    alice = _user(db_session, "alice")
    bob = _user(db_session, "bob")

    with pytest.raises(OfferOwnershipError):
        record_current_offer(
            db_session,
            user_pk=bob.id,
            job_opportunity_id=_job_id(alice),
            operation_key="stolen-job",
            terms=_terms(),
            source=_source(bob),
            job_owner_checker=_job_owner,
            source_checker=_source_checker,
        )

    with pytest.raises(OfferSourceUnavailableError):
        record_current_offer(
            db_session,
            user_pk=alice.id,
            job_opportunity_id=_job_id(alice),
            operation_key="fake-source",
            terms=_terms(),
            source=OfferSourceInput(
                kind="file_asset",
                identity="file_asset:someone-else:source",
                version="v1",
                observed_at=NOW,
            ),
            job_owner_checker=_job_owner,
            source_checker=_source_checker,
        )

    offer = record_current_offer(
        db_session,
        user_pk=alice.id,
        job_opportunity_id=_job_id(alice),
        operation_key="valid-source",
        terms=_terms(),
        source=_source(alice),
        job_owner_checker=_job_owner,
        source_checker=_source_checker,
    )
    with pytest.raises(OfferSourceUnavailableError):
        record_current_offer(
            db_session,
            user_pk=alice.id,
            job_opportunity_id=_job_id(alice),
            operation_key="same-terms-fake-source",
            terms=_terms(),
            source=OfferSourceInput(
                kind="file_asset",
                identity="file_asset:someone-else:source",
                version="v1",
                observed_at=NOW,
            ),
            job_owner_checker=_job_owner,
            source_checker=_source_checker,
        )
    assert offer.last_source_identity == _source(alice).identity


def test_differing_source_returns_diff_and_writes_nothing(db_session):
    user = _user(db_session, "alice")
    offer = record_current_offer(
        db_session,
        user_pk=user.id,
        job_opportunity_id=_job_id(user),
        operation_key="create",
        terms=_terms(),
        source=_source(user),
        job_owner_checker=_job_owner,
        source_checker=_source_checker,
    )
    before = dict(offer.terms_json)

    with pytest.raises(OfferTermsConfirmationRequired) as caught:
        record_current_offer(
            db_session,
            user_pk=user.id,
            job_opportunity_id=_job_id(user),
            operation_key="new-source",
            terms=_terms("120000"),
            source=_source(user, suffix="two"),
            job_owner_checker=_job_owner,
            source_checker=_source_checker,
        )

    db_session.refresh(offer)
    assert offer.terms_json == before
    assert caught.value.offer_id == offer.id
    assert "base_salary_amount" in caught.value.diff.changed
    assert caught.value.current_token == current_offer_token(offer)
    assert db_session.query(Offer).count() == 1


def test_confirmed_replace_updates_same_row_and_stale_token_is_rejected(db_session):
    user = _user(db_session, "alice")
    offer = record_current_offer(
        db_session,
        user_pk=user.id,
        job_opportunity_id=_job_id(user),
        operation_key="create",
        terms=_terms(),
        source=_source(user),
        job_owner_checker=_job_owner,
        source_checker=_source_checker,
    )
    token = current_offer_token(offer)
    replacement = _terms("120000")
    changed = confirm_offer_terms_change(
        db_session,
        user_pk=user.id,
        offer_id=offer.id,
        job_opportunity_id=_job_id(user),
        operation_key="confirm-replace",
        expected_current_token=token,
        resolution="replace",
        terms=replacement,
        candidate_source=_source(user, suffix="two"),
        confirmation_source=_source(user, kind="user_assertion", suffix="confirm"),
        job_owner_checker=_job_owner,
        source_checker=_source_checker,
    )

    assert changed.id == offer.id
    assert changed.terms_json["base_salary_amount"] == "120000"
    assert changed.last_confirmation_source_kind == "user_assertion"
    assert db_session.query(Offer).count() == 1

    with pytest.raises(OfferStaleConfirmationError):
        confirm_offer_terms_change(
            db_session,
            user_pk=user.id,
            offer_id=offer.id,
            job_opportunity_id=_job_id(user),
            operation_key="stale-confirmation",
            expected_current_token=token,
            resolution="replace",
            terms=_terms("130000"),
            candidate_source=_source(user, suffix="three"),
            confirmation_source=_source(
                user,
                kind="user_assertion",
                suffix="confirm-again",
            ),
            job_owner_checker=_job_owner,
            source_checker=_source_checker,
        )


def test_supplement_only_adds_terms_and_cannot_overwrite(db_session):
    user = _user(db_session, "alice")
    offer = record_current_offer(
        db_session,
        user_pk=user.id,
        job_opportunity_id=_job_id(user),
        operation_key="create",
        terms=_terms(),
        source=_source(user),
        job_owner_checker=_job_owner,
        source_checker=_source_checker,
    )
    token = current_offer_token(offer)
    supplement = _terms(
        benefits=["Private medical insurance"],
        formality="verbal_pending_written",
        original_text="The recruiter verbally mentioned private medical insurance.",
    )
    changed = confirm_offer_terms_change(
        db_session,
        user_pk=user.id,
        offer_id=offer.id,
        job_opportunity_id=_job_id(user),
        operation_key="supplement-benefit",
        expected_current_token=token,
        resolution="supplement",
        terms=supplement,
        candidate_source=_source(user, suffix="benefits"),
        confirmation_source=_source(user, kind="user_assertion", suffix="confirm"),
        job_owner_checker=_job_owner,
        source_checker=_source_checker,
    )
    assert changed.terms_json["benefits"] == ["Private medical insurance"]
    assert changed.terms_json["base_salary_amount"] == "100000"
    assert len(changed.source_excerpts_json) == 2
    assert {
        excerpt["formality"] for excerpt in changed.source_excerpts_json.values()
    } == {"written", "verbal_pending_written"}

    with pytest.raises(OfferTermsResolutionError):
        confirm_offer_terms_change(
            db_session,
            user_pk=user.id,
            offer_id=offer.id,
            job_opportunity_id=_job_id(user),
            operation_key="bad-supplement",
            expected_current_token=current_offer_token(changed),
            resolution="supplement",
            terms=_terms("130000", benefits=["Private medical insurance"]),
            candidate_source=_source(user, suffix="conflicting-salary"),
            confirmation_source=_source(
                user,
                kind="user_assertion",
                suffix="confirm-conflict",
            ),
            job_owner_checker=_job_owner,
            source_checker=_source_checker,
        )


def test_offer_terms_reject_analysis_fields_and_incomplete_salary_shape():
    with pytest.raises(ValidationError):
        OfferTermsInput(
            formality="written",
            original_text="Offer text",
            annualized_value="not an Offer fact",
        )
    with pytest.raises(ValidationError):
        OfferTermsInput(
            base_salary_amount="100000",
            formality="written",
            original_text="Offer text",
        )


def test_offer_has_no_accept_decline_or_process_outcome_state(db_session):
    user = _user(db_session, "alice")
    offer = record_current_offer(
        db_session,
        user_pk=user.id,
        job_opportunity_id=_job_id(user),
        operation_key="create",
        terms=_terms(),
        source=_source(user),
        job_owner_checker=_job_owner,
        source_checker=_source_checker,
    )

    columns = set(Offer.__table__.columns.keys())
    assert not columns.intersection(
        {"status", "outcome", "accepted_at", "declined_at", "decision"}
    )
    assert next(iter(offer.source_excerpts_json.values()))["formality"] == "written"
