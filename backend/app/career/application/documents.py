"""Structured document drafts publish to the existing Artifact owner."""

import json
import hashlib
from app.career.application import artifacts
from app.career.application.resumes import resume_artifact_service
from app.models.artifact import ArtifactVersion, ArtifactResumeState
from app.models.career_workspace import DocumentDraft
from app.schemas.artifact import ArtifactWriteInput
from app.schemas.career_workspace import ResumeDocument
from app.db.types import utc_now


def _version(title, data):
    return ArtifactWriteInput(
        title=title,
        content_text=data.plain_text(),
        content_format="markdown",
        document_json=data.model_dump(),
    )


def _ready(db, user_pk, artifact):
    if artifact.kind == "resume":
        current = artifacts.get_current_artifact_version(
            db, user_pk=user_pk, artifact_id=artifact.id
        )
        # An empty editor template is a document, not a usable default resume.
        if not ResumeDocument.model_validate(current.document_json).has_content():
            state = (
                db.query(ArtifactResumeState)
                .filter_by(artifact_id=artifact.id)
                .one_or_none()
            )
            if state:
                was_default = state.is_default
                state.is_default = False
                state.parse_status = "failed"
                state.parse_error = "文档内容为空，请在编辑器中补充内容"
                state.parse_version_id = current.id
                state.section_spans_json = None
                db.flush()
                if was_default:
                    for candidate in resume_artifact_service.list_resume_artifacts(
                        db, user_pk=user_pk
                    ):
                        if (
                            candidate.artifact.id != artifact.id
                            and candidate.state.parse_status == "ready"
                            and candidate.state.parse_version_id
                            == candidate.current_version.id
                        ):
                            candidate.state.is_default = True
                            break
                    db.flush()
            return
        record = resume_artifact_service.register_resume_artifact(
            db, user_pk=user_pk, artifact_id=artifact.id
        )
        record.state.parse_status = "ready"
        record.state.parse_version_id = record.current_version.id
        record.state.parse_error = None
        text = (record.current_version.content_text or "").strip()
        record.state.section_spans_json = json.dumps(
            [
                {
                    "section_type": "other",
                    "title": "完整简历",
                    "start": 0,
                    "end": len(text),
                }
            ],
            ensure_ascii=False,
        )
        db.flush()


def create_document(db, user_pk, command):
    resume_artifact_service._lock_user(db, user_pk=user_pk)
    artifact = artifacts.save_artifact_explicitly(
        db,
        user_pk=user_pk,
        operation_key=command.operation_key,
        artifact_kind=command.kind,
        version=_version(command.title, command.data),
    )
    if command.opportunity_id:
        from app.career.application.workspace import owned_job

        job = owned_job(db, user_pk, command.opportunity_id)
        artifacts.relate_artifact_to_job(
            db,
            user_pk=user_pk,
            artifact_id=artifact.id,
            job_opportunity_id=job.id,
            job_owner_checker=lambda session, owner, kind, ref: (
                ref == job.id and owner == user_pk
            ),
        )
    _ready(db, user_pk, artifact)
    return get_draft(db, user_pk, artifact.id)


def get_draft(db, user_pk, artifact_id):
    artifact = artifacts._owned_artifact_locked(db, user_pk, artifact_id)
    current = artifacts.get_current_artifact_version(
        db, user_pk=user_pk, artifact_id=artifact.id, include_archived=True
    )
    draft = db.get(DocumentDraft, artifact.id)
    text = current.content_text or ""
    data = (
        current.document_json
        or ResumeDocument(
            sections=[
                {
                    "id": f"import-{index}",
                    "title": "原始内容",
                    "content": text[index : index + 30000],
                }
                for index in range(0, max(1, len(text)), 30000)
            ]
        ).model_dump()
    )
    return {
        "artifact_id": artifact.id,
        "kind": artifact.kind,
        "archived": artifact.archived_at is not None,
        "revision": draft.revision if draft else 0,
        "base_version_id": draft.base_version_id if draft else current.id,
        "current_version_id": current.id,
        "title": draft.title if draft else current.title,
        "data": draft.data if draft else data,
        "updated_at": draft.updated_at if draft else current.created_at,
        "awaiting_extraction": bool(
            current.file_asset_id
            and not current.content_text
            and not current.document_json
        ),
    }


def save_draft(db, user_pk, artifact_id, command):
    artifact = artifacts._require_active_artifact(db, user_pk, artifact_id)
    # Lock the stable owner even when its draft row does not exist yet.
    artifacts._owned_artifact_locked(db, user_pk, artifact.id)
    current = artifacts.get_current_artifact_version(
        db, user_pk=user_pk, artifact_id=artifact.id
    )
    draft = db.get(DocumentDraft, artifact.id)
    fingerprint = hashlib.sha256(
        command.model_dump_json(exclude={"operation_key"}).encode()
    ).hexdigest()
    if draft and draft.last_save_key == command.operation_key:
        if draft.last_save_fingerprint != fingerprint:
            raise artifacts.ArtifactConflictError("同一保存操作不能用于不同内容")
        return get_draft(db, user_pk, artifact.id)
    if current.file_asset_id and not current.content_text and not current.document_json:
        raise artifacts.ArtifactConflictError("请等待原文件提取完成，或重试解析")
    if (
        command.base_version_id != current.id
        or (draft.revision if draft else 0) != command.expected_revision
    ):
        raise artifacts.ArtifactConflictError(
            "文档已在别处更新，本地草稿已保留，请先刷新比较"
        )
    if draft is None:
        draft = DocumentDraft(artifact_id=artifact.id, revision=0)
    draft.revision += 1
    draft.base_version_id = current.id
    draft.title, draft.data = command.title, command.data.model_dump()
    draft.last_save_key, draft.last_save_fingerprint = (
        command.operation_key,
        fingerprint,
    )
    draft.updated_at = utc_now()
    db.add(draft)
    db.flush()
    return get_draft(db, user_pk, artifact.id)


def publish(db, user_pk, artifact_id, command):
    resume_artifact_service._lock_user(db, user_pk=user_pk)
    artifact = artifacts._owned_artifact_locked(db, user_pk, artifact_id)
    existing = (
        db.query(ArtifactVersion)
        .filter_by(artifact_id=artifact.id, operation_key=command.operation_key)
        .one_or_none()
    )
    if existing:
        if existing.draft_revision != command.expected_revision:
            raise artifacts.ArtifactConflictError("同一发布操作不能用于不同草稿")
        return get_draft(db, user_pk, artifact.id)
    draft = db.get(DocumentDraft, artifact.id)
    if draft is None or draft.revision != command.expected_revision:
        raise artifacts.ArtifactConflictError("草稿已改变，请保存后重试")
    current = artifacts.get_current_artifact_version(
        db, user_pk=user_pk, artifact_id=artifact.id
    )
    if current.id != draft.base_version_id:
        raise artifacts.ArtifactConflictError("正式文档已有新版本，请先刷新比较")
    version = artifacts.edit_artifact(
        db,
        user_pk=user_pk,
        artifact_id=artifact.id,
        operation_key=command.operation_key,
        version=_version(draft.title, ResumeDocument.model_validate(draft.data)),
        draft_revision=command.expected_revision,
    )
    draft.base_version_id = version.id
    draft.revision += 1
    draft.updated_at = utc_now()
    _ready(db, user_pk, artifact)
    db.flush()
    return get_draft(db, user_pk, artifact.id)
