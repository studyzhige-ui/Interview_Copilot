"""Shared read/write retention policy; reads do not depend on worker health."""

from datetime import timedelta

from sqlalchemy import func, or_

from app.core.config import settings
from app.db.types import utc_now
from app.models.long_term_memory import LongTermAgentMemory, LongTermAgentMemorySource
from app.models.memory_pipeline import MemoryExtraction


def expired_source_ids(db, user_id: int) -> set[str]:
    # Use the source generation time, not consolidation time: rewriting an
    # unused memory must not restart its retention window. Exposure is not use.
    usage = (
        db.query(
            LongTermAgentMemorySource.source_turn_identity.label("turn_id"),
            func.max(LongTermAgentMemory.last_used_at).label("last_used_at"),
        )
        .join(LongTermAgentMemory)
        .filter(LongTermAgentMemory.user_id == user_id)
        .group_by(LongTermAgentMemorySource.source_turn_identity)
        .subquery()
    )
    cutoff = utc_now() - timedelta(days=settings.AGENT_MEMORY_MAX_UNUSED_DAYS)
    return {
        turn_id
        for (turn_id,) in db.query(MemoryExtraction.turn_id)
        .outerjoin(usage, usage.c.turn_id == MemoryExtraction.turn_id)
        .filter(
            MemoryExtraction.user_id == user_id,
            MemoryExtraction.status == "succeeded",
            MemoryExtraction.generated_at < cutoff,
            or_(usage.c.last_used_at.is_(None), usage.c.last_used_at < cutoff),
        )
    }


def unavailable_memory_ids(db, user_id: int) -> set[str]:
    """Reject an entire projection if any of its sources is no longer usable."""
    expired = expired_source_ids(db, user_id)
    memories = (
        db.query(LongTermAgentMemory.id, LongTermAgentMemory.evidence_json)
        .filter(
            LongTermAgentMemory.user_id == user_id,
            LongTermAgentMemory.origin == "pipeline",
            LongTermAgentMemory.status == "active",
        )
        .all()
    )
    # Provenance edges are append-only deletion tombstones. Eligibility uses
    # this version's evidence, not old edges left by a previous consolidation.
    sources = {
        identity: {e.get("turn_id") for e in evidence or []}
        for identity, evidence in memories
    }
    identities = set().union(*sources.values()) if sources else set()
    available = {
        turn_id
        for (turn_id,) in db.query(MemoryExtraction.turn_id).filter(
            MemoryExtraction.user_id == user_id,
            MemoryExtraction.status == "succeeded",
            MemoryExtraction.turn_id.in_(identities),
        )
    } - expired
    return {
        identity
        for identity, required in sources.items()
        if not required or not required.issubset(available)
    }
