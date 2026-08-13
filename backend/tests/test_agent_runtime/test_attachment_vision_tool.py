from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import fitz
from sqlalchemy.orm import sessionmaker

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, registry
from app.agent_runtime.tools import attachment_vision
from app.agent_runtime.tools.attachment_vision import InspectAttachmentPagesArgs
from app.core.model_catalog import ModelProfile
from app.models.chat import Conversation
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.models.user import User


def _profile(*, supports_vision: bool) -> ModelProfile:
    return ModelProfile(
        id="openai/vision-test",
        provider="openai",
        display_name="Vision Test",
        model="vision-test",
        api_base="https://provider.invalid/v1",
        api_key_env="TEST_KEY",
        supports_function_calling=True,
        supports_vision=supports_vision,
    )


def _pdf_bytes(page_count: int = 3) -> bytes:
    document = fitz.open()
    for index in range(page_count):
        page = document.new_page(width=320, height=480)
        page.insert_text((36, 60), f"Visual page {index + 1}", fontsize=18)
    data = document.tobytes()
    document.close()
    return data


def test_tool_is_one_exact_scope_read_surface():
    definition = registry.snapshot().entries["inspect_attachment_pages"]

    assert definition.effect is ToolEffect.READ
    assert definition.concurrency_safe is True
    assert set(InspectAttachmentPagesArgs.model_fields) == {
        "attachment_ref_id",
        "source_ref_id",
        "page_start",
        "page_count",
        "focus",
    }


def test_non_vision_primary_profile_blocks_before_file_or_network(monkeypatch):
    monkeypatch.setattr(
        attachment_vision,
        "_resolve_primary_profile",
        lambda _user_id: _profile(supports_vision=False),
    )
    monkeypatch.setattr(
        attachment_vision,
        "_load_and_render_pages",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not read attachment")
        ),
    )

    result = asyncio.run(
        registry.snapshot().dispatch(
            "inspect_attachment_pages",
            {"attachment_ref_id": "ar-1"},
            AgentToolContext(user_id="alice", session_id="conversation"),
        )
    )

    assert result == {
        "error": "attachment_page_vision_blocked",
        "blocked_reason": "primary_model_does_not_support_vision",
        "model_profile_id": "openai/vision-test",
        "provider": "openai",
    }


def test_fake_provider_produces_exact_receipt_without_network(monkeypatch):
    profile = _profile(supports_vision=True)
    rendered = attachment_vision._RenderedPage(
        number=1,
        media_type="image/jpeg",
        data=b"rendered-page",
        width=640,
        height=960,
        sha256=hashlib.sha256(b"rendered-page").hexdigest(),
    )
    inspection = attachment_vision._InspectionInput(
        identity_kind="attachment_ref",
        identity="ar-1",
        file_asset_id="fa-1",
        file_asset_version="sha256:v1",
        filename="resume.pdf",
        total_pages=1,
        pages=(rendered,),
    )
    monkeypatch.setattr(
        attachment_vision,
        "_resolve_primary_profile",
        lambda _user_id: profile,
    )
    monkeypatch.setattr(
        attachment_vision,
        "_load_and_render_pages",
        lambda _args, _ctx: inspection,
    )

    async def fake_request(**_kwargs):
        return "Page 1 has a clear hierarchy.", {"prompt_tokens": 10}, "stop"

    monkeypatch.setattr(attachment_vision, "_run_vision_request", fake_request)

    result = asyncio.run(
        registry.snapshot().dispatch(
            "inspect_attachment_pages",
            {"attachment_ref_id": "ar-1", "page_count": 1},
            AgentToolContext(user_id="alice", session_id="conversation"),
        )
    )

    assert result["status"] == "completed"
    assert result["visual_observations"].startswith("Page 1")
    assert result["coverage"]["single_call_full_coverage"] is True
    assert result["receipt"]["type"] == "model_page_vision"
    assert result["receipt"]["identity"] == "ar-1"
    assert result["receipt"]["file_asset_version"] == "sha256:v1"
    assert len(result["receipt"]["provider_response_sha256"]) == 64


