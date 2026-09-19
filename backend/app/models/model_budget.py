"""Content-free account accounting; deleting a Conversation cannot reset usage.

The historical table names remain stable during expansion. All metered work
shares this ledger; currency amounts are rated estimates, not vendor invoices. Provider cache token
categories must not be counted twice. Reservations with an uncertain outcome
are retained until an explicit, evidenced reconciliation.
"""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    event,
    BigInteger,
    ForeignKeyConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
)

from sqlalchemy.dialects.postgresql import JSONB

from app.db.database import Base
from app.db.types import UTCDateTime, JSONValue
from app.db.types import utc_now


class UsageAccount(Base):
    """An account-only lock, independent of long-running business transactions."""

    __tablename__ = "usage_accounts"
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class ModelBudgetWindow(Base):
    __tablename__ = "model_budget_windows"
    __table_args__ = (
        CheckConstraint(
            "call_limit > 0 AND token_limit > 0", name="ck_model_budget_limits"
        ),
        CheckConstraint(
            "calls_admitted >= 0 AND tokens_used >= 0 AND tokens_reserved >= 0",
            name="ck_model_budget_counters",
        ),
        CheckConstraint(
            "cost_used_micros >= 0 AND cost_reserved_micros >= 0 AND (cost_limit_micros IS NULL OR cost_limit_micros > 0)",
            name="ck_usage_window_costs",
        ),
    )
    user_id = Column(
        Integer,
        ForeignKey("usage_accounts.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    window_date = Column(Date, primary_key=True)
    call_limit = Column(Integer, nullable=False)
    token_limit = Column(Integer, nullable=False)
    calls_admitted = Column(Integer, nullable=False, default=0, server_default="0")
    tokens_used = Column(BigInteger, nullable=False, default=0, server_default="0")
    tokens_reserved = Column(BigInteger, nullable=False, default=0, server_default="0")
    currency = Column(String(3), nullable=False, default="USD", server_default="USD")
    cost_limit_micros = Column(BigInteger, nullable=True)
    cost_used_micros = Column(BigInteger, nullable=False, default=0, server_default="0")
    cost_reserved_micros = Column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    units_used_json = Column(
        JSONValue, nullable=False, default=dict, server_default="{}"
    )
    units_reserved_json = Column(
        JSONValue, nullable=False, default=dict, server_default="{}"
    )
    unit_limits_json = Column(
        JSONValue, nullable=False, default=dict, server_default="{}"
    )
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)


class ModelBudgetReservation(Base):
    __tablename__ = "model_budget_reservations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('reserved','settled','estimated','rejected','unknown')",
            name="ck_model_budget_reservation_status",
        ),
        CheckConstraint("reserved_tokens >= 0", name="ck_model_budget_reserved_tokens"),
        CheckConstraint(
            "cost_reserved_micros >= 0 AND (cost_observed_micros IS NULL OR cost_observed_micros >= 0) AND (invoice_cost_micros IS NULL OR invoice_cost_micros >= 0)",
            name="ck_usage_receipt_costs",
        ),
        CheckConstraint("observed_tokens >= 0", name="ck_model_budget_observed_tokens"),
        Index("ix_model_budget_owner_day", "user_id", "window_date"),
        ForeignKeyConstraint(
            ["user_id", "window_date"],
            ["model_budget_windows.user_id", "model_budget_windows.window_date"],
            ondelete="CASCADE",
            name="fk_model_budget_reservation_window",
        ),
    )
    meter = Column(
        String(80), nullable=False, default="primary", server_default="primary"
    )
    provider = Column(String(120), nullable=True)
    model = Column(String(255), nullable=True)
    provider_request_id = Column(String(255), nullable=True)
    request_fingerprint = Column(String(64), nullable=True)
    price_snapshot_json = Column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        nullable=True,
    )
    reserved_units_json = Column(
        JSONValue, nullable=False, default=dict, server_default="{}"
    )
    observed_units_json = Column(JSONValue, nullable=True)
    cost_reserved_micros = Column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    cost_observed_micros = Column(BigInteger, nullable=True)
    # Digest of owner/turn/call, NOT prompt content. No FK to deletable Turn.
    id = Column(String(64), primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("usage_accounts.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    window_date = Column(Date, nullable=False)
    reserved_tokens = Column(BigInteger, nullable=False)
    observed_tokens = Column(BigInteger, nullable=False, default=0, server_default="0")
    status = Column(String(16), nullable=False, default="reserved")
    reconciliation_ref = Column(String(256), nullable=True)
    revision = Column(Integer, nullable=False, default=0, server_default="0")
    invoice_cost_micros = Column(BigInteger, nullable=True)
    valuation_snapshot_json = Column(JSONValue, nullable=True)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
    transport_claimed_at = Column(UTCDateTime, nullable=True)
    settled_at = Column(UTCDateTime, nullable=True)


class UsageAdjustment(Base):
    """Append-only operator evidence; never a model-callable refund action."""

    __tablename__ = "usage_adjustments"
    __table_args__ = (
        Index("ix_usage_adjustment_owner_receipt", "user_id", "receipt_id"),
    )
    id = Column(String(64), primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("usage_accounts.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    receipt_id = Column(
        String(64),
        ForeignKey("model_budget_reservations.id", ondelete="CASCADE"),
        nullable=False,
    )
    payload_fingerprint = Column(String(64), nullable=False)
    operator = Column(String(120), nullable=False)
    evidence_ref = Column(String(256), nullable=False)
    before_json = Column(JSONValue, nullable=False)
    after_json = Column(JSONValue, nullable=False)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)


@event.listens_for(UsageAdjustment, "before_update")
@event.listens_for(UsageAdjustment, "before_delete")
def _immutable_usage_adjustment(*_args):
    raise ValueError("usage_adjustment_is_append_only")
