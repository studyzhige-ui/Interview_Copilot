"""Two-phase durable memory pipeline. No model call holds a database lock.

Leases fence late workers; input fingerprints fence source/control changes.
Only publication writes canonical memory. Source payloads are disposable and
never replace exact History. User mutations revoke publication leases.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, and_

from app.core.config import settings
from app.core.tokens import token_count
from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.agent_execution import AgentToolCall
from app.models.long_term_memory import (
    AgentMemorySetting,
    LongTermAgentMemory,
    LongTermAgentMemorySource,
)
from app.models.memory_pipeline import (
    MemoryExtraction,
    MemoryWorkspace,
    MemoryReadReceipt,
)
from app.models.user import User
from app.services import agent_memory_service as memory
from app.services.memory_prompts import EXTRACT, CONSOLIDATE, SELECT
from app.services.memory_retention import expired_source_ids


class ExtractedCandidate(memory._Candidate):
    evidence_seq: int = Field(ge=1)
    evidence_kind: Literal["user", "tool"] = "user"
    tool_call_id: str | None = None
    evidence_status: Literal[
        "user_reported_result", "verified_tool_result", "unverified"
    ]


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=1200)
    candidates: list[ExtractedCandidate] = Field(max_length=3)


class ConsolidatedMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_key: str = Field(min_length=3, max_length=120)
    content: str = Field(min_length=1, max_length=800)
    applicability: str = Field(min_length=1, max_length=400)
    tags: list[str] = Field(max_length=12)
    valence: str
    confidence: float = Field(ge=0, le=1)
    index_text: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(min_length=1, max_length=120)


class ConsolidationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memories: list[ConsolidatedMemory] = Field(max_length=40)


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


async def model_json(instruction: str, data: dict) -> dict:
    from app.core.llm_client_factory import get_internal_llm

    response = await asyncio.wait_for(
        get_internal_llm("router" if instruction == SELECT else "worker").acomplete(
            instruction
            + "\nUNTRUSTED INPUT JSON:\n"
            + json.dumps(data, ensure_ascii=False),
            response_format={"type": "json_object"},
        ),
        timeout=settings.AGENT_MEMORY_MODEL_TIMEOUT_SECONDS,
    )
    return json.loads(str(response.text or ""))


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


def _source(db, turn_id: str):
    source = memory.eligible_source_for_turn(db, turn_id=turn_id)
    if source is None:
        return None
    turn = db.get(ConversationTurn, turn_id)
    messages = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == source.conversation_id,
            ConversationMessage.seq <= turn.assistant_message_seq,
        )
        .order_by(ConversationMessage.seq.desc())
        .limit(12)
        .all()
    )
    transcript = []
    for message in reversed(messages):
        text = memory.redact_tool_text(message.content or "")[:4000]
        # Sensitive context does not enter the model or persisted artifacts.
        if memory._PERSONAL_DATA.search(text):
            text = "[REDACTED_SENSITIVE_MESSAGE]"
        transcript.append({"seq": message.seq, "role": message.role, "text": text})
    tools = []
    for call in (
        db.query(AgentToolCall)
        .filter(
            AgentToolCall.turn_id == turn_id,
            AgentToolCall.user_id == source.user_pk,
            AgentToolCall.status.in_(("completed", "failed")),
        )
        .order_by(AgentToolCall.id)
        .limit(12)
        .all()
    ):
        result = memory.redact_tool_text(
            json.dumps(call.result_json, ensure_ascii=False)
        )[:2000]
        if memory._PERSONAL_DATA.search(result):
            result = "[REDACTED_SENSITIVE_RESULT]"
        tools.append(
            {
                "id": call.call_id,
                "name": call.tool_name,
                "status": call.status,
                "result": result,
            }
        )
    data = {"target_seq": turn.user_message_seq, "messages": transcript, "tools": tools}
    return source, data, fingerprint(data)


def validate_extraction(output: ExtractionOutput, data: dict) -> list[dict]:
    memory._validate_memory_text(output.summary, "")
    target = next(m for m in data["messages"] if m["seq"] == data["target_seq"])
    candidates = []
    for candidate in output.candidates:
        if candidate.evidence_status == "unverified":
            continue
        if candidate.evidence_seq != data["target_seq"]:
            raise ValueError("invalid_evidence_sequence")
        if candidate.evidence_kind == "tool":
            if candidate.evidence_status != "verified_tool_result":
                raise ValueError("inconsistent_evidence_status")
            tool = next(
                (t for t in data.get("tools", []) if t["id"] == candidate.tool_call_id),
                None,
            )
            if tool is None or "[REDACTED" in tool["result"]:
                raise ValueError("invalid_tool_evidence")
            evidence = tool["result"]
        else:
            if candidate.evidence_status != "user_reported_result":
                raise ValueError("inconsistent_evidence_status")
            evidence = target["text"]
        if (
            candidate.support_quote not in evidence
            or "[REDACTED" in candidate.support_quote
        ):
            raise ValueError("unsupported_quote")
        memory._validate_memory_text(candidate.content, candidate.applicability)
        memory._validate_memory_text(candidate.support_quote, " ".join(candidate.tags))
        if any(len(tag) > 40 for tag in candidate.tags):
            raise ValueError("invalid_tag")
        # Self-reported numeric confidence is uncalibrated, not an admission gate.
        # Exact source support is checked here; cross-source value is judged in Phase 2.
        candidates.append(candidate.model_dump())
    return candidates


def discover_turns(limit: int | None = None) -> list[str]:
    if not settings.AGENT_MEMORY_PRODUCER_ENABLED:
        return []
    now = utc_now()
    with SessionLocal() as db:
        rows = (
            db.query(ConversationTurn.id)
            .outerjoin(
                MemoryExtraction,
                MemoryExtraction.turn_id == ConversationTurn.id,
            )
            .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .outerjoin(
                AgentMemorySetting,
                AgentMemorySetting.user_id == ConversationTurn.user_id,
            )
            .filter(
                Conversation.active_turn_id.is_(None),
                or_(
                    Conversation.memory_contribution_override.is_(True),
                    and_(
                        Conversation.memory_contribution_override.is_(None),
                        AgentMemorySetting.contribution_enabled.is_(True),
                    ),
                ),
                ConversationTurn.status == "completed",
                ConversationTurn.completed_at
                <= now - timedelta(seconds=settings.AGENT_MEMORY_IDLE_SECONDS),
                ConversationTurn.completed_at
                >= now - timedelta(days=settings.AGENT_MEMORY_MAX_AGE_DAYS),
                or_(
                    MemoryExtraction.turn_id.is_(None),
                    (MemoryExtraction.status == "failed")
                    & (MemoryExtraction.retry_at <= now),
                    (MemoryExtraction.status == "running")
                    & (MemoryExtraction.lease_until <= now),
                ),
            )
            .order_by(ConversationTurn.completed_at.desc())
            .limit(limit or settings.AGENT_MEMORY_SCAN_LIMIT)
            .all()
        )
        return [row.id for row in rows if _source(db, row.id) is not None]


async def extract_turn(turn_id: str) -> int | None:
    """Return owner for successful/already processed input; None for deferred work."""
    token = str(uuid.uuid4())
    with SessionLocal() as db:
        turn = (
            db.query(ConversationTurn)
            .filter(
                ConversationTurn.id == turn_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if turn is None:
            return None
        source_data = _source(db, turn_id)
        if source_data is None:
            return None
        source, data, source_hash = source_data
        row = db.get(MemoryExtraction, turn_id)
        if row is not None:
            if row.status in {"succeeded", "no_output"}:
                return row.user_id
            if row.status in {"suppressed", "forgotten"}:
                return None
            if row.lease_until and row.lease_until > utc_now():
                return None
            if row.retry_at and row.retry_at > utc_now():
                return None
        else:
            # Existing memory source edges are content-free suppression markers.
            if memory._source_turn_was_processed(
                db, user_pk=source.user_pk, turn_id=turn_id
            ):
                return None
            row = MemoryExtraction(
                turn_id=turn_id,
                user_id=source.user_pk,
                conversation_id=source.conversation_id,
                source_hash=source_hash,
                observed_at=source.observed_at,
            )
            db.add(row)
            db.flush()
        row.status = "running"
        row.source_hash = source_hash
        row.lease_token = token
        row.lease_until = utc_now() + timedelta(
            seconds=max(
                settings.AGENT_MEMORY_LEASE_SECONDS,
                settings.AGENT_MEMORY_MODEL_TIMEOUT_SECONDS + 30,
            )
        )
        row.attempts += 1
        row.error_code = None
        db.commit()
    try:
        output = ExtractionOutput.model_validate(await model_json(EXTRACT, data))
        candidates = validate_extraction(output, data)
        with SessionLocal() as db:
            row = (
                db.query(MemoryExtraction)
                .filter(MemoryExtraction.turn_id == turn_id)
                .with_for_update()
                .one()
            )
            if row.lease_token != token:
                return None
            fresh = _source(db, turn_id)
            if fresh is None or fresh[2] != source_hash:
                row.status = "failed"
                row.error_code = "source_changed"
                row.retry_at = utc_now() + timedelta(seconds=60)
                row.lease_token = None
                row.lease_until = None
                db.commit()
                return None
            row.summary = output.summary if candidates else ""
            row.candidates_json = candidates
            row.status = "succeeded" if candidates else "no_output"
            row.generated_at = utc_now()
            row.retry_at = None
            row.lease_token = None
            row.lease_until = None
            db.commit()
        return source.user_pk
    except Exception as exc:
        _fail(MemoryExtraction, turn_id, token, exc)
        raise


def _fail(model, identity, token, exc):
    with SessionLocal() as db:
        row = (
            db.query(model)
            .filter(
                model.turn_id == identity
                if model is MemoryExtraction
                else model.user_id == identity
            )
            .with_for_update()
            .one_or_none()
        )
        if row is not None and row.lease_token == token:
            row.status = "failed"
            # Never persist provider error bodies (may contain credentials/data).
            row.error_code = type(exc).__name__[:80]
            row.retry_at = utc_now() + timedelta(
                seconds=min(3600, 30 * 2 ** min(row.attempts, 7))
            )
            row.lease_token = None
            row.lease_until = None
            db.commit()


def _inputs(db, user_id: int):
    rows = (
        db.query(MemoryExtraction)
        .filter(
            MemoryExtraction.user_id == user_id,
            MemoryExtraction.status == "succeeded",
        )
        .order_by(MemoryExtraction.observed_at.desc())
        .all()
    )
    memories = (
        db.query(LongTermAgentMemory)
        .filter(LongTermAgentMemory.user_id == user_id)
        .all()
    )
    edges = (
        db.query(LongTermAgentMemorySource)
        .join(
            LongTermAgentMemory,
            LongTermAgentMemory.id == LongTermAgentMemorySource.memory_id,
        )
        .filter(LongTermAgentMemory.user_id == user_id)
        .all()
    )
    feedback_rows = (
        db.query(MemoryReadReceipt.memory_id, MemoryReadReceipt.feedback)
        .join(
            LongTermAgentMemory,
            and_(
                LongTermAgentMemory.id == MemoryReadReceipt.memory_id,
                LongTermAgentMemory.version == MemoryReadReceipt.memory_version,
            ),
        )
        .filter(
            MemoryReadReceipt.user_id == user_id,
            LongTermAgentMemory.user_id == user_id,
            MemoryReadReceipt.feedback.is_not(None),
        )
        .all()
    )
    feedback_by_memory = {}
    for receipt in feedback_rows:
        counts = feedback_by_memory.setdefault(
            receipt.memory_id, {"helpful": 0, "unhelpful": 0}
        )
        counts[receipt.feedback] += 1
    blocked_turns = set()
    for item in memories:
        if item.origin == "manual" or (
            item.status != "active"
            and item.status_reason
            not in {"reconsolidated", "source_changed", "unused_retention"}
        ):
            blocked_turns.update(
                s.source_turn_identity for s in edges if s.memory_id == item.id
            )
    now = utc_now()
    selected = []
    for row in rows:
        if row.turn_id in blocked_turns:
            continue
        conversation = db.get(Conversation, row.conversation_id)
        linked = [
            m
            for m in memories
            if any(e.get("turn_id") == row.turn_id for e in m.evidence_json or [])
        ]
        if conversation is None or conversation.user_id != user_id:
            continue
        # Opt-out stops new formation; it must not silently erase existing memory.
        if not linked and not memory._effective_controls(db, conversation)[1]:
            continue
        used = max(
            [m.last_used_at for m in linked if m.last_used_at] + [row.generated_at]
        )
        if used < now - timedelta(days=settings.AGENT_MEMORY_MAX_UNUSED_DAYS):
            continue
        count = sum(m.usage_count for m in linked) + sum(
            2
            * (
                feedback_by_memory.get(m.id, {}).get("helpful", 0)
                - feedback_by_memory.get(m.id, {}).get("unhelpful", 0)
            )
            for m in linked
        )
        selected.append((count, used, row))
    selected.sort(key=lambda x: (x[0], x[1], x[2].turn_id), reverse=True)
    candidates = {}
    for _, _, row in selected[: settings.AGENT_MEMORY_MAX_INPUTS]:
        for number, value in enumerate(row.candidates_json):
            candidates[f"{row.turn_id}:{number}"] = {
                **value,
                "turn_id": row.turn_id,
                "conversation_id": row.conversation_id,
                "observed_at": row.observed_at.isoformat(),
                "summary": row.summary,
            }
    previous = [
        {
            "id": m.id,
            "semantic_key": m.semantic_key,
            "version": m.version,
            "status": m.status,
            "origin": m.origin,
            "reason": m.status_reason,
            "feedback": feedback_by_memory.get(m.id, {}),
            "content": m.content,
        }
        for m in sorted(
            (m for m in memories if m.status == "active"),
            key=lambda m: m.updated_at,
            reverse=True,
        )[:100]
    ]
    data = {
        "candidates": candidates,
        "previous": sorted(previous, key=lambda x: x["id"]),
    }
    # Preserve whole evidence records, never truncate JSON or source quotes.
    # Candidate insertion order is utility/recency order above.
    budget = max(2000, settings.AGENT_MEMORY_CONSOLIDATION_INPUT_TOKENS)
    while token_count(json.dumps(data, ensure_ascii=False)) > budget:
        if data["previous"]:
            data["previous"].pop()
        elif len(data["candidates"]) > 1:
            data["candidates"].popitem()
        else:
            raise ValueError("memory_input_exceeds_budget")
    return data, fingerprint(data)


async def consolidate_user(user_id: int) -> int:
    if not settings.AGENT_MEMORY_PRODUCER_ENABLED:
        return 0
    token = str(uuid.uuid4())
    with SessionLocal() as db:
        workspace = _workspace(db, user_id)
        if workspace.lease_until and workspace.lease_until > utc_now():
            return 0
        if workspace.retry_at and workspace.retry_at > utc_now():
            return 0
        _forget_expired(db, user_id)
        data, input_hash = _inputs(db, user_id)
        if workspace.input_hash == input_hash:
            workspace.updated_at = utc_now()
            db.commit()
            return 0
        workspace.status = "running"
        workspace.lease_token = token
        workspace.lease_until = utc_now() + timedelta(
            seconds=max(
                settings.AGENT_MEMORY_LEASE_SECONDS,
                settings.AGENT_MEMORY_MODEL_TIMEOUT_SECONDS + 30,
            )
        )
        workspace.attempts += 1
        db.commit()
    try:
        output = ConsolidationOutput.model_validate(
            await model_json(CONSOLIDATE, data)
            if data["candidates"]
            else {"memories": []}
        )
        _validate_consolidation(output, data)
        with SessionLocal() as db:
            workspace = _workspace(db, user_id)
            if workspace.lease_token != token:
                return 0
            _, current_hash = _inputs(db, user_id)
            if current_hash != input_hash:
                invalidate_workspace(db, user_id)
                db.commit()
                return 0
            changed = _publish(db, user_id, output, data)
            workspace.index_json = [
                {"id": m.id, "version": m.version, "text": m.index_text}
                for m in db.query(LongTermAgentMemory)
                .filter(
                    LongTermAgentMemory.user_id == user_id,
                    LongTermAgentMemory.status == "active",
                )
                .all()
            ]
            workspace.input_hash = _inputs(db, user_id)[1]
            workspace.revision += 1
            workspace.status = "succeeded"
            workspace.error_code = None
            workspace.retry_at = None
            workspace.lease_token = None
            workspace.lease_until = None
            workspace.updated_at = utc_now()
            db.commit()
            return changed
    except Exception as exc:
        _fail(MemoryWorkspace, user_id, token, exc)
        raise


def _validate_consolidation(output, data):
    seen = set()
    for item in output.memories:
        if item.semantic_key in seen or not memory._SEMANTIC_KEY.fullmatch(
            item.semantic_key
        ):
            raise ValueError("duplicate_or_invalid_key")
        seen.add(item.semantic_key)
        if item.valence not in {"effective", "ineffective", "mixed"}:
            raise ValueError("invalid_valence")
        if any(key not in data["candidates"] for key in item.evidence_ids):
            raise ValueError("unknown_evidence")
        evidence = [data["candidates"][key] for key in item.evidence_ids]
        if item.confidence > max(e["confidence"] for e in evidence):
            raise ValueError("inflated_confidence")
        if len({e["valence"] for e in evidence}) > 1 and item.valence != "mixed":
            raise ValueError("unresolved_conflict")
        memory._validate_memory_text(item.content, item.applicability)
        memory._validate_memory_text(item.index_text, " ".join(item.tags))
        if any(len(tag) > 40 for tag in item.tags):
            raise ValueError("invalid_tag")


def _publish(db, user_id, output, data):
    rows = {
        m.semantic_key: m
        for m in db.query(LongTermAgentMemory)
        .filter(LongTermAgentMemory.user_id == user_id)
        .with_for_update()
        .all()
    }
    kept = set()
    now = utc_now()
    for item in output.memories:
        row = rows.get(item.semantic_key)
        if row is not None and (
            row.origin != "pipeline"
            or row.status == "deleted"
            or (
                row.status == "invalidated"
                and row.status_reason
                not in {"reconsolidated", "source_changed", "unused_retention"}
            )
        ):
            continue
        evidence = [
            {"id": key, **data["candidates"][key]}
            for key in dict.fromkeys(item.evidence_ids)
        ]
        observed = [
            db.get(MemoryExtraction, e["turn_id"]).observed_at for e in evidence
        ]
        if row is None:
            row = LongTermAgentMemory(
                user_id=user_id,
                semantic_key=item.semantic_key,
                origin="pipeline",
                formed_at=min(observed),
            )
            db.add(row)
        else:
            row.version += 1
        row.content = item.content
        row.applicability = item.applicability
        row.tags_json = item.tags
        row.index_text = item.index_text
        row.evidence_json = evidence
        row.valence = item.valence
        row.confidence = item.confidence
        row.content_hash = memory._content_hash(item.content, item.applicability)
        row.status = "active"
        row.status_reason = None
        row.invalidated_at = None
        row.last_confirmed_at = max(observed)
        row.updated_at = now
        db.flush()
        kept.add(row.id)
        # Source identities are append-only suppression provenance, not snapshots.
        for e in evidence:
            exists = (
                db.query(LongTermAgentMemorySource.id)
                .filter(
                    LongTermAgentMemorySource.memory_id == row.id,
                    LongTermAgentMemorySource.source_turn_identity == e["turn_id"],
                )
                .first()
            )
            if exists is None:
                db.add(
                    LongTermAgentMemorySource(
                        memory_id=row.id,
                        turn_id=e["turn_id"],
                        source_turn_identity=e["turn_id"],
                        source_conversation_identity=e["conversation_id"],
                        support_quote_hash=fingerprint(e["support_quote"]),
                        observed_at=db.get(MemoryExtraction, e["turn_id"]).observed_at,
                    )
                )
    for row in rows.values():
        if row.origin == "pipeline" and row.status == "active" and row.id not in kept:
            row.status = "invalidated"
            row.status_reason = "reconsolidated"
            row.invalidated_at = now
            row.content = ""
            row.index_text = ""
            row.applicability = ""
            row.evidence_json = []
            row.tags_json = []
            row.version += 1
    db.flush()
    return len(kept)


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


def _forget_expired(db, user_id: int):
    expired = expired_source_ids(db, user_id)
    if expired:
        suppress_sources(db, user_id, set(expired), status="forgotten")


async def process_turn(turn_id: str) -> int:
    owner = await extract_turn(turn_id)
    return await consolidate_user(owner) if owner is not None else 0
