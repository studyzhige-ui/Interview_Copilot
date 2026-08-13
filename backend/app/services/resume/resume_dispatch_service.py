"""Post-commit dispatch for canonical resume Artifact parsing."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.services.resume import resume_artifact_service
from app.task_queue.dispatch import dispatch_resume_parse

logger = logging.getLogger(__name__)


def dispatch_parse_after_commit(
    db: Session,
    record: resume_artifact_service.ResumeArtifactRecord,
) -> bool:
    """Dispatch the exact current version and expose broker failure as state.

    The Artifact/version transaction must already be committed. A delayed
    dispatch failure cannot mark a newer version failed because the state
    command is version-scoped.
    """

    version = record.current_version
    if not (version.file_asset_id or (version.content_text or "").strip()):
        return False
    try:
        dispatch_resume_parse(record.artifact.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "resume Artifact parse dispatch failed for %s: %s",
            record.artifact.id,
            exc,
        )
        try:
            resume_artifact_service.mark_parse_state(
                db,
                user_pk=record.artifact.user_id,
                resume_id=record.artifact.id,
                status="failed",
                error="简历解析任务派发失败，请稍后重试。",
                source_version_id=version.id,
            )
        except resume_artifact_service.ResumeArtifactStaleVersionError:
            db.rollback()
            return False
        db.commit()
        return False
    return True


__all__ = ["dispatch_parse_after_commit"]
