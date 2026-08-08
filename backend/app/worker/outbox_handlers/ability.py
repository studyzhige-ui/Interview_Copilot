"""Worker handlers for the Milvus ability-state index.

``memory_ability_state_service`` enqueues these in the SAME transaction as the
Postgres write; the outbox worker drains them, applying the (eventually-
consistent) Milvus index update with retry/backoff. Keeping Milvus out of the
business transaction means a Milvus outage delays the index, never blocks the
memory write.

Imported by the worker's drain task so the handlers are registered before any
job runs.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob
from app.services.memory import ability_index
from app.services.outbox import register_handler


def _handle_upsert(db: Session, job: OutboxJob) -> None:
    p = job.payload_json or {}
    state_id = p.get("state_id")
    user_id = p.get("user_id")
    if not state_id or not user_id:
        raise ValueError(f"upsert_memory_ability_index: bad payload {p}")
    if job.aggregate_id and job.aggregate_id != state_id:
        raise ValueError("ability-index aggregate id does not match payload")
    if int(user_id) != job.user_id:
        raise PermissionError("ability-index job owner does not match payload owner")
    ability_index.upsert_ability(
        state_id,
        user_id=user_id,
        search_text=p.get("search_text", ""),
        topic=p.get("topic", ""),
        skill_type=p.get("skill_type", ""),
        mastery_level=p.get("mastery_level", ""),
        summary=p.get("summary"),
    )


def _handle_delete(db: Session, job: OutboxJob) -> None:
    p = job.payload_json or {}
    state_id = p.get("state_id")
    user_id = p.get("user_id")
    if not state_id or not user_id:
        raise ValueError(f"delete_memory_ability_index: bad payload {p}")
    if job.aggregate_id and job.aggregate_id != state_id:
        raise ValueError("ability-index aggregate id does not match payload")
    if int(user_id) != job.user_id:
        raise PermissionError("ability-index job owner does not match payload owner")
    ability_index.delete_ability(state_id)


register_handler("upsert_memory_ability_index", _handle_upsert)
register_handler("delete_memory_ability_index", _handle_delete)
