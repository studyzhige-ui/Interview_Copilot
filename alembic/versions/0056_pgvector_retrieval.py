"""PostgreSQL retrieval projection; preserve source facts and legacy indexes.

Revision ID: 0056
Revises: 0055
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import VECTOR

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "retrieval_generations",
        sa.Column("fingerprint", sa.String(64), primary_key=True),
        sa.Column("identity_json", postgresql.JSONB(), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "embedding_dim > 0 AND embedding_dim <= 16000",
            name="ck_retrieval_generation_dim",
        ),
    )
    op.create_table(
        "retrieval_entries",
        sa.Column(
            "generation",
            sa.String(64),
            sa.ForeignKey("retrieval_generations.fingerprint", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "chunk_id",
            sa.String(),
            sa.ForeignKey("document_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("passage", sa.Text(), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.Column("term_counts", postgresql.JSONB(), nullable=False),
        sa.Column("lexical_terms", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("token_count >= 0", name="ck_retrieval_token_count"),
    )
    op.create_index(
        "ux_retrieval_generation_node",
        "retrieval_entries",
        ["generation", "node_id"],
        unique=True,
    )
    op.create_index(
        "ix_retrieval_user_generation_document",
        "retrieval_entries",
        ["user_id", "generation", "document_id"],
    )
    op.create_index("ix_retrieval_document", "retrieval_entries", ["document_id"])
    op.create_index(
        "ix_retrieval_lexical_terms",
        "retrieval_entries",
        ["lexical_terms"],
        postgresql_using="gin",
    )
    # Existing jobs retain their idempotency keys and identities. Only the
    # dispatcher vocabulary changes; no old job is paid for/replayed here.
    op.execute(
        "UPDATE outbox_jobs SET job_type='retrieval_upsert_document' WHERE job_type='milvus_upsert_document'"
    )
    op.execute(
        "UPDATE outbox_jobs SET job_type='retrieval_delete_document' WHERE job_type='milvus_delete_document'"
    )


def downgrade():
    # Projections can be rebuilt, but operator evidence/old deployments should
    # not be destroyed as a surprise side effect of a downgrade.
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM retrieval_entries)")
    ).scalar():
        raise RuntimeError(
            "Export/backup retrieval generations before destructive downgrade; original facts remain intact"
        )
    op.execute(
        "UPDATE outbox_jobs SET job_type='milvus_upsert_document' WHERE job_type='retrieval_upsert_document'"
    )
    op.execute(
        "UPDATE outbox_jobs SET job_type='milvus_delete_document' WHERE job_type='retrieval_delete_document'"
    )
    op.drop_table("retrieval_entries")
    op.drop_table("retrieval_generations")
    # The extension may belong to other application tables: never drop it here.
