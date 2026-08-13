"""Read models and explicit commands for actions, funnel, and Offer analysis."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.job_opportunity import NextActionView


class NotificationPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    enabled: bool = True
    default_channel: Literal["in_app"] = "in_app"
    timezone: str = Field(min_length=1, max_length=80)
    quiet_start: str | None = Field(
        default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    quiet_end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def quiet_hours_are_paired(self) -> "NotificationPreferenceUpdate":
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("quiet_start and quiet_end must be paired")
        if self.quiet_start is not None and self.quiet_start == self.quiet_end:
            raise ValueError("quiet hours cannot cover the entire day")
        return self


class NotificationPreferenceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    default_channel: Literal["in_app"]
    timezone: str
    quiet_start: str | None
    quiet_end: str | None
    version: int


class ReminderDismiss(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)


class NextActionAgendaItem(BaseModel):
    action: NextActionView
    bucket: Literal["conflict", "today", "upcoming", "unscheduled_planned", "suggested"]
    overdue: bool
    due_soon: bool
    conflict_action_ids: list[str]
    duplicate_action_ids: list[str]


class NextActionAgenda(BaseModel):
    generated_at: datetime
    items: list[NextActionAgendaItem]


class FunnelCoverage(BaseModel):
    sample_count: int
    direction_snapshot_count: int
    submitted_material_count: int
    channel_count: int
    jd_snapshot_count: int
    outcome_count: int


class FunnelStageMetric(BaseModel):
    stage: Literal["applied", "in_process", "offer", "terminal"]
    reached: int
    conversion_from_sample: float
    median_wait_hours: float | None


class FunnelGroup(BaseModel):
    direction_id: str | None
    direction_label: str | None
    submitted_artifact_version_id: str | None
    channel: str | None
    calendar_month: str
    sample_job_ids: list[str]
    stages: list[FunnelStageMetric]
    outcomes: dict[str, int]


class FunnelAnalysis(BaseModel):
    generated_at: datetime
    sample_job_ids: list[str]
    coverage: FunnelCoverage
    groups: list[FunnelGroup]
    missing_source_notes: list[str]
    confounders: list[str]
    interpretation_limit: str


class AssumptionSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: str = Field(min_length=1, max_length=500)
    observed_at: AwareDatetime
    url: str | None = Field(default=None, max_length=4_000)


class ExchangeRateAssumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    rate_to_base: Decimal = Field(gt=0)
    source: AssumptionSource


class TaxAssumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str = Field(min_length=1, max_length=35)
    effective_rate: Decimal = Field(ge=0, le=1)
    jurisdiction: str = Field(min_length=1, max_length=160)
    source: AssumptionSource


class EquityValuationAssumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str = Field(min_length=1, max_length=35)
    annual_value: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    method: str = Field(min_length=1, max_length=500)
    source: AssumptionSource


class AnnualBonusAssumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str = Field(min_length=1, max_length=35)
    annual_value: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    basis: str = Field(min_length=1, max_length=500)
    source: AssumptionSource


class OfferAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_ids: list[str] = Field(min_length=1, max_length=20)
    base_currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    exchange_rates: list[ExchangeRateAssumption] = Field(default_factory=list)
    tax_assumptions: list[TaxAssumption] = Field(default_factory=list)
    equity_assumptions: list[EquityValuationAssumption] = Field(default_factory=list)
    bonus_assumptions: list[AnnualBonusAssumption] = Field(default_factory=list)
    user_constraints: list[str] = Field(default_factory=list, max_length=50)
    save_artifact: bool = False
    operation_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_unique_inputs(self) -> "OfferAnalysisRequest":
        if len(self.offer_ids) != len(set(self.offer_ids)):
            raise ValueError("offer_ids must be unique")
        for name, values in (
            ("tax_assumptions", self.tax_assumptions),
            ("equity_assumptions", self.equity_assumptions),
            ("bonus_assumptions", self.bonus_assumptions),
        ):
            ids = [item.offer_id for item in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} may contain at most one item per Offer")
            unknown = sorted(set(ids) - set(self.offer_ids))
            if unknown:
                raise ValueError(
                    f"{name} references Offer ids outside offer_ids: {unknown}"
                )
        currencies = [item.currency.upper() for item in self.exchange_rates]
        if len(currencies) != len(set(currencies)):
            raise ValueError("exchange_rates may contain at most one item per currency")
        if self.save_artifact and not self.operation_key:
            raise ValueError("operation_key is required when save_artifact is true")
        return self


class OfferAnalysisItem(BaseModel):
    offer_id: str
    job_opportunity_id: str
    company_name: str
    job_title: str
    original_currency: str | None
    annual_base_original: str | None
    annual_base_in_base_currency: str | None
    annual_bonus_in_base_currency: str | None
    annual_equity_in_base_currency: str | None
    estimated_after_tax_cash: str | None
    estimated_total_value: str | None
    missing_information: list[str]
    risks: list[str]
    assumptions: list[str]


class OfferAnalysisResponse(BaseModel):
    generated_at: datetime
    base_currency: str
    items: list[OfferAnalysisItem]
    career_profile_constraints: list[str]
    user_constraints: list[str]
    source_observations: list[AssumptionSource]
    report_markdown: str
    artifact_id: str | None = None


class NegotiationDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=1_000)
    tone: Literal["professional", "warm", "concise"] = "professional"
    constraints: list[str] = Field(default_factory=list, max_length=20)
    save_artifact: bool = False
    operation_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_save_key(self) -> "NegotiationDraftRequest":
        if self.save_artifact and not self.operation_key:
            raise ValueError("operation_key is required when save_artifact is true")
        return self


class NegotiationDraftResponse(BaseModel):
    offer_id: str
    draft_markdown: str
    send_status: Literal["not_sent"] = "not_sent"
    execution_note: str
    artifact_id: str | None = None


__all__ = [
    "AnnualBonusAssumption",
    "AssumptionSource",
    "EquityValuationAssumption",
    "ExchangeRateAssumption",
    "FunnelAnalysis",
    "FunnelCoverage",
    "FunnelGroup",
    "FunnelStageMetric",
    "NegotiationDraftRequest",
    "NegotiationDraftResponse",
    "NextActionAgenda",
    "NextActionAgendaItem",
    "NotificationPreferenceUpdate",
    "NotificationPreferenceView",
    "OfferAnalysisItem",
    "OfferAnalysisRequest",
    "OfferAnalysisResponse",
    "ReminderDismiss",
    "TaxAssumption",
]
