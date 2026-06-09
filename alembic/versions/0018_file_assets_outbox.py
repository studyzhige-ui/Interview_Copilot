"""UPLOAD-FILE-ASSETS: add ``file_assets`` + ``outbox_jobs``.

Adds the unified raw-file-asset layer (presigned upload + confirm + validation
lifecycle) and the reliable outbox-job queue for cross-system side effects
(object-storage cleanup now; Milvus/memory work as later packages register
handlers). Both key on the stable ``users.id`` (FK, ON DELETE CASCADE).

Additive — the legacy ``user_uploads`` table stays in place during the
migration; its consumers move to ``file_assets`` in the domain packages, and
it is dropped in CLEANUP.

Revision ID: 0018_file_assets_outbox
Revises: 0017_model_config_tables
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0018_file_assets_outbox"
down_revision: Union[str, None] = "0017_model_config_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not _has_table(insp, "file_assets"):
        op.create_table(
            "file_assets",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column("purpose", sa.String(), nullable=False, index=True),
            sa.Column("original_filename", sa.String(), nullable=False),
            sa.Column("object_key", sa.String(), nullable=False, unique=True, index=True),
            sa.Column("storage_uri", sa.String(), nullable=False),
            sa.Column("content_type", sa.String(), nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=True),
            sa.Column("checksum_sha256", sa.String(), nullable=True),
            sa.Column("upload_status", sa.String(), nullable=False, server_default="pending_upload", index=True),
            sa.Column("validation_status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("validation_error", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_file_assets_user_purpose", "file_assets", ["user_id", "purpose"])

    if not _has_table(insp, "outbox_jobs"):
        op.create_table(
            "outbox_jobs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column("job_type", sa.String(), nullable=False, index=True),
            sa.Column("aggregate_type", sa.String(), nullable=True),
            sa.Column("aggregate_id", sa.String(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending", index=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("next_run_at", sa.DateTime(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("idempotency_key", sa.String(), nullable=True),
            sa.Column("locked_at", sa.DateTime(), nullable=True),
            sa.Column("locked_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("job_type", "idempotency_key", name="uq_outbox_jobs_type_idem"),
        )
        op.create_index(
            "ix_outbox_jobs_status_next_run", "outbox_jobs", ["status", "next_run_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if _has_table(insp, "outbox_jobs"):
        op.drop_table("outbox_jobs")
    if _has_table(insp, "file_assets"):
        op.drop_table("file_assets")
