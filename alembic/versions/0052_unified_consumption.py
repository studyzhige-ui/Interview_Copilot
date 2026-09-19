"""Expand the existing ledger to every consumption category, preserving balances.

Revision ID: 0052
Revises: 0051
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

WINDOW = (
    ("currency", sa.String(3), False, "USD"),
    ("cost_limit_micros", sa.BigInteger(), True, None),
    ("cost_used_micros", sa.BigInteger(), False, "0"),
    ("cost_reserved_micros", sa.BigInteger(), False, "0"),
    ("units_used_json", postgresql.JSONB(), False, "{}"),
    ("units_reserved_json", postgresql.JSONB(), False, "{}"),
    ("unit_limits_json", postgresql.JSONB(), False, "{}"),
)
RESERVATION = (
    ("revision", sa.Integer(), False, "0"),
    ("invoice_cost_micros", sa.BigInteger(), True, None),
    ("valuation_snapshot_json", postgresql.JSONB(), True, None),
    ("transport_claimed_at", sa.DateTime(timezone=True), True, None),
    ("meter", sa.String(80), False, "primary"),
    ("provider", sa.String(120), True, None),
    ("model", sa.String(255), True, None),
    ("request_fingerprint", sa.String(64), True, None),
    ("price_snapshot_json", postgresql.JSONB(none_as_null=True), True, None),
    ("reserved_units_json", postgresql.JSONB(), False, "{}"),
    ("observed_units_json", postgresql.JSONB(), True, None),
    ("cost_reserved_micros", sa.BigInteger(), False, "0"),
    ("cost_observed_micros", sa.BigInteger(), True, None),
)


def upgrade():
    op.create_table(
        "usage_accounts",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    # Literal operations are inspectable by the migration/ORM contract gate.
    op.add_column(
        "model_budget_windows",
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
    )
    op.add_column(
        "model_budget_windows",
        sa.Column(
            "cost_limit_micros", sa.BigInteger(), nullable=True, server_default=None
        ),
    )
    op.add_column(
        "model_budget_windows",
        sa.Column(
            "cost_used_micros", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "model_budget_windows",
        sa.Column(
            "cost_reserved_micros", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "model_budget_windows",
        sa.Column(
            "units_used_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
    )
    op.add_column(
        "model_budget_windows",
        sa.Column(
            "units_reserved_json",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "model_budget_windows",
        sa.Column(
            "unit_limits_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column(
            "invoice_cost_micros", sa.BigInteger(), nullable=True, server_default=None
        ),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column(
            "valuation_snapshot_json",
            postgresql.JSONB(),
            nullable=True,
            server_default=None,
        ),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column(
            "transport_claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=None,
        ),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column("meter", sa.String(80), nullable=False, server_default="primary"),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column("provider", sa.String(120), nullable=True, server_default=None),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column("model", sa.String(255), nullable=True, server_default=None),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column(
            "request_fingerprint", sa.String(64), nullable=True, server_default=None
        ),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column(
            "price_snapshot_json",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
            server_default=None,
        ),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column(
            "reserved_units_json",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column(
            "observed_units_json",
            postgresql.JSONB(),
            nullable=True,
            server_default=None,
        ),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column(
            "cost_reserved_micros", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column(
            "cost_observed_micros", sa.BigInteger(), nullable=True, server_default=None
        ),
    )
    op.create_check_constraint(
        "ck_usage_window_costs",
        "model_budget_windows",
        "cost_used_micros >= 0 AND cost_reserved_micros >= 0 AND (cost_limit_micros IS NULL OR cost_limit_micros > 0)",
    )
    op.create_check_constraint(
        "ck_usage_receipt_costs",
        "model_budget_reservations",
        "cost_reserved_micros >= 0 AND (cost_observed_micros IS NULL OR cost_observed_micros >= 0) AND (invoice_cost_micros IS NULL OR invoice_cost_micros >= 0)",
    )
    op.add_column(
        "model_budget_reservations",
        sa.Column("provider_request_id", sa.String(255), nullable=True),
    )
    op.create_table(
        "usage_adjustments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("usage_accounts.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "receipt_id",
            sa.String(64),
            sa.ForeignKey("model_budget_reservations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("operator", sa.String(120), nullable=False),
        sa.Column("evidence_ref", sa.String(256), nullable=False),
        sa.Column("before_json", postgresql.JSONB(), nullable=False),
        sa.Column("after_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_usage_adjustment_owner_receipt",
        "usage_adjustments",
        ["user_id", "receipt_id"],
    )
    op.execute(
        "INSERT INTO usage_accounts (user_id) SELECT id FROM users ON CONFLICT DO NOTHING"
    )
    # Old rows recorded one admitted physical request and logical token totals,
    # not disjoint input/output/cache buckets. Backfill only known attempt units;
    # do not invent a token split or vendor price. Keep the original balances.
    op.execute(
        "UPDATE model_budget_reservations SET reserved_units_json = '{\"requests\":1}'::jsonb"
    )
    op.execute(
        "UPDATE model_budget_reservations SET observed_units_json = '{\"requests\":1}'::jsonb WHERE status IN ('settled','estimated','rejected')"
    )
    op.execute("""
        UPDATE model_budget_windows AS w SET
            units_reserved_json = jsonb_build_object('requests', (
                SELECT count(*) FROM model_budget_reservations AS r
                WHERE r.user_id = w.user_id AND r.window_date = w.window_date
                AND r.status IN ('reserved','unknown'))),
            units_used_json = jsonb_build_object('requests', (
                SELECT count(*) FROM model_budget_reservations AS r
                WHERE r.user_id = w.user_id AND r.window_date = w.window_date
                AND r.status IN ('settled','estimated','rejected')))
    """)
    # The accounting subtree references its own owner lock. A new day/receipt
    # must not wait on a User FOR UPDATE held by an unrelated business command.
    inspector = sa.inspect(op.get_bind())
    for table in ("model_budget_windows", "model_budget_reservations"):
        for fk in inspector.get_foreign_keys(table):
            if fk["constrained_columns"] == ["user_id"]:
                op.drop_constraint(fk["name"], table, type_="foreignkey")
        op.create_foreign_key(
            f"fk_{table}_usage_account",
            table,
            "usage_accounts",
            ["user_id"],
            ["user_id"],
            ondelete="CASCADE",
        )


def downgrade():
    # New category receipts and unresolved costs cannot be erased to bypass a
    # quota or retry an uncertain write. Export/reconcile before operator rollback.
    connection = op.get_bind()
    active = connection.scalar(
        sa.text(
            "SELECT count(*) FROM model_budget_reservations WHERE meter <> 'primary' OR provider IS NOT NULL OR provider_request_id IS NOT NULL OR cost_reserved_micros <> 0 OR cost_observed_micros IS NOT NULL"
        )
    )
    if active or connection.scalar(sa.text("SELECT count(*) FROM usage_adjustments")):
        raise RuntimeError("usage_rollback_requires_reconciliation_and_export")
    op.drop_table("usage_adjustments")
    op.drop_column("model_budget_reservations", "provider_request_id")
    for table in ("model_budget_windows", "model_budget_reservations"):
        op.drop_constraint(f"fk_{table}_usage_account", table, type_="foreignkey")
        op.create_foreign_key(
            f"{table}_user_id_fkey",
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.drop_constraint(
        "ck_usage_receipt_costs", "model_budget_reservations", type_="check"
    )
    op.drop_constraint("ck_usage_window_costs", "model_budget_windows", type_="check")
    for table, columns in (
        ("model_budget_reservations", RESERVATION),
        ("model_budget_windows", WINDOW),
    ):
        for name, *_ in reversed(columns):
            op.drop_column(table, name)
    op.drop_table("usage_accounts")
