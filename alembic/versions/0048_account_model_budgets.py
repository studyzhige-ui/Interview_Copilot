"""Content-free account allowances and durable model reservations.

Revision ID: 0048
Revises: 0047
"""

from alembic import op
import sqlalchemy as sa

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_budget_windows",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("window_date", sa.Date(), primary_key=True),
        sa.Column("call_limit", sa.Integer(), nullable=False),
        sa.Column("token_limit", sa.Integer(), nullable=False),
        sa.Column("calls_admitted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "tokens_reserved", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "call_limit > 0 AND token_limit > 0", name="ck_model_budget_limits"
        ),
        sa.CheckConstraint(
            "calls_admitted >= 0 AND tokens_used >= 0 AND tokens_reserved >= 0",
            name="ck_model_budget_counters",
        ),
    )
    op.create_table(
        "model_budget_reservations",
        sa.ForeignKeyConstraint(
            ["user_id", "window_date"],
            ["model_budget_windows.user_id", "model_budget_windows.window_date"],
            ondelete="CASCADE",
            name="fk_model_budget_reservation_window",
        ),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("window_date", sa.Date(), nullable=False),
        sa.Column("reserved_tokens", sa.BigInteger(), nullable=False),
        sa.Column(
            "observed_tokens", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reconciliation_ref", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('reserved','settled','estimated','rejected','unknown')",
            name="ck_model_budget_reservation_status",
        ),
        sa.CheckConstraint(
            "reserved_tokens >= 0", name="ck_model_budget_reserved_tokens"
        ),
        sa.CheckConstraint(
            "observed_tokens >= 0", name="ck_model_budget_observed_tokens"
        ),
    )
    op.create_index(
        "ix_model_budget_owner_day",
        "model_budget_reservations",
        ["user_id", "window_date"],
    )


def downgrade():
    # Deliberate operator downgrade deletes accounting only, never user facts.
    # Export these records first when a deployment needs historical accounting.
    op.drop_table("model_budget_reservations")
    op.drop_table("model_budget_windows")
