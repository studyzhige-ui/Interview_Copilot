"""Freeze the exact FileAsset version used by an ArtifactVersion.

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "artifact_versions",
        sa.Column("file_asset_version", sa.String(length=96), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("artifact_versions", "file_asset_version")
