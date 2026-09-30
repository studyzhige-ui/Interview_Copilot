"""Bounded resource fences retained after a Conversation is deleted.

This is deliberately scoped to Conversation deletion receipts.  It is not a
second resource registry: the receipt only preserves the canonical identities
already frozen on an unresolved mutating Tool call.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation_deletion_receipt import ConversationDeletionReceipt

MAX_RECEIPT_RESOURCE_IDENTITIES = 32
MAX_RECEIPT_RESOURCE_IDENTITY_LENGTH = 255


def normalize_receipt_resource_identities(value: object) -> list[str]:
    """Return the bounded canonical ``type:value`` identities receipt may keep."""

    if not isinstance(value, (list, tuple)):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        raw = item.strip()
        if len(raw) > MAX_RECEIPT_RESOURCE_IDENTITY_LENGTH or ":" not in raw:
            continue
        resource_type, resource_value = raw.split(":", 1)
        canonical = f"{resource_type.strip()}:{resource_value.strip()}"
        if canonical == ":" or canonical.startswith(":") or canonical.endswith(":"):
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        normalized.append(canonical)
        if len(normalized) == MAX_RECEIPT_RESOURCE_IDENTITIES:
            break
    return normalized


def find_unresolved_conversation_deletion_resource_receipts(
    db: Session,
    *,
    user_id: Any,
    resource_identities: object,
    lock: bool = False,
    now: datetime | None = None,
) -> list[ConversationDeletionReceipt]:
    """Find same-user, unexpired, unreconciled tombstones overlapping resources.

    ``lock=True`` acquires row locks where supported.  A dispatch caller should
    keep that transaction open through admission so settlement cannot remove the
    fence between overlap detection and the dispatch decision.
    """

    requested = set(normalize_receipt_resource_identities(resource_identities))
    if not requested:
        return []

    current_time = now or datetime.now(timezone.utc)
    statement = (
        select(ConversationDeletionReceipt)
        .where(
            ConversationDeletionReceipt.user_id == user_id,
            ConversationDeletionReceipt.resolved_at.is_(None),
            ConversationDeletionReceipt.retain_until > current_time,
        )
        .order_by(ConversationDeletionReceipt.created_at.asc())
    )
    if lock:
        statement = statement.with_for_update()

    matches: list[ConversationDeletionReceipt] = []
    for receipt in db.scalars(statement):
        retained = set(
            normalize_receipt_resource_identities(receipt.resource_identities_json)
        )
        if requested.intersection(retained):
            matches.append(receipt)
    return matches


def has_unresolved_conversation_deletion_resource_conflict(
    db: Session,
    *,
    user_id: Any,
    resource_identities: object,
    lock: bool = True,
) -> bool:
    """Return whether deleted-Conversation work still fences a requested resource."""

    return bool(
        find_unresolved_conversation_deletion_resource_receipts(
            db,
            user_id=user_id,
            resource_identities=resource_identities,
            lock=lock,
        )
    )


def receipt_resource_identities_for_call(call: Any) -> list[str]:
    """Project resources only for unresolved calls with possible side effects."""

    raw_effect = getattr(call, "effect", "unknown") or "unknown"
    raw_status = getattr(call, "status", "unknown") or "unknown"
    effect = str(getattr(raw_effect, "value", raw_effect)).strip().lower()
    status = str(getattr(raw_status, "value", raw_status)).strip().lower()
    if effect == "read" or status not in {"running", "unknown"}:
        return []
    return normalize_receipt_resource_identities(
        getattr(call, "resource_identities_json", None)
    )
