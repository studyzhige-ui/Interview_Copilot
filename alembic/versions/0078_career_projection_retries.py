"""Index replayed pipeline stages and bind document retries to their commands."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.models.job_opportunity import JobOpportunity, ProcessEvent
from app.career.application.process import project_events

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "job_opportunities",
        sa.Column(
            "pipeline_stage", sa.String(32), nullable=False, server_default="saved"
        ),
    )
    op.add_column(
        "document_drafts", sa.Column("last_save_key", sa.String(100), nullable=True)
    )
    op.add_column(
        "document_drafts",
        sa.Column("last_save_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "artifact_versions", sa.Column("draft_revision", sa.Integer(), nullable=True)
    )
    # Read only the history required for each batch. Do not replay action closures,
    # change optimistic versions, or rewrite event timestamps during backfill.
    db = Session(bind=op.get_bind())
    after = ""
    while True:
        ids = [
            row[0]
            for row in db.query(JobOpportunity.id)
            .filter(JobOpportunity.id > after)
            .order_by(JobOpportunity.id)
            .limit(500)
            .all()
        ]
        if not ids:
            break
        events = {}
        for event in (
            db.query(ProcessEvent)
            .filter(ProcessEvent.job_opportunity_id.in_(ids))
            .order_by(ProcessEvent.sequence)
            .all()
        ):
            events.setdefault(event.job_opportunity_id, []).append(event)
        for job_id in ids:
            if events.get(job_id):
                stage = project_events(events[job_id])[3]
                db.execute(
                    sa.update(JobOpportunity)
                    .where(JobOpportunity.id == job_id)
                    .values(pipeline_stage=stage, updated_at=JobOpportunity.updated_at)
                )
        after = ids[-1]
    db.flush()
    op.create_index(
        "ix_job_opportunities_user_pipeline_updated",
        "job_opportunities",
        ["user_id", "pipeline_stage", "updated_at", "id"],
    )


def downgrade():
    op.drop_index(
        "ix_job_opportunities_user_pipeline_updated", table_name="job_opportunities"
    )
    op.drop_column("artifact_versions", "draft_revision")
    op.drop_column("document_drafts", "last_save_fingerprint")
    op.drop_column("document_drafts", "last_save_key")
    op.drop_column("job_opportunities", "pipeline_stage")
