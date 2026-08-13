from __future__ import annotations

from app.models.ability_signal import AbilitySignal
from app.models.chat import Conversation, ConversationMessage
from app.models.memory_ability_state import MemoryAbilityState
from app.models.memory_audit_logs import MemoryAuditEntry
from app.models.memory_document import MemoryDocument
from app.models.user import User
from app.services.legacy_memory_migration import migrate_legacy_memory


def _seed(db_session):
    user = User(username="legacy-migration-user", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    message = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role="User",
        content="复盘我的系统设计表现",
    )
    db_session.add(message)
    db_session.flush()
    db_session.add_all(
        [
            MemoryDocument(
                user_id=user.id,
                doc_type="user_profile",
                body="# background\n混合事实、目标和偏好",
            ),
            MemoryAbilityState(
                id="mas_safe",
                user_id=user.id,
                topic="系统设计表达",
                skill_type="system_design",
                mastery_level="improving",
                ability_score=0.42,
                score_version="legacy-v1",
                summary="能识别核心组件，但取舍解释不够清楚。",
                evidence_refs_json=[
                    {"type": "conversation_message", "id": str(message.id)}
                ],
            ),
            MemoryAuditEntry(
                id="aud_forgotten",
                user_id=user.id,
                change_type="user_delete",
                before_body="content the user forgot",
                after_body="content the user forgot",
            ),
            MemoryAbilityState(
                id="mas_no_score",
                user_id=user.id,
                topic="行为面试",
                skill_type="behavioral",
                mastery_level="strong",
                ability_score=None,
                summary="只有旧标签，没有可复核分数。",
                evidence_refs_json=[
                    {"type": "conversation_message", "id": str(message.id)}
                ],
            ),
        ]
    )
    db_session.commit()
    return user


def test_legacy_migration_is_conservative_and_idempotent(db_session):
    user = _seed(db_session)

    dry_run = migrate_legacy_memory(db_session, apply=False)
    assert dry_run["counts"] == {
        "quarantined": 2,
        "eligible": 1,
        "purge_required": 1,
    }
    assert db_session.query(AbilitySignal).count() == 0

    applied = migrate_legacy_memory(db_session, apply=True)
    assert applied["counts"] == {
        "quarantined": 2,
        "migrated": 1,
        "purged": 1,
    }
    signal = db_session.query(AbilitySignal).one()
    assert signal.user_id == user.id
    assert signal.topic == "系统设计表达"
    assert signal.confidence == 0.25
    assert signal.rubric_version == "legacy-memory:mas_safe"
    forgotten = db_session.get(MemoryAuditEntry, "aud_forgotten")
    assert forgotten.before_body is None
    assert forgotten.after_body is None

    repeated = migrate_legacy_memory(db_session, apply=True)
    assert repeated["counts"] == {
        "quarantined": 2,
        "already_migrated": 1,
        "already_purged": 1,
    }
    assert db_session.query(AbilitySignal).count() == 1
