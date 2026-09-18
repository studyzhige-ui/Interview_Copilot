"""Content-free account accounting; deleting a Conversation cannot reset usage.

These are UTC-day logical token/call allowances, not a currency invoice. Only
primary Chat/Agent dispatches currently enter this ledger. Provider cache token
categories must not be counted twice. Reservations with an uncertain outcome
are retained until an explicit, evidenced reconciliation.
"""

from sqlalchemy import (
    CheckConstraint,
    BigInteger,
    ForeignKeyConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
)

from app.db.database import Base
from app.db.types import UTCDateTime
from app.db.types import utc_now


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
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    window_date = Column(Date, primary_key=True)
    call_limit = Column(Integer, nullable=False)
    token_limit = Column(Integer, nullable=False)
    calls_admitted = Column(Integer, nullable=False, default=0, server_default="0")
    tokens_used = Column(BigInteger, nullable=False, default=0, server_default="0")
    tokens_reserved = Column(BigInteger, nullable=False, default=0, server_default="0")
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)


class ModelBudgetReservation(Base):
    __tablename__ = "model_budget_reservations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('reserved','settled','estimated','rejected','unknown')",
            name="ck_model_budget_reservation_status",
        ),
        CheckConstraint("reserved_tokens >= 0", name="ck_model_budget_reserved_tokens"),
        CheckConstraint("observed_tokens >= 0", name="ck_model_budget_observed_tokens"),
        Index("ix_model_budget_owner_day", "user_id", "window_date"),
        ForeignKeyConstraint(
            ["user_id", "window_date"],
            ["model_budget_windows.user_id", "model_budget_windows.window_date"],
            ondelete="CASCADE",
            name="fk_model_budget_reservation_window",
        ),
    )
    # Digest of owner/turn/call, NOT prompt content. No FK to deletable Turn.
    id = Column(String(64), primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    window_date = Column(Date, nullable=False)
    reserved_tokens = Column(BigInteger, nullable=False)
    observed_tokens = Column(BigInteger, nullable=False, default=0, server_default="0")
    status = Column(String(16), nullable=False, default="reserved")
    reconciliation_ref = Column(String(256), nullable=True)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
    settled_at = Column(UTCDateTime, nullable=True)
