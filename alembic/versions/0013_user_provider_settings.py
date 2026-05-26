"""Add ``user_provider_settings`` table (P6-L scaffolding for P6-M).

One row per (user, provider) when the user has overridden anything
about how the system talks to that vendor:

  - ``enabled``         — hide/show the vendor's card on the Models page
  - ``api_base_override`` — subscription gateway / self-hosted endpoint
  - ``organization_id`` — OpenAI org / Azure deployment / Aliyun project
  - ``extra_headers_json`` — escape-hatch for vendor-required custom headers
                             (PATCH-only in v1, no UI surface)

Missing row = system uses ``ProviderDefaults`` from
``app/services/model_sources/providers.py``.

Revision ID: 0013_user_provider_settings
Revises: 0012_user_model_selection
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0013_user_provider_settings"
down_revision: Union[str, None] = "0012_user_model_selection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent — dev DBs that picked the table up via
    # ``Base.metadata.create_all()`` after the SQLA model landed
    # should not error here.
    bind = op.get_bind()
    insp = inspect(bind)
    existing_tables = set(insp.get_table_names())
    if "user_provider_settings" in existing_tables:
        return

    op.create_table(
        "user_provider_settings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.username", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("api_base_override", sa.String(), nullable=True),
        sa.Column("organization_id", sa.String(), nullable=True),
        sa.Column("extra_headers_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_provider_settings"),
    )
    op.create_index(
        "ix_user_provider_settings_user_id",
        "user_provider_settings",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_provider_settings_user_id", table_name="user_provider_settings")
    op.drop_table("user_provider_settings")
