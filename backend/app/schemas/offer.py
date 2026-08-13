"""Typed current-Offer terms, sources, differences, and read models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


OfferSourceKind = Literal[
    "user_assertion",
    "observation",
    "tool_result",
    "provider_receipt",
    "artifact",
    "file_asset",
]
OfferTermsResolution = Literal["supplement", "replace"]


class OfferSourceInput(BaseModel):
    """Direct identity of an actual assertion, record, result, or asset."""

    model_config = ConfigDict(extra="forbid")

    kind: OfferSourceKind
    identity: str = Field(min_length=1, max_length=256)
    version: str | None = Field(default=None, max_length=128)
    observed_at: AwareDatetime


class OfferTermsInput(BaseModel):
    """Small common Offer structure plus explicitly named additional terms.

    Estimates such as annualized value, FX conversion, tax estimates, scores,
    risk, or recommendations are deliberately absent and rejected as extras.
    """

    model_config = ConfigDict(extra="forbid")

    position_title: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    employment_type: str | None = Field(default=None, max_length=100)

    base_salary_amount: Decimal | None = Field(default=None, gt=0, max_digits=20)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    pay_period: Literal["hourly", "monthly", "annual", "total"] | None = None
    tax_basis: Literal["gross", "net", "unspecified"] | None = None

    bonus_text: str | None = Field(default=None, max_length=4_000)
    equity_text: str | None = Field(default=None, max_length=4_000)
    benefits: list[str] | None = Field(default=None, max_length=100)
    probation_text: str | None = Field(default=None, max_length=2_000)
    start_date: date | None = None
    response_deadline: AwareDatetime | None = None
    # Optional exact local wording/input and its source timezone.  The aware
    # datetime remains the comparable fact; these fields preserve provenance
    # for a deadline-derived NextAction.
    response_deadline_text: str | None = Field(default=None, max_length=300)
    response_deadline_timezone: str | None = Field(default=None, max_length=80)
    additional_terms: dict[str, str] | None = Field(default=None, max_length=100)

    formality: Literal["written", "verbal_confirmed", "verbal_pending_written"]
    # Exact source wording. Structured extraction never replaces this text.
    original_text: str = Field(min_length=1, max_length=100_000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def validate_salary_and_extensible_terms(self):
        salary_shape = (
            self.base_salary_amount,
            self.currency,
            self.pay_period,
            self.tax_basis,
        )
        if any(value is not None for value in salary_shape) and not all(
            value is not None for value in salary_shape
        ):
            raise ValueError(
                "base salary requires amount, currency, pay_period and tax_basis"
            )
        if self.benefits is not None and any(
            not item.strip() for item in self.benefits
        ):
            raise ValueError("benefits cannot contain empty entries")
        if (self.response_deadline_text is None) != (
            self.response_deadline_timezone is None
        ):
            raise ValueError(
                "response_deadline_text and response_deadline_timezone must be paired"
            )
        if self.response_deadline is None and self.response_deadline_text is not None:
            raise ValueError("response deadline provenance requires response_deadline")
        if self.additional_terms is not None:
            if any(
                not key.strip()
                or len(key) > 120
                or not value.strip()
                or len(value) > 4_000
                for key, value in self.additional_terms.items()
            ):
                raise ValueError(
                    "additional terms require bounded non-empty keys/values"
                )
        return self


class OfferTermsDiff(BaseModel):
    added: dict[str, object] = Field(default_factory=dict)
    changed: dict[str, dict[str, object]] = Field(default_factory=dict)
    removed: dict[str, object] = Field(default_factory=dict)


class OfferView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    job_opportunity_id: str
    terms_json: dict[str, object]
    term_sources_json: dict[str, dict[str, object]]
    source_excerpts_json: dict[str, dict[str, object]]
    last_source_kind: OfferSourceKind
    last_source_identity: str
    last_source_version: str | None
    last_source_observed_at: datetime
    created_at: datetime
    updated_at: datetime


class OfferRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(min_length=1, max_length=128)
    terms: OfferTermsInput
    source: OfferSourceInput


class OfferProductUiConfirmationInput(BaseModel):
    """Explicit decision made by the signed-in user in a first-party UI."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["product_ui"] = "product_ui"


class OfferConfirmTermsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str = Field(min_length=1, max_length=35)
    operation_key: str = Field(min_length=1, max_length=128)
    expected_current_token: str = Field(min_length=64, max_length=64)
    resolution: OfferTermsResolution
    terms: OfferTermsInput
    candidate_source: OfferSourceInput
    # A Conversation path can point at its real user message. A first-party
    # Offer page instead records the signed-in user's typed UI command on the
    # Offer aggregate, without fabricating a ConversationMessage.
    confirmation_source: OfferSourceInput | None = None
    ui_confirmation: OfferProductUiConfirmationInput | None = None

    @model_validator(mode="after")
    def requires_exactly_one_confirmation(self):
        if (self.confirmation_source is None) == (self.ui_confirmation is None):
            raise ValueError(
                "provide exactly one of confirmation_source or ui_confirmation"
            )
        return self


class OfferCurrentResponse(BaseModel):
    offer: OfferView
    current_token: str = Field(min_length=64, max_length=64)


class OfferListItem(BaseModel):
    offer: OfferView
    current_token: str = Field(min_length=64, max_length=64)
    company_name: str
    job_title: str


class OfferConfirmationRequiredView(BaseModel):
    status: Literal["confirmation_required"] = "confirmation_required"
    offer_id: str
    current_token: str = Field(min_length=64, max_length=64)
    diff: OfferTermsDiff


__all__ = [
    "OfferConfirmationRequiredView",
    "OfferConfirmTermsRequest",
    "OfferCurrentResponse",
    "OfferListItem",
    "OfferProductUiConfirmationInput",
    "OfferRecordRequest",
    "OfferSourceInput",
    "OfferSourceKind",
    "OfferTermsDiff",
    "OfferTermsInput",
    "OfferTermsResolution",
    "OfferView",
]
