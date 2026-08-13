"""Explicit, destructive deletion of one owned FileAsset and its projections."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.artifact import Artifact, ArtifactVersion
from app.models.conversation_attachment import (
    ConversationAttachmentDraft,
    ConversationAttachmentRef,
)
from app.models.file_asset import FileAsset
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.models.interview_source import InterviewSourceRef
from app.models.knowledge import KnowledgeDocument
from app.models.resume import Resume
from app.schemas.file_assets import (
    FileAssetDeletionImpact,
    FileAssetPermanentDeleteResult,
    FileAssetReferenceImpact,
)


class FileAssetDeletionError(ValueError):
    """Base permanent-deletion error."""


class FileAssetDeletionNotFoundError(FileAssetDeletionError):
    """The FileAsset is absent or belongs to another user."""


class FileAssetDeletionConflictError(FileAssetDeletionError):
    """The explicit preview/confirmation is stale or mismatched."""


@dataclass(frozen=True)
class FileAssetDeletionExecution:
    result: FileAssetPermanentDeleteResult
    ingestion_task_ids: tuple[str, ...]


def preview_file_asset_deletion(
    db: Session,
    *,
    user_pk: int,
    file_asset_id: str,
) -> FileAssetDeletionImpact:
    asset = _owned_asset(db, user_pk=user_pk, file_asset_id=file_asset_id)
    return _impact(db, asset)


def permanently_delete_file_asset(
    db: Session,
    *,
    user_pk: int,
    file_asset_id: str,
    confirmation_token: str,
    confirm_file_asset_id: str,
    confirm_filename: str,
) -> FileAssetDeletionExecution:
    """Revoke every Copilot scope and delete controllable bytes/projections.

    Formal owners retain their exact historical FileAsset identity, now a
    tombstone, so old Artifact/Interview records are not silently rewritten.
    The caller commits and then revokes returned ingestion jobs.
    """

    asset = _owned_asset(
        db,
        user_pk=user_pk,
        file_asset_id=file_asset_id,
        for_update=True,
    )
    if asset.deleted_at is not None or asset.upload_status in {
        "delete_pending",
        "deleted",
    }:
        raise FileAssetDeletionConflictError("FileAsset is already deleted")
    if confirm_file_asset_id.strip() != asset.id:
        raise FileAssetDeletionConflictError("FileAsset confirmation mismatch")
    if confirm_filename != asset.original_filename:
        raise FileAssetDeletionConflictError("filename confirmation mismatch")
    impact = _impact(db, asset)
    if not hmac.compare_digest(
        (confirmation_token or "").strip(), impact.confirmation_token
    ):
        raise FileAssetDeletionConflictError(
            "FileAsset references changed after preview; review the impact again"
        )

    now = utc_now()
    drafts = (
        db.query(ConversationAttachmentDraft)
        .filter(
            ConversationAttachmentDraft.user_id == user_pk,
            ConversationAttachmentDraft.file_asset_id == asset.id,
        )
        .with_for_update()
        .all()
    )
    refs = (
        db.query(ConversationAttachmentRef)
        .filter(
            ConversationAttachmentRef.user_id == user_pk,
            ConversationAttachmentRef.file_asset_id == asset.id,
        )
        .with_for_update()
        .all()
    )
    debrief_refs = (
        db.query(InterviewSourceRef)
        .filter(
            InterviewSourceRef.user_id == user_pk,
            InterviewSourceRef.file_asset_id == asset.id,
        )
        .with_for_update()
        .all()
    )
    documents = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.user_id == user_pk,
            KnowledgeDocument.file_asset_id == asset.id,
        )
        .with_for_update()
        .all()
    )
    active_draft_count = sum(draft.removed_at is None for draft in drafts)
    active_ref_count = sum(ref.removed_at is None for ref in refs)
    active_debrief_ref_count = sum(ref.removed_at is None for ref in debrief_refs)
    for draft in drafts:
        draft.removed_at = draft.removed_at or now
        db.add(draft)
    for ref in refs:
        ref.removed_at = ref.removed_at or now
        db.add(ref)
    for ref in debrief_refs:
        ref.removed_at = ref.removed_at or now
        db.add(ref)

    ingestion_task_ids: list[str] = []
    from app.services.knowledge.knowledge_service import (
        delete_document_vectors_and_chunks,
    )

    for document in documents:
        if document.task_id:
            ingestion_task_ids.append(document.task_id)
        delete_document_vectors_and_chunks(db, document)
        document.status = "failed"
        document.error_message = "原始文件已由用户永久删除。"
        document.content_text = None
        document.chunk_count = 0
        document.ref_doc_ids = "[]"
        document.task_id = None
        document.deleted_at = document.deleted_at or now
        document.updated_at = now
        db.add(document)

    from app.services.uploads.file_asset_service import enqueue_asset_blob_delete

    enqueue_asset_blob_delete(db, asset)
    asset.upload_status = "delete_pending"
    asset.validation_status = "failed"
    asset.validation_error = "permanently_deleted_by_user"
    asset.deleted_at = now
    asset.updated_at = now
    db.add(asset)
    db.flush()
    formal_count = sum(
        item.active_count + item.tombstone_count
        for item in impact.reference_impacts
        if item.reference_type
        in {"artifact_version", "legacy_resume", "interview_record", "interview_qa"}
    )
    return FileAssetDeletionExecution(
        result=FileAssetPermanentDeleteResult(
            status="delete_pending",
            file_asset_id=asset.id,
            removed_draft_scopes=active_draft_count,
            removed_conversation_scopes=active_ref_count,
            removed_debrief_scopes=active_debrief_ref_count,
            deleted_projections=len(documents),
            preserved_reference_tombstones=(
                formal_count + len(drafts) + len(refs) + len(debrief_refs)
            ),
        ),
        ingestion_task_ids=tuple(dict.fromkeys(ingestion_task_ids)),
    )


def _impact(db: Session, asset: FileAsset) -> FileAssetDeletionImpact:
    drafts = (
        db.query(ConversationAttachmentDraft)
        .filter(
            ConversationAttachmentDraft.user_id == asset.user_id,
            ConversationAttachmentDraft.file_asset_id == asset.id,
        )
        .all()
    )
    refs = (
        db.query(ConversationAttachmentRef)
        .filter(
            ConversationAttachmentRef.user_id == asset.user_id,
            ConversationAttachmentRef.file_asset_id == asset.id,
        )
        .all()
    )
    debrief_refs = (
        db.query(InterviewSourceRef)
        .filter(
            InterviewSourceRef.user_id == asset.user_id,
            InterviewSourceRef.file_asset_id == asset.id,
        )
        .all()
    )
    documents = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.user_id == asset.user_id,
            KnowledgeDocument.file_asset_id == asset.id,
        )
        .all()
    )
    artifact_versions = (
        db.query(ArtifactVersion)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .filter(
            Artifact.user_id == asset.user_id,
            ArtifactVersion.file_asset_id == asset.id,
        )
        .all()
    )
    resumes = (
        db.query(Resume)
        .filter(
            Resume.user_id == asset.user_id,
            Resume.file_asset_id == asset.id,
        )
        .all()
    )
    interview_records = (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.user_id == asset.user_id,
            or_(
                InterviewRecord.audio_file_asset_id == asset.id,
                InterviewRecord.resume_file_asset_id == asset.id,
                InterviewRecord.jd_file_asset_id == asset.id,
            ),
        )
        .all()
    )
    interview_qas = (
        db.query(InterviewQA)
        .join(InterviewRecord, InterviewRecord.id == InterviewQA.record_id)
        .filter(
            InterviewRecord.user_id == asset.user_id,
            InterviewQA.answer_audio_file_asset_id == asset.id,
        )
        .all()
    )
    impacts = [
        _ref_impact(
            "conversation_draft",
            drafts,
            effect="撤回草稿引用；待发送输入会明确显示来源失效，直到用户编辑或撤回。",
        ),
        _ref_impact(
            "conversation_attachment",
            refs,
            effect="撤销未来读取；历史 AttachmentRef 保留为不可访问 tombstone。",
        ),
        _ref_impact(
            "debrief_project_source",
            debrief_refs,
            effect="从对应本次复盘 scope 移除；其他复盘不受影响。",
        ),
        FileAssetReferenceImpact(
            reference_type="parsing_projection",
            active_count=sum(1 for row in documents if row.deleted_at is None),
            tombstone_count=sum(1 for row in documents if row.deleted_at is not None),
            effect="删除正文、chunks 与检索投影；仅保留失效来源身份。",
        ),
        FileAssetReferenceImpact(
            reference_type="artifact_version",
            active_count=len(artifact_versions),
            effect="ArtifactVersion 历史身份保留，但原文件不可再读取。",
        ),
        FileAssetReferenceImpact(
            reference_type="legacy_resume",
            active_count=len(resumes),
            effect="旧迁移记录保留为历史引用，不恢复原文件。",
        ),
        FileAssetReferenceImpact(
            reference_type="interview_record",
            active_count=len(interview_records),
            effect="面试记录保留，关联原文件显示已删除。",
        ),
        FileAssetReferenceImpact(
            reference_type="interview_qa",
            active_count=len(interview_qas),
            effect="问答记录保留，关联音频显示已删除。",
        ),
    ]
    impacts = [item for item in impacts if item.active_count or item.tombstone_count]
    known_transmission_ids = _known_external_transmission_ids(db, asset)
    fingerprint = {
        "asset": [
            asset.id,
            asset.upload_status,
            asset.validation_status,
            asset.updated_at.isoformat() if asset.updated_at else None,
            asset.deleted_at.isoformat() if asset.deleted_at else None,
        ],
        "drafts": sorted((row.id, row.removed_at is not None) for row in drafts),
        "refs": sorted((row.id, row.removed_at is not None) for row in refs),
        "debrief": sorted((row.id, row.removed_at is not None) for row in debrief_refs),
        "documents": sorted((row.id, row.deleted_at is not None) for row in documents),
        "formal": sorted(
            [
                *(f"artifact_version:{row.id}" for row in artifact_versions),
                *(f"legacy_resume:{row.id}" for row in resumes),
                *(f"interview_record:{row.id}" for row in interview_records),
                *(f"interview_qa:{row.id}" for row in interview_qas),
            ]
        ),
        "known_external_transmissions": list(known_transmission_ids),
    }
    token = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return FileAssetDeletionImpact(
        file_asset_id=asset.id,
        filename=asset.original_filename,
        purpose=asset.purpose,
        size_bytes=asset.size_bytes,
        reference_impacts=impacts,
        known_external_transmission_count=len(known_transmission_ids),
        confirmation_token=token,
        disclosures=[
            "这是永久删除：Copilot 可控存储中的原始字节、正文、chunks 与索引将被删除。",
            "Conversation、Debrief、Artifact 与 Interview 历史 owner 不会被冒充为从未存在；只保留不可读取的最小引用/tombstone。",
            "删除不会回滚已经发送的邮件、投递或其他外部动作。",
            "已经发送给回答模型、MCP 或其他 Provider 的副本受其保留与删除政策约束，Copilot 不能承诺追溯清除。",
            "确认时必须同时匹配 FileAsset identity、当前影响 token 与完整文件名。",
        ],
    )


def _ref_impact(reference_type: str, rows: list[Any], *, effect: str):
    return FileAssetReferenceImpact(
        reference_type=reference_type,
        active_count=sum(1 for row in rows if row.removed_at is None),
        tombstone_count=sum(1 for row in rows if row.removed_at is not None),
        effect=effect,
    )


def _known_external_transmission_ids(
    db: Session,
    asset: FileAsset,
) -> tuple[str, ...]:
    calls = db.query(AgentToolCall).filter(AgentToolCall.user_id == asset.user_id).all()
    identities: list[str] = []
    for call in calls:
        if call.status != "completed":
            continue
        payloads = [call.arguments_json, call.result_json]
        if any(_contains_exact_asset_id(payload, asset.id) for payload in payloads):
            identities.append(f"{call.turn_id}:{call.call_id}")
    return tuple(sorted(identities))


def _contains_exact_asset_id(value: Any, asset_id: str) -> bool:
    if isinstance(value, dict):
        return any(
            (str(key) == "file_asset_id" and item == asset_id)
            or _contains_exact_asset_id(item, asset_id)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_exact_asset_id(item, asset_id) for item in value)
    return False


def _owned_asset(
    db: Session,
    *,
    user_pk: int,
    file_asset_id: str,
    for_update: bool = False,
) -> FileAsset:
    query = db.query(FileAsset).filter(
        FileAsset.id == file_asset_id.strip(),
        FileAsset.user_id == user_pk,
    )
    if for_update:
        query = query.with_for_update().populate_existing()
    asset = query.one_or_none()
    if asset is None:
        raise FileAssetDeletionNotFoundError(file_asset_id)
    return asset


__all__ = [
    "FileAssetDeletionConflictError",
    "FileAssetDeletionError",
    "FileAssetDeletionExecution",
    "FileAssetDeletionNotFoundError",
    "permanently_delete_file_asset",
    "preview_file_asset_deletion",
]