def test_vision_request_uses_selected_primary_adapter_with_inline_page(monkeypatch):
    captured: dict = {}
    profile = _profile(supports_vision=True)
    rendered = attachment_vision._RenderedPage(
        number=2,
        media_type="image/jpeg",
        data=b"rendered-page",
        width=640,
        height=960,
        sha256=hashlib.sha256(b"rendered-page").hexdigest(),
    )
    inspection = attachment_vision._InspectionInput(
        identity_kind="attachment_ref",
        identity="ar-1",
        file_asset_id="fa-1",
        file_asset_version="sha256:v1",
        filename="resume.pdf",
        total_pages=3,
        pages=(rendered,),
    )

    async def chunks():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="Page 2 is visually balanced.",
                        reasoning_content=None,
                        tool_calls=[],
                    ),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=6,
                prompt_tokens_details=None,
            ),
        )

    class Completions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return chunks()

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(
        "app.core.llm_client_factory.build_provider_client_for_role",
        lambda role, user_id=None: (client, profile),
    )

    observations, usage, stop_reason = asyncio.run(
        attachment_vision._run_vision_request(
            profile=profile,
            inspection=inspection,
            focus="Check alignment",
            user_id="alice",
        )
    )

    assert observations == "Page 2 is visually balanced."
    assert usage == {"prompt_tokens": 12, "completion_tokens": 6}
    assert stop_reason == "stop"
    content = captured["messages"][-1]["content"]
    assert content[-1]["type"] == "image_url"
    assert content[-1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "Exact page window: 2-2 of 3" in content[0]["text"]


def test_real_pymupdf_render_is_page_and_pixel_bounded():
    total, pages = attachment_vision._render_page_window(
        _pdf_bytes(5),
        page_start=2,
        page_count=2,
    )

    assert total == 5
    assert [page.number for page in pages] == [2, 3]
    assert all(page.width * page.height <= 2_500_000 for page in pages)
    assert all(len(page.data) <= 2 * 1024 * 1024 for page in pages)
    assert all(page.data.startswith(b"\xff\xd8\xff") for page in pages)


def test_real_scope_resolver_requires_owner_and_frozen_version(
    db_session,
    monkeypatch,
    tmp_path,
):
    raw = _pdf_bytes(2)
    checksum = hashlib.sha256(raw).hexdigest()
    storage_file = tmp_path / "uploads" / "owner" / "fa-vision" / "resume.pdf"
    storage_file.parent.mkdir(parents=True)
    storage_file.write_bytes(raw)
    monkeypatch.setattr("app.core.config.settings.STORAGE_DIR", str(tmp_path))

    owner = User(username="vision-owner", hashed_password="x")
    other = User(username="vision-other", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.flush()
    conversation = Conversation(
        id="conv-vision",
        user_id=owner.id,
        title="vision",
    )
    turn = ConversationTurn(
        id="turn-vision",
        conversation_id=conversation.id,
        user_id=owner.id,
        mode="agent",
        message="inspect layout",
    )
    asset = FileAsset(
        id="fa-vision",
        user_id=owner.id,
        purpose="knowledge_document",
        original_filename="resume.pdf",
        object_key="uploads/owner/fa-vision/resume.pdf",
        storage_uri="local://uploads/owner/fa-vision/resume.pdf",
        content_type="application/pdf",
        size_bytes=len(raw),
        checksum_sha256=checksum,
        upload_status="consumed",
        validation_status="passed",
    )
    document = KnowledgeDocument(
        id="kdoc-vision",
        user_id=owner.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        title="resume.pdf",
        category="会话附件",
        source_kind="chat_attachment",
        content_text="parsed text",
        storage_uri=asset.storage_uri,
        object_key=asset.object_key,
        status="ready",
    )
    ref = ConversationAttachmentRef(
        id="ar-vision",
        draft_id="ad-vision",
        user_id=owner.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id="submission-vision",
        position=0,
        file_asset_id=asset.id,
        source_document_id=document.id,
        file_asset_version=f"sha256:{checksum}",
        display_name="resume.pdf",
    )
    db_session.add_all([conversation, turn, asset, document, ref])
    db_session.commit()
    maker = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    monkeypatch.setattr("app.db.database.SessionLocal", maker)

    loaded = attachment_vision._load_and_render_pages(
        InspectAttachmentPagesArgs(
            attachment_ref_id=ref.id,
            page_start=1,
            page_count=1,
        ),
        AgentToolContext(
            user_id=owner.username,
            user_pk=owner.id,
            session_id=conversation.id,
        ),
    )
    assert loaded.identity == ref.id
    assert loaded.file_asset_version == f"sha256:{checksum}"
    assert loaded.total_pages == 2

    try:
        attachment_vision._load_and_render_pages(
            InspectAttachmentPagesArgs(attachment_ref_id=ref.id),
            AgentToolContext(
                user_id=other.username,
                user_pk=other.id,
                session_id=conversation.id,
            ),
        )
    except attachment_vision._VisionBlocked as exc:
        assert exc.reason == "attachment_identity_or_scope"
    else:  # pragma: no cover - the owner check must fail closed
        raise AssertionError("cross-owner page vision unexpectedly succeeded")
