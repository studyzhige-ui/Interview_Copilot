"""Resolve mock sources through their canonical owners, without model IO."""

from sqlalchemy.orm import Session
from app.models.job_description_snapshot import JobDescriptionSnapshot
from app.models.job_opportunity import JobOpportunity


class MockJobDescriptionUnavailable(ValueError):
    pass


def resolve_job_description(
    db: Session,
    *,
    user_pk: int,
    jd_text: str | None,
    job_opportunity_id: str | None = None,
    jd_snapshot_id: str | None = None,
    jd_snapshot_version: int | None = None,
) -> str:
    if jd_snapshot_id is None:
        if jd_snapshot_version is not None or jd_text is None:
            raise MockJobDescriptionUnavailable("Supply a complete, explicit JD source")
        text = jd_text.strip()
    else:
        if jd_text is not None or jd_snapshot_version is None or not job_opportunity_id:
            raise MockJobDescriptionUnavailable("Supply exactly one explicit JD source")
        snapshot = (
            db.query(JobDescriptionSnapshot)
            .join(
                JobOpportunity,
                JobOpportunity.id == JobDescriptionSnapshot.job_opportunity_id,
            )
            .filter(
                JobOpportunity.user_id == user_pk,
                JobOpportunity.archived_at.is_(None),
                JobOpportunity.id == job_opportunity_id,
                JobDescriptionSnapshot.id == jd_snapshot_id,
                JobDescriptionSnapshot.version == jd_snapshot_version,
            )
            .one_or_none()
        )
        if snapshot is None:
            raise MockJobDescriptionUnavailable("JD snapshot is unavailable or changed")
        text = snapshot.canonical_content.strip()
    if not 20 <= len(text) <= 50_000:
        raise MockJobDescriptionUnavailable(
            "JD must contain 20 to 50000 characters; no silent truncation"
        )
    return text
