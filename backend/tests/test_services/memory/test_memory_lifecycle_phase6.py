"""Phase 6 memory-lifecycle behaviors: mastery discipline (MEM-4),
tombstone via dispatch (MEM-2), dreaming archive op (MEM-9), strict parse
(MEM-7), lock raise mode (MEM-6), optimistic doc edits (MEM-3), tiered
truncation (MEM-8), doc compaction (MEM-5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.memory import (
    _dispatch,
    memory_ability_state_service as abil,
    memory_document_service as docs,
)
from app.services.memory._extraction_common import parse_json_patches_ex
from app.services.memory._user_memory_lock import LockNotAcquired


@pytest.fixture(autouse=True)
def _seed_user(db_session, monkeypatch):
    from app.models.user import User

    db_session.add(User(username="alice", hashed_password="x"))
    db_session.commit()

    # Route every service-owned SessionLocal at the test DB.
    import app.services.memory._db_helpers as dbh_mod
    import app.services.memory._memory_audit as audit_mod
    import app.services.memory.memory_ability_state_service as abil_mod
    import app.services.memory.memory_document_service as docs_mod
    from tests.conftest import patch_session_locals

    patch_session_locals(
        monkeypatch, db_session, abil_mod, docs_mod, audit_mod, dbh_mod
    )


# ── MEM-4: mastery discipline ────────────────────────────────────────────


def test_realtime_cannot_mint_strong_without_evidence():
    row = abil.upsert(
        "alice",
        topic="K8s",
        skill_type="knowledge_topic",
        mastery_level="strong",
        summary="自称精通",
        change_type="patch_realtime",
    )
    # New row via realtime: one step from nothing → weak; strong impossible.
    assert row.mastery_level == "weak"


def test_realtime_steps_up_one_level_at_a_time():
    abil.upsert(
        "alice",
        topic="Redis",
        skill_type="knowledge_topic",
        mastery_level="weak",
        summary="s",
        change_type="patch_realtime",
    )
    row = abil.upsert(
        "alice",
        topic="Redis",
        skill_type="knowledge_topic",
        mastery_level="strong",
        summary="s",
        change_type="patch_realtime",
    )
    assert row.mastery_level == "improving"  # weak +1, not weak→strong


def test_realtime_strong_requires_evidence_even_from_stable():
    abil.upsert(
        "alice",
        topic="MQ",
        skill_type="knowledge_topic",
        mastery_level="stable",
        summary="s",
        change_type="patch_dreaming",
    )
    no_ev = abil.upsert(
        "alice",
        topic="MQ",
        skill_type="knowledge_topic",
        mastery_level="strong",
        summary="s",
        change_type="patch_realtime",
    )
    assert no_ev.mastery_level == "stable"
    with_ev = abil.upsert(
        "alice",
        topic="MQ",
        skill_type="knowledge_topic",
        mastery_level="strong",
        summary="s",
        change_type="patch_realtime",
        evidence_refs=[{"type": "qa", "id": "qa_1"}],
    )
    assert with_ev.mastery_level == "strong"


def test_downgrade_always_allowed():
    abil.upsert(
        "alice",
        topic="GC",
        skill_type="knowledge_topic",
        mastery_level="strong",
        summary="s",
        change_type="patch_dreaming",
    )
    row = abil.upsert(
        "alice",
        topic="GC",
        skill_type="knowledge_topic",
        mastery_level="weak",
        summary="忘光了",
        change_type="patch_realtime",
    )
    assert row.mastery_level == "weak"


# ── MEM-2/9: tombstone + archive op through dispatch ─────────────────────


def test_dispatch_archive_op_dreaming_only(db_session):
    abil.upsert(
        "alice",
        topic="旧栈",
        skill_type="knowledge_topic",
        mastery_level="stable",
        summary="s",
        change_type="patch_dreaming",
    )

    # Realtime may not archive.
    r = _dispatch.dispatch_memory_patches(
        user_id="alice",
        change_type="patch_realtime",
        patches=[
            {
                "target": "ability_state",
                "op": "archive",
                "topic": "旧栈",
                "skill_type": "knowledge_topic",
            }
        ],
    )
    assert r.dropped == 1
    assert len(abil.load_active("alice")) == 1

    # Dreaming may.
    r = _dispatch.dispatch_memory_patches(
        user_id="alice",
        change_type="patch_dreaming",
        patches=[
            {
                "target": "ability_state",
                "op": "archive",
                "topic": "旧栈",
                "skill_type": "knowledge_topic",
            }
        ],
    )
    assert r.applied == 1
    assert abil.load_active("alice") == []


def test_dreaming_blocked_by_user_tombstone():
    abil.upsert(
        "alice",
        topic="幻觉",
        skill_type="knowledge_topic",
        mastery_level="weak",
        summary="s",
        change_type="patch_realtime",
    )
    assert abil.archive("alice", topic="幻觉", skill_type="knowledge_topic") is True
    blocked = abil.upsert(
        "alice",
        topic="幻觉",
        skill_type="knowledge_topic",
        mastery_level="weak",
        summary="回魂",
        change_type="patch_dreaming",
    )
    assert blocked is None


# ── MEM-7: strict parse ──────────────────────────────────────────────────


def test_parse_ex_distinguishes_garbage_from_empty():
    assert parse_json_patches_ex("") == ([], True)
    assert parse_json_patches_ex("[]") == ([], True)
    assert parse_json_patches_ex('{"patches": []}') == ([], True)
    patches, ok = parse_json_patches_ex('[{"target": "ability_state"}]')
    assert ok and len(patches) == 1
    _, ok = parse_json_patches_ex("对不起，我无法输出 JSON。")
    assert ok is False


# ── MEM-6: lock raise mode ───────────────────────────────────────────────


def test_lock_raises_when_redis_down(monkeypatch):
    import app.db.redis as redis_mod
    from app.services.memory._user_memory_lock import user_memory_lock_sync

    class _Boom:
        def set(self, *a, **k):
            raise ConnectionError("redis down")

    monkeypatch.setattr(redis_mod, "sync_redis_client", _Boom())
    with pytest.raises(LockNotAcquired):
        with user_memory_lock_sync("alice", on_timeout="raise"):
            pass  # pragma: no cover

    # Degrade mode still yields through.
    with user_memory_lock_sync("alice"):
        pass


# ── MEM-3: optimistic doc edits ──────────────────────────────────────────


def test_stale_doc_edit_rejected():
    docs.upsert_user_edit("alice", "user_profile", "第一版")
    meta = docs.load_with_meta("alice", "user_profile")
    assert meta["body"] == "第一版" and meta["updated_at"]

    # Background write lands between the user's GET and PUT.
    docs.apply_patches(
        "alice",
        "user_profile",
        [{"op": "add", "new_line": "- 后台补充"}],
        change_type="patch_realtime",
    )
    with pytest.raises(docs.StaleDocumentEdit):
        docs.upsert_user_edit(
            "alice",
            "user_profile",
            "第二版（会抹掉后台行）",
            base_updated_at=meta["updated_at"],
        )
    # A fresh token passes; the returned token comes from the save
    # transaction itself (not a racy post-lock re-read).
    fresh = docs.load_with_meta("alice", "user_profile")
    saved = docs.upsert_user_edit(
        "alice",
        "user_profile",
        "第二版",
        base_updated_at=fresh["updated_at"],
    )
    assert saved["body"] == "第二版"
    assert saved["updated_at"]


# ── MEM-8: tiered truncation ─────────────────────────────────────────────


def test_context_cap_keeps_all_growth_states(monkeypatch):
    from app.services.memory import v3_context_loader as loader

    monkeypatch.setattr(loader, "_MAX_ABILITIES", 5)

    def _state(i, level, days_old=0):
        return SimpleNamespace(
            topic=f"t{i}",
            skill_type="knowledge_topic",
            mastery_level=level,
            summary="s",
            last_evidence_at=datetime.utcnow() - timedelta(days=days_old),
        )

    # 3 old weak + 4 fresh strong; flat updated_at-desc cut at 5 would keep
    # only 1 weak — tiered keeps all 3.
    states = [_state(i, "strong") for i in range(4)] + [
        _state(10 + i, "weak", days_old=90) for i in range(3)
    ]
    dicts = loader._ability_states_to_dicts(states)
    weak_topics = {d["topic"] for d in dicts if d["mastery_level"] == "weak"}
    assert weak_topics == {"t10", "t11", "t12"}
    assert len(dicts) == 5
    # Stale annotation present for the 90-day-old entries (MEM-1).
    assert all(
        d.get("stale_days", 0) >= 89 for d in dicts if d["mastery_level"] == "weak"
    )


# ── MEM-5: doc compaction ────────────────────────────────────────────────


def test_compact_skips_small_doc():
    docs.upsert_user_edit("alice", "user_profile", "短文档")
    assert docs.compact_if_oversized("alice", "user_profile") is False


def test_compact_rewrites_oversized_doc(monkeypatch):
    big = "\n".join(f"- 条目 {i}：一些内容" for i in range(150))
    docs.upsert_user_edit("alice", "user_profile", big)

    rewritten = "\n".join(f"- 合并条目 {i}" for i in range(30))

    class _LLM:
        async def acomplete(self, prompt):
            return SimpleNamespace(text=rewritten)

    monkeypatch.setattr(
        "app.core.llm_client_factory.get_llm_for_role",
        lambda role, user_id=None: _LLM(),
    )
    monkeypatch.setattr(
        "app.worker.tasks.run_async",
        lambda coro: __import__("asyncio").run(coro),
    )

    assert docs.compact_if_oversized("alice", "user_profile") is True
    assert docs.load("alice", "user_profile") == rewritten


def test_compact_rejects_suspiciously_small_rewrite(monkeypatch):
    big = "\n".join(f"- 条目 {i}：一些内容一些内容" for i in range(150))
    docs.upsert_user_edit("alice", "user_profile", big)

    class _LLM:
        async def acomplete(self, prompt):
            return SimpleNamespace(text="没了")

    monkeypatch.setattr(
        "app.core.llm_client_factory.get_llm_for_role",
        lambda role, user_id=None: _LLM(),
    )
    monkeypatch.setattr(
        "app.worker.tasks.run_async",
        lambda coro: __import__("asyncio").run(coro),
    )
    assert docs.compact_if_oversized("alice", "user_profile") is False
    assert docs.load("alice", "user_profile") == big


# ── MEM-7: the observability events actually fire ─────────────────────────


def _capture_metrics(monkeypatch):
    events: list[tuple[str, dict]] = []

    def _incr(event, *, value=1, **labels):
        events.append((event, labels))

    import app.services.memory._dispatch as dispatch_mod
    import app.services.memory.memory_ability_state_service as abil_mod

    monkeypatch.setattr(dispatch_mod._metrics, "incr", _incr)
    monkeypatch.setattr(abil_mod._metrics, "incr", _incr)
    return events


def test_metrics_emitted_for_clamp_drop_and_apply(monkeypatch):
    events = _capture_metrics(monkeypatch)

    # applied + clamped
    _dispatch.dispatch_memory_patches(
        user_id="alice",
        change_type="patch_realtime",
        patches=[
            {
                "target": "ability_state",
                "topic": "K8s",
                "skill_type": "knowledge_topic",
                "mastery_level": "strong",
                "summary": "自称精通",
            }
        ],
    )
    names = [e for e, _ in events]
    assert "memory.mastery_clamped" in names
    assert "memory.patch_applied" in names

    # invalid fields → single unified drop event with a reason label
    events.clear()
    _dispatch.dispatch_memory_patches(
        user_id="alice",
        change_type="patch_realtime",
        patches=[
            {
                "target": "ability_state",
                "topic": "",
                "skill_type": "nope",
                "mastery_level": "weak",
            }
        ],
    )
    drops = [
        (event, labels) for event, labels in events if event == "memory.patch_dropped"
    ]
    assert drops and drops[0][1]["reason"] == "invalid_fields"
    assert not any(e == "memory.patch_dropped_total" for e, _ in events)


def test_tombstone_drop_emits_reason(monkeypatch):
    events = _capture_metrics(monkeypatch)
    abil.upsert(
        "alice",
        topic="鬼影",
        skill_type="knowledge_topic",
        mastery_level="weak",
        summary="s",
        change_type="patch_realtime",
    )
    assert abil.archive("alice", topic="鬼影", skill_type="knowledge_topic") is True
    events.clear()
    blocked = abil.upsert(
        "alice",
        topic="鬼影",
        skill_type="knowledge_topic",
        mastery_level="weak",
        summary="回魂",
        change_type="patch_realtime",
    )
    assert blocked is None
    assert ("memory.patch_dropped",)[0] in [e for e, _ in events]
    reasons = [
        labels.get("reason")
        for event, labels in events
        if event == "memory.patch_dropped"
    ]
    assert "tombstone" in reasons
