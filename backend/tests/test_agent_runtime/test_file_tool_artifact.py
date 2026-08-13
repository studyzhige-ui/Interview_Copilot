from __future__ import annotations

from app.agent_runtime.tool_registry import AgentToolContext
from app.agent_runtime.tools.file_tool import WriteFileArgs, _write_file_sync
from app.db import database as database_module
from app.models.artifact import Artifact, ArtifactVersion
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.user import User
from app.services.uploads import file_asset_service
from tests.conftest import NoCloseSession


def test_write_file_creates_one_idempotent_artifact_export(
    db_session,
    monkeypatch,
):
    user = User(username="artifact-export-user", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(id="artifact-export-conv", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationTurn(
        id="artifact-export-turn",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="请把报告保存成文件",
    )
    db_session.add(turn)
    db_session.commit()

    monkeypatch.setattr(
        database_module,
        "SessionLocal",
        lambda: NoCloseSession(db_session),
    )
    monkeypatch.setattr(
        file_asset_service,
        "upload_file_to_owned_key",
        lambda _file, object_key, **_kwargs: f"local://{object_key}",
    )
    context = AgentToolContext(
        user_id=user.username,
        user_pk=user.id,
        session_id=conversation.id,
        turn_id=turn.id,
        tool_call_id="call-export-1",
    )
    args = WriteFileArgs(filename="analysis.md", content="# Analysis\nUseful text")

    first = _write_file_sync(args, context)
    retry = _write_file_sync(args, context)

    assert retry == first
    assert first["external_action_performed"] is False
    assert first["artifact_id"]
    assert first["artifact_version_id"]
    assert first["file_asset_id"]
    assert db_session.query(Artifact).count() == 1
    assert db_session.query(ArtifactVersion).count() == 1
    assert db_session.query(FileAsset).count() == 1
    artifact = db_session.get(Artifact, first["artifact_id"])
    version = db_session.get(ArtifactVersion, first["artifact_version_id"])
    assert artifact.kind == "agent_export"
    assert version.content_text == args.content
    assert version.file_asset_id == first["file_asset_id"]
    assert version.source_turn_id == turn.id
