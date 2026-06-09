"""RESUME-INTERVIEW: transcript split + interview_records resume/file-asset
columns + resume_sections.resume_id.

Clean rebuild (no backfill): the data stores are empty, so this is a direct
schema cut to the target architecture.

  * New ``interview_transcripts`` table — transcript full text + segments move
    out of ``interview_records`` (which keeps only a ``transcript_id`` ref).
  * ``interview_records``: drop legacy ``transcript`` / ``transcript_segments_json``
    / ``resume_doc_id`` and the ``*_upload_id`` columns; add the file-asset refs
    (``audio_file_asset_id`` / ``resume_file_asset_id`` / ``jd_file_asset_id``),
    the personal-resume linkage (``resume_id`` FK / ``resume_source`` /
    ``resume_title_snapshot``), ``category``, ``resume_structured_snapshot_json``
    and ``transcript_id``.
  * ``resume_sections``: ``upload_id`` -> ``resume_id`` (FK to resumes) + add
    ``order_idx``.

Revision ID: 0034_resume_interview_split
Revises: 0033_resume_sections_user_pk
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0034_resume_interview_split"
down_revision: Union[str, None] = "0033_resume_sections_user_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(insp, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)}


def _indexes(insp, table: str) -> set[str]:
    return {i["name"] for i in insp.get_indexes(table)}


def _tables(insp) -> set[str]:
    return set(insp.get_table_names())


# interview_records column deltas
_IR = "interview_records"
_IR_DROP = [
    "transcript",
    "transcript_segments_json",
    "resume_doc_id",
    "audio_upload_id",
    "resume_upload_id",
    "jd_upload_id",
    "resume_structured_json",
]
_IR_ADD = [
    ("category", lambda: sa.Column("category", sa.String(), nullable=True)),
    ("audio_file_asset_id", lambda: sa.Column("audio_file_asset_id", sa.String(), nullable=True)),
    ("resume_file_asset_id", lambda: sa.Column("resume_file_asset_id", sa.String(), nullable=True)),
    ("jd_file_asset_id", lambda: sa.Column("jd_file_asset_id", sa.String(), nullable=True)),
    ("resume_id", lambda: sa.Column("resume_id", sa.String(), nullable=True)),
    ("resume_source", lambda: sa.Column("resume_source", sa.String(), nullable=True)),
    ("resume_title_snapshot", lambda: sa.Column("resume_title_snapshot", sa.String(), nullable=True)),
    ("resume_structured_snapshot_json", lambda: sa.Column("resume_structured_snapshot_json", sa.Text(), nullable=True)),
    ("transcript_id", lambda: sa.Column("transcript_id", sa.String(), nullable=True)),
]
_IR_RESUME_FK = "fk_interview_records_resume_id"
_IR_TRANSCRIPT_IDX = "ix_interview_records_transcript_id"


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    # ── interview_transcripts (new) ──────────────────────────────────────
    if "interview_transcripts" not in _tables(insp):
        op.create_table(
            "interview_transcripts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "record_id", sa.String(),
                sa.ForeignKey("interview_records.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("language", sa.String(), nullable=True),
            sa.Column("text", sa.Text(), nullable=True),
            sa.Column("segments_json", sa.Text(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_interview_transcripts_record_id", "interview_transcripts", ["record_id"])
        op.create_index("ix_interview_transcripts_user_id", "interview_transcripts", ["user_id"])

    # ── interview_records: drop legacy, add target columns ───────────────
    have = _cols(insp, _IR)
    for col in _IR_DROP:
        if col in have:
            op.drop_column(_IR, col)
    have = _cols(inspect(bind), _IR)
    for name, factory in _IR_ADD:
        if name not in have:
            op.add_column(_IR, factory())
    if _IR_TRANSCRIPT_IDX not in _indexes(inspect(bind), _IR):
        op.create_index(_IR_TRANSCRIPT_IDX, _IR, ["transcript_id"])
    # resume_id FK — skipped on SQLite (no ALTER ADD CONSTRAINT; the model-level
    # ForeignKey still applies when tables are created from metadata in tests).
    if not is_sqlite:
        op.create_foreign_key(
            _IR_RESUME_FK, _IR, "resumes", ["resume_id"], ["id"], ondelete="SET NULL",
        )

    # ── resume_sections: upload_id -> resume_id + order_idx ──────────────
    rs_cols = _cols(inspect(bind), "resume_sections")
    rs_idx = _indexes(inspect(bind), "resume_sections")
    if "ix_resume_sections_upload_id" in rs_idx:
        op.drop_index("ix_resume_sections_upload_id", table_name="resume_sections")
    if "upload_id" in rs_cols:
        op.drop_column("resume_sections", "upload_id")
    if "resume_id" not in rs_cols:
        op.add_column("resume_sections", sa.Column("resume_id", sa.String(), nullable=False))
        op.create_index("ix_resume_sections_resume_id", "resume_sections", ["resume_id"])
        if not is_sqlite:
            op.create_foreign_key(
                "fk_resume_sections_resume_id", "resume_sections", "resumes",
                ["resume_id"], ["id"], ondelete="CASCADE",
            )
    if "order_idx" not in rs_cols:
        op.add_column(
            "resume_sections",
            sa.Column("order_idx", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # resume_sections: resume_id -> upload_id
    rs_cols = _cols(inspect(bind), "resume_sections")
    if "order_idx" in rs_cols:
        op.drop_column("resume_sections", "order_idx")
    if not is_sqlite:
        try:
            op.drop_constraint("fk_resume_sections_resume_id", "resume_sections", type_="foreignkey")
        except Exception:  # noqa: BLE001
            pass
    if "ix_resume_sections_resume_id" in _indexes(inspect(bind), "resume_sections"):
        op.drop_index("ix_resume_sections_resume_id", table_name="resume_sections")
    if "resume_id" in rs_cols:
        op.drop_column("resume_sections", "resume_id")
    if "upload_id" not in _cols(inspect(bind), "resume_sections"):
        op.add_column("resume_sections", sa.Column("upload_id", sa.String(), nullable=False))
        op.create_index("ix_resume_sections_upload_id", "resume_sections", ["upload_id"])

    # interview_records: reverse columns
    if not is_sqlite:
        try:
            op.drop_constraint(_IR_RESUME_FK, _IR, type_="foreignkey")
        except Exception:  # noqa: BLE001
            pass
    if _IR_TRANSCRIPT_IDX in _indexes(inspect(bind), _IR):
        op.drop_index(_IR_TRANSCRIPT_IDX, table_name=_IR)
    have = _cols(inspect(bind), _IR)
    for name, _ in _IR_ADD:
        if name in have:
            op.drop_column(_IR, name)
    have = _cols(inspect(bind), _IR)
    _readd = [
        ("transcript", sa.Text()),
        ("transcript_segments_json", sa.Text()),
        ("resume_doc_id", sa.String()),
        ("audio_upload_id", sa.String()),
        ("resume_upload_id", sa.String()),
        ("jd_upload_id", sa.String()),
        ("resume_structured_json", sa.Text()),
    ]
    for name, type_ in _readd:
        if name not in have:
            op.add_column(_IR, sa.Column(name, type_, nullable=True))

    # interview_transcripts (drop last — interview_records FK points at it)
    if "interview_transcripts" in _tables(inspect(bind)):
        op.drop_table("interview_transcripts")
