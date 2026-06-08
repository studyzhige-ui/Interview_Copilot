"""Outbox handlers for the Milvus ability-state index (MEMORY-V3).

``memory_ability_state_service`` enqueues these in the SAME transaction as the
Postgres write; the outbox worker drains them, applying the (eventually-
consistent) Milvus index update with retry/backoff. Keeping Milvus out of the
business transaction means a Milvus outage delays the index, never blocks the
memory write.

Imported by the worker's drain task so the handlers are registered before any
job runs.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob
from app.services.memory import ability_index
from app.services.uploads.outbox_service import register_handler

logger = logging.getLogger(__name__)


def _handle_upsert(db: Session, job: OutboxJob) -> None:
    p = json.loads(job.payload_json) if job.payload_json else {}
    state_id = p.get("state_id")
    user_id = p.get("user_id")
    if not state_id or not user_id:
        # Malformed payload — log loudly rather than index a ghost node that no
        # tenant-filtered search could ever reach.
        logger.warning("upsert_memory_ability_index: bad payload %s", p)
        return
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
    p = json.loads(job.payload_json) if job.payload_json else {}
    state_id = p.get("state_id")
    if state_id:
        ability_index.delete_ability(state_id)


register_handler("upsert_memory_ability_index", _handle_upsert)
register_handler("delete_memory_ability_index", _handle_delete)
