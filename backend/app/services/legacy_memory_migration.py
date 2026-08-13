"""Conservative, idempotent classification of the retired mixed Memory data.

This is an operational Stage 2 migration helper, not a runtime Recall path.
Mixed Markdown documents are quarantined for manual review. A legacy ability
row is promoted only when it has a numeric score, a non-empty explanation and
live references accepted by the canonical AbilitySignal service.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.ability_signal import AbilitySignal
from app.models.memory_ability_state import MemoryAbilityState
from app.models.memory_audit_logs import MemoryAuditEntry
from app.models.memory_document import MemoryDocument
from app.schemas.ability_signal import (
    AbilityScopeInput,
    AbilitySignalCreateInput,
    AbilitySourceRefInput,
)
from app.services.ability_signal_service import (
    AbilitySignalError,
    create_ability_signal,
)

_SOURCE_KINDS = frozenset(
    {
        "interview_record",
        "interview_qa",
        "conversation_message",
        "agent_tool_call",
        "process_event",
        "artifact_version",
    }
)


def migrate_legacy_memory(
    db: Session,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Classify every legacy row and optionally create safe AbilitySignals.

    The deterministic ``rubric_version`` is the idempotency seam. The caller
    owns commit/rollback, making dry-run and deployment batching explicit.
    """

    items: list[dict[str, Any]] = []
    documents = db.query(MemoryDocument).order_by(MemoryDocument.id.asc()).all()
    for document in documents:
        items.append(
            {
                "source_kind": "memory_document",
                "source_id": document.id,
                "user_id": document.user_id,
                "classification": "quarantined",
                "reason": (
                    "mixed_markdown_requires_user_review; it must not be copied "
                    "into CareerProfile, CopilotPreference, or Long-term Memory"
                ),
            }
        )

    states = db.query(MemoryAbilityState).order_by(MemoryAbilityState.id.asc()).all()
    for state in states:
        rubric_version = f"legacy-memory:{state.id}"
        existing = (
            db.query(AbilitySignal)
            .filter(
                AbilitySignal.user_id == state.user_id,
                AbilitySignal.rubric_version == rubric_version,
            )
            .one_or_none()
        )
        if existing is not None:
            items.append(
                _state_item(
                    state,
                    "already_migrated",
                    target_id=existing.id,
                    reason="canonical AbilitySignal already exists",
                )
            )
            continue

        reason = _ineligible_reason(state)
        sources = _legacy_sources(state.evidence_refs_json)
        if reason is None and not sources:
            reason = "no supported real-owner source references"
        if reason is not None:
            items.append(_state_item(state, "quarantined", reason=reason))
            continue
        if not apply:
            items.append(
                _state_item(
                    state,
                    "eligible",
                    reason="dry-run; canonical source validation occurs on apply",
                )
            )
            continue

        try:
            view = create_ability_signal(
                db,
                user_pk=state.user_id,
                assessment=AbilitySignalCreateInput(
                    topic=state.topic.strip(),
                    signal_type=state.skill_type,
                    level=state.mastery_level,
                    score=state.ability_score,
                    summary=(state.summary or "").strip(),
                    # The old store did not record calibrated confidence. Keep
                    # this visibly low instead of inventing certainty.
                    confidence=0.25,
                    limitations=(
                        "Migrated from the retired ability store. Legacy rows did "
                        "not record calibrated confidence; re-evaluate from new "
                        "observations before high-impact use."
                    ),
                    scope=AbilityScopeInput(kind="general"),
                    formed_at=(
                        state.last_evidence_at or state.updated_at or state.created_at
                    ),
                    rubric_version=rubric_version,
                    sources=sources,
                ),
            )
        except AbilitySignalError as exc:
            items.append(
                _state_item(
                    state,
                    "quarantined",
                    reason=f"canonical source validation failed: {exc}",
                )
            )
        else:
            items.append(
                _state_item(
                    state,
                    "migrated",
                    target_id=view.id,
                    reason="created low-confidence canonical AbilitySignal",
                )
            )

    forgotten_audits = (
        db.query(MemoryAuditEntry)
        .filter(MemoryAuditEntry.change_type == "user_delete")
        .order_by(MemoryAuditEntry.id.asc())
        .all()
    )
    for audit in forgotten_audits:
        has_body = bool(audit.before_body or audit.after_body)
        if apply and has_body:
            audit.before_body = None
            audit.after_body = None
        items.append(
            {
                "source_kind": "memory_audit_log",
                "source_id": audit.id,
                "user_id": audit.user_id,
                "classification": (
                    "purged"
                    if apply and has_body
                    else "already_purged"
                    if not has_body
                    else "purge_required"
                ),
                "reason": "forgotten content must not survive in audit snapshots",
            }
        )

    counts: dict[str, int] = {}
    for item in items:
        key = str(item["classification"])
        counts[key] = counts.get(key, 0) + 1
    return {"applied": apply, "counts": counts, "items": items}


def _legacy_sources(value: Any) -> list[AbilitySourceRefInput]:
    if not isinstance(value, list):
        return []
    result: list[AbilitySourceRefInput] = []
    seen: set[tuple[str, str]] = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or raw.get("type") or "").strip()
        source_id = str(raw.get("source_id") or raw.get("id") or "").strip()
        identity = (kind, source_id)
        if kind not in _SOURCE_KINDS or not source_id or identity in seen:
            continue
        seen.add(identity)
        result.append(AbilitySourceRefInput(kind=kind, source_id=source_id))
    return result


def _ineligible_reason(state: MemoryAbilityState) -> str | None:
    if state.archived_at is not None:
        return "legacy row is archived"
    if not (state.topic or "").strip():
        return "missing topic"
    if not (state.summary or "").strip():
        return "missing explanatory summary"
    if state.ability_score is None:
        return "missing numeric score; mastery label must not become a fake score"
    return None


def _state_item(
    state: MemoryAbilityState,
    classification: str,
    *,
    reason: str,
    target_id: str | None = None,
) -> dict[str, Any]:
    return {
        "source_kind": "memory_ability_state",
        "source_id": state.id,
        "user_id": state.user_id,
        "classification": classification,
        "target_kind": "ability_signal" if target_id else None,
        "target_id": target_id,
        "reason": reason,
    }


__all__ = ["migrate_legacy_memory"]
