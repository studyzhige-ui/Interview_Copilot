from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_user(username="alice"):
    user = MagicMock()
    user.username = username
    return user


@pytest.mark.asyncio
async def test_create_knowledge_upload_url_uses_owned_path(db_session):
    from app.api.rag_api import KnowledgeUploadRequest, create_knowledge_upload_url

    with patch("app.services.upload_service.generate_presigned_upload_url_for_key") as mock_url:
        mock_url.return_value = {"upload_url": "https://upload", "storage_uri": "s3://bucket/key"}
        result = await create_knowledge_upload_url(
            KnowledgeUploadRequest(filename="Redis 题库.pdf", content_type="application/pdf"),
            db=db_session,
            current_user=_make_user("alice"),
    )

    assert result["status"] == "success"
    assert result["upload_id"].startswith("upl_")
    from app.models.upload import UserUpload

    upload = db_session.get(UserUpload, result["upload_id"])
    assert upload.user_id == "alice"
    assert upload.purpose == "knowledge_document"
    assert upload.object_key.startswith(f"uploads/alice/{upload.id}/")


@pytest.mark.asyncio
async def test_create_knowledge_document_rejects_other_user_upload(db_session):
    from app.api.rag_api import KnowledgeDocumentCreateRequest, create_knowledge_document
    from app.models.upload import UserUpload

    upload = UserUpload(
        user_id="bob",
        purpose="knowledge_document",
        original_filename="redis.pdf",
        storage_uri="s3://bucket/uploads/bob/upl_b/redis.pdf",
        object_key="uploads/bob/upl_b/redis.pdf",
        status="uploaded",
    )
    db_session.add(upload)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await create_knowledge_document(
            KnowledgeDocumentCreateRequest(upload_id=upload.id),
            db=db_session,
            current_user=_make_user("alice"),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_create_knowledge_document_dispatches_internal_document_id(db_session):
    from app.api.rag_api import KnowledgeDocumentCreateRequest, create_knowledge_document
    from app.models.upload import UserUpload

    upload = UserUpload(
        user_id="alice",
        purpose="knowledge_document",
        original_filename="redis.pdf",
        storage_uri="s3://bucket/uploads/alice/upl_a/redis.pdf",
        object_key="uploads/alice/upl_a/redis.pdf",
        status="uploaded",
    )
    db_session.add(upload)
    db_session.flush()

    task = MagicMock()
    task.id = "task-1"
    with patch("app.api.rag_api.process_document_ingestion") as mock_task:
        mock_task.delay.return_value = task
        result = await create_knowledge_document(
            KnowledgeDocumentCreateRequest(
                upload_id=upload.id,
                title="Redis 题库",
                category="后端",
            ),
            db=db_session,
            current_user=_make_user("alice"),
        )

    document_id = result["document"]["id"]
    mock_task.delay.assert_called_once_with(document_id)
    assert result["document"]["category"] == "后端"


@pytest.mark.asyncio
async def test_list_documents_is_user_scoped(db_session):
    from app.api.rag_api import list_knowledge_documents
    from app.models.knowledge import KnowledgeDocument
    from app.models.upload import UserUpload

    for user in ["alice", "bob"]:
        upload = UserUpload(
            user_id=user,
            purpose="knowledge_document",
            original_filename=f"{user}.pdf",
            storage_uri=f"s3://bucket/uploads/{user}/upl/{user}.pdf",
            object_key=f"uploads/{user}/upl/{user}.pdf",
            status="consumed",
        )
        db_session.add(upload)
        db_session.flush()
        db_session.add(
            KnowledgeDocument(
                user_id=user,
                upload_id=upload.id,
                title=f"{user} doc",
                category="默认",
                source_type="interview_qa",
                storage_uri=upload.storage_uri,
                object_key=upload.object_key,
                status="ready",
            )
        )
    db_session.flush()

    result = await list_knowledge_documents(db=db_session, current_user=_make_user("alice"))

    assert [doc["title"] for doc in result["documents"]] == ["alice doc"]


def test_hard_delete_removes_document_and_upload_after_backends_succeed(db_session):
    from app.core.config import settings
    from app.models.knowledge import KnowledgeDocument
    from app.models.upload import UserUpload
    from app.services.knowledge_service import hard_delete_knowledge_document

    upload = UserUpload(
        user_id="alice",
        purpose="knowledge_document",
        original_filename="redis.pdf",
        storage_uri=f"s3://{settings.S3_BUCKET_NAME}/placeholder",
        object_key="placeholder",
        status="consumed",
    )
    db_session.add(upload)
    db_session.flush()
    upload.object_key = f"uploads/alice/{upload.id}/redis.pdf"
    upload.storage_uri = f"s3://{settings.S3_BUCKET_NAME}/{upload.object_key}"
    document = KnowledgeDocument(
        user_id="alice",
        upload_id=upload.id,
        title="Redis",
        category="后端",
        source_type="interview_qa",
        storage_uri=upload.storage_uri,
        object_key=upload.object_key,
        status="ready",
        node_ids='["node-1"]',
        ref_doc_ids='["ref-1"]',
    )
    db_session.add(document)
    db_session.commit()

    with (
        patch("app.services.knowledge_service.delete_document_vectors_and_docstore") as mock_vectors,
        patch("app.services.knowledge_service.delete_s3_object") as mock_s3,
    ):
        hard_delete_knowledge_document(db_session, document)

    mock_vectors.assert_called_once()
    mock_s3.assert_called_once_with(upload.storage_uri)
    assert db_session.get(KnowledgeDocument, document.id) is None
    assert db_session.get(UserUpload, upload.id) is None


def test_hard_delete_keeps_record_when_backend_delete_fails(db_session):
    from app.core.config import settings
    from app.models.knowledge import KnowledgeDocument
    from app.models.upload import UserUpload
    from app.services.knowledge_service import hard_delete_knowledge_document

    upload = UserUpload(
        user_id="alice",
        purpose="knowledge_document",
        original_filename="redis.pdf",
        storage_uri=f"s3://{settings.S3_BUCKET_NAME}/placeholder",
        object_key="placeholder",
        status="consumed",
    )
    db_session.add(upload)
    db_session.flush()
    upload.object_key = f"uploads/alice/{upload.id}/redis.pdf"
    upload.storage_uri = f"s3://{settings.S3_BUCKET_NAME}/{upload.object_key}"
    document = KnowledgeDocument(
        user_id="alice",
        upload_id=upload.id,
        title="Redis",
        category="后端",
        source_type="interview_qa",
        storage_uri=upload.storage_uri,
        object_key=upload.object_key,
        status="ready",
    )
    db_session.add(document)
    db_session.commit()

    with (
        patch(
            "app.services.knowledge_service.delete_document_vectors_and_docstore",
            side_effect=RuntimeError("vector delete failed"),
        ),
        patch("app.services.knowledge_service.delete_s3_object") as mock_s3,
        pytest.raises(RuntimeError),
    ):
        hard_delete_knowledge_document(db_session, document)

    saved = db_session.get(KnowledgeDocument, document.id)
    assert saved is not None
    assert saved.status == "delete_failed"
    assert "vector delete failed" in saved.error_message
    assert db_session.get(UserUpload, upload.id) is not None
    mock_s3.assert_not_called()
