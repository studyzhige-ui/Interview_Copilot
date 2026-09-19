"""Memory projection invalidation shared by lifecycle and consolidation."""

from app.db.types import utc_now
from app.models.user import User
from app.models.memory_pipeline import MemoryWorkspace, MemoryExtraction
from app.models.long_term_memory import LongTermAgentMemory


def _workspace(db, user_id: int) -> MemoryWorkspace:
    # Serializes first insertion as well as all control-plane mutations.
    db.query(User).filter(User.id == user_id).with_for_update().one()
    row = db.get(MemoryWorkspace, user_id)
    if row is None:
        row = MemoryWorkspace(user_id=user_id)
        db.add(row)
        db.flush()
    return row


def invalidate_workspace(db, user_id: int) -> None:
    row = _workspace(db, user_id)
    row.lease_token = None
    row.lease_until = None
    row.input_hash = ""
    row.index_json = []
    row.status = "pending"
    row.retry_at = None
    row.updated_at = utc_now()


def suppress_sources(
    db, user_id: int, turn_ids: set[str], *, status: str = "suppressed"
) -> None:
    """Erasure invalidates EVERY dependent projection before a later rebuild."""
    invalidate_workspace(db, user_id)
    for row in (
        db.query(MemoryExtraction)
        .filter(
            MemoryExtraction.user_id == user_id, MemoryExtraction.turn_id.in_(turn_ids)
        )
        .all()
    ):
        row.status = status
        row.summary = ""
        row.candidates_json = []
        row.lease_token = None
        row.lease_until = None
    for row in (
        db.query(LongTermAgentMemory)
        .filter(LongTermAgentMemory.user_id == user_id)
        .all()
    ):
        if any(e.get("turn_id") in turn_ids for e in row.evidence_json or []):
            row.evidence_json = []
            row.index_text = ""
            row.content = ""
            row.applicability = ""
            row.tags_json = []
            if row.status == "active":
                row.status = "invalidated"
                row.status_reason = "source_changed"
                row.invalidated_at = utc_now()
                row.version += 1
    db.flush()
