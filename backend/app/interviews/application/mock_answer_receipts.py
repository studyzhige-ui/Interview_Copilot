"""Durable answer-intent identity, sharing the existing record/lease transaction.

Callers authorize the record before reading. New claims serialize on the record
row; no timeout or repeated request ID can dispatch another model call. An
explicit new user intent may retry a saved answer after the old lease releases.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from app.db.types import utc_now
from app.models.mock_answer_submission import MockAnswerSubmission
from app.schemas.chat import MockAnswerReceipt, MockAnswerRequest, MockAnswerResp

MAX_RECORD_SUBMISSIONS = 1000
# Same conservative recovery window as the live question lease; expiry affects
# the read projection only and NEVER changes unknown into permission to retry.
ANSWER_CLAIM_TTL_SECONDS = 600


class AnswerRequestConflict(ValueError):
    """An existing intent ID was reused for different input."""


class AnswerRequestUnresolved(ValueError):
    """Read the receipt; generating again requires an explicit new intent."""


def fingerprint(command: MockAnswerRequest) -> str:
    value = {"schema_version": 1, **command.model_dump(exclude={"request_id"})}
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def read_receipt(db, record_id: str, request_id: str):
    row = (
        db.query(MockAnswerSubmission)
        .filter_by(record_id=record_id, request_id=request_id)
        .populate_existing()
        .one_or_none()
    )
    if row is None:
        return None
    status = row.status
    if status == "in_progress" and row.created_at < utc_now() - timedelta(
        seconds=ANSWER_CLAIM_TTL_SECONDS
    ):
        status = "unknown"
    return MockAnswerReceipt(
        request_id=row.request_id,
        question_message_id=row.question_message_id,
        status=status,
        response=MockAnswerResp.model_validate(row.response_json)
        if status == "completed"
        else None,
    )


def replay(db, record_id: str, command: MockAnswerRequest):
    row = (
        db.query(MockAnswerSubmission)
        .filter_by(record_id=record_id, request_id=command.request_id)
        .populate_existing()
        .one_or_none()
    )
    if row is None:
        return None
    if row.command_sha256 != fingerprint(command):
        raise AnswerRequestConflict("answer_request_content_conflict")
    if row.status != "completed":
        raise AnswerRequestUnresolved("answer_request_result_unconfirmed")
    return MockAnswerResp.model_validate(row.response_json)


def start(db, record_id: str, command: MockAnswerRequest, generation: int):
    if (
        db.query(MockAnswerSubmission).filter_by(record_id=record_id).count()
        >= MAX_RECORD_SUBMISSIONS
    ):
        raise AnswerRequestConflict("answer_request_capacity")
    db.query(MockAnswerSubmission).filter_by(
        record_id=record_id,
        question_message_id=command.question_message_id,
        status="in_progress",
    ).update(
        {
            MockAnswerSubmission.status: "unknown",
            MockAnswerSubmission.updated_at: utc_now(),
        },
        synchronize_session=False,
    )
    db.add(
        MockAnswerSubmission(
            record_id=record_id,
            request_id=command.request_id,
            question_message_id=command.question_message_id,
            command_sha256=fingerprint(command),
            claim_generation=generation,
            status="in_progress",
        )
    )
    db.flush()


def complete(
    db, record_id: str, request_id: str, generation: int, response: MockAnswerResp
):
    changed = (
        db.query(MockAnswerSubmission)
        .filter_by(
            record_id=record_id,
            request_id=request_id,
            claim_generation=generation,
            status="in_progress",
        )
        .update(
            {
                MockAnswerSubmission.status: "completed",
                MockAnswerSubmission.response_json: response.model_dump(),
                MockAnswerSubmission.updated_at: utc_now(),
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise AnswerRequestUnresolved("answer_request_publication_fenced")


def mark_unknown(db, record_id: str, request_id: str, generation: int):
    # A response-loss after a successful COMMIT must not erase its valid receipt.
    db.query(MockAnswerSubmission).filter_by(
        record_id=record_id,
        request_id=request_id,
        claim_generation=generation,
        status="in_progress",
    ).update(
        {
            MockAnswerSubmission.status: "unknown",
            MockAnswerSubmission.updated_at: utc_now(),
        },
        synchronize_session=False,
    )
