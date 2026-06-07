"""MODEL-CONFIG: structure user model config under stable users.id.

Clean rebuild (pre-launch, no data preserved):
  * drop ``user_api_keys``            -> ``user_model_credentials``
  * drop ``user_provider_settings``   -> ``user_model_provider_settings``
  * drop ``users.model_selection_json`` -> ``user_model_selections`` (one row
    per role)

All three new tables key on the stable ``users.id`` (FK, ON DELETE CASCADE)
instead of the username. The system model catalog stays in code / Redis — no
``model_providers`` / ``model_catalog_entries`` tables.

Revision ID: 0017_model_config_tables
Revises: 0016_auth_token_version
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0017_model_config_tables"
down_revision: Union[str, None] = "0016_auth_token_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _has_column(insp, table: str, col: str) -> bool:
    return _has_table(insp, table) and col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    # ── New tables (idempotent: skip if a create_all-initialised dev DB
    # already has them) ──────────────────────────────────────────────────
    if not _has_table(insp, "user_model_credentials"):
        op.create_table(
            "user_model_credentials",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("key_ciphertext", sa.Text(), nullable=False),
            sa.Column("key_masked", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "user_id", "provider", name="uq_user_model_credentials_user_provider",
            ),
        )

    if not _has_table(insp, "user_model_provider_settings"):
        op.create_table(
            "user_model_provider_settings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("api_base_override", sa.String(), nullable=True),
            sa.Column("organization_id", sa.String(), nullable=True),
            sa.Column("extra_headers_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "user_id", "provider", name="uq_user_model_provider_settings",
            ),
        )

    if not _has_table(insp, "user_model_selections"):
        op.create_table(
            "user_model_selections",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "user_id", "role", name="uq_user_model_selections_user_role",
            ),
        )

    # ── Drop the superseded structures ───────────────────────────────────
    if _has_table(insp, "user_api_keys"):
        op.drop_table("user_api_keys")
    if _has_table(insp, "user_provider_settings"):
        op.drop_table("user_provider_settings")
    if _has_column(insp, "users", "model_selection_json"):
        op.drop_column("users", "model_selection_json")


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not _has_column(insp, "users", "model_selection_json"):
        op.add_column("users", sa.Column("model_selection_json", sa.Text(), nullable=True))

    if not _has_table(insp, "user_provider_settings"):
        op.create_table(
            "user_provider_settings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False, index=True),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("api_base_override", sa.String(), nullable=True),
            sa.Column("organization_id", sa.String(), nullable=True),
            sa.Column("extra_headers_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "provider", name="uq_user_provider_settings"),
        )

    if not _has_table(insp, "user_api_keys"):
        op.create_table(
            "user_api_keys",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.String(), nullable=False, index=True),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("key_ciphertext", sa.Text(), nullable=False),
            sa.Column("key_masked", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "provider", name="uq_user_api_keys_user_provider"),
        )

    for tbl in ("user_model_selections", "user_model_provider_settings", "user_model_credentials"):
        if _has_table(insp, tbl):
            op.drop_table(tbl)
