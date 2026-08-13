"""Application Service for explicit personalization guidance.

The three lifetimes retain their real owners. This module only performs their
deterministic read/update contract and produces one resolved prompt projection;
it does not introduce a shared Guidance entity or inheritance registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.chat import Conversation, ConversationMessage
from app.models.copilot_preference import CopilotPreference
from app.models.interview_record import InterviewRecord
from app.schemas.personalization import (
    CopilotPreferenceUpdate,
    CopilotPreferenceView,
    ScopedGuidanceUpdate,
    ScopedGuidanceView,
)


class PersonalizationError(ValueError):
    """Base deterministic command error."""


class PersonalizationNotFoundError(PersonalizationError):
    """The requested real owner does not exist for this user."""


class PersonalizationConflictError(PersonalizationError):
    """An optimistic version or source invariant failed."""


@dataclass(frozen=True)
class GuidanceProjection:
    global_instructions: tuple[str, ...]
    debrief_guidance: str | None
    conversation_guidance: str | None

    def render(self) -> str:
        sections: list[str] = []
        if self.global_instructions:
            sections.append(
                "[Global CopilotPreference]\n"
                + "\n".join(f"- {item}" for item in self.global_instructions)
            )
        if self.debrief_guidance:
            sections.append(f"[Current Debrief Guidance]\n{self.debrief_guidance}")
        if self.conversation_guidance:
            sections.append(
                f"[Current Conversation Guidance]\n{self.conversation_guidance}"
            )
        if not sections:
            return ""
        return (
            "These are explicit collaboration instructions, ordered broad to "
            "specific. More specific/current user input wins. They never grant "
            "Tool permission or change product facts.\n\n" + "\n\n".join(sections)
        )


def get_copilot_preference(db: Session, *, user_pk: int) -> CopilotPreferenceView:
    row = (
        db.query(CopilotPreference)
        .filter(CopilotPreference.user_id == user_pk)
        .one_or_none()
    )
    if row is None:
        return CopilotPreferenceView(
            id=None,
            instructions=[],
            version=0,
            updated_at=None,
        )
    return _preference_view(row)


def replace_copilot_preference(
    db: Session,
    *,
    user_pk: int,
    command: CopilotPreferenceUpdate,
) -> CopilotPreferenceView:
    row = (
        db.query(CopilotPreference)
        .filter(CopilotPreference.user_id == user_pk)
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        if command.expected_version != 0:
            raise PersonalizationConflictError("CopilotPreference version changed")
        row = CopilotPreference(
            user_id=user_pk,
            instructions_json=list(command.instructions),
            version=1,
        )
        db.add(row)
    else:
        if row.version != command.expected_version:
            raise PersonalizationConflictError("CopilotPreference version changed")
        if list(row.instructions_json or []) == list(command.instructions):
            return _preference_view(row)
        row.instructions_json = list(command.instructions)
        row.version += 1
        row.updated_at = utc_now()
    db.flush()
    return _preference_view(row)


def get_conversation_guidance(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
) -> ScopedGuidanceView:
    row = _owned_conversation(db, user_pk, conversation_id)
    return _conversation_view(row)


def update_conversation_guidance(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    command: ScopedGuidanceUpdate,
) -> ScopedGuidanceView:
    row = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise PersonalizationNotFoundError("Conversation not found")
    if int(row.guidance_version or 0) != command.expected_version:
        raise PersonalizationConflictError("Conversation guidance version changed")
    if command.guidance is not None:
        if command.source_message_id is None:
            raise PersonalizationConflictError(
                "Conversation guidance requires its original user message"
            )
        source = db.get(ConversationMessage, int(command.source_message_id))
        if (
            source is None
            or source.conversation_id != conversation_id
            or source.role.lower() != "user"
        ):
            raise PersonalizationConflictError(
                "Conversation guidance source is not an owned user message"
            )
    elif command.source_message_id is not None:
        raise PersonalizationConflictError("Cleared guidance cannot keep a source")
    row.guidance_text = command.guidance
    row.guidance_source_message_id = command.source_message_id
    row.guidance_version = int(row.guidance_version or 0) + 1
    row.updated_at = utc_now()
    db.flush()
    return _conversation_view(row)


def get_debrief_guidance(
    db: Session,
    *,
    user_pk: int,
    interview_record_id: str,
) -> ScopedGuidanceView:
    row = _owned_interview(db, user_pk, interview_record_id)
    return _interview_view(row)


def update_debrief_guidance(
    db: Session,
    *,
    user_pk: int,
    interview_record_id: str,
    command: ScopedGuidanceUpdate,
) -> ScopedGuidanceView:
    row = (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.id == interview_record_id,
            InterviewRecord.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise PersonalizationNotFoundError("InterviewRecord not found")
    if int(row.debrief_guidance_version or 0) != command.expected_version:
        raise PersonalizationConflictError("Debrief guidance version changed")
    if command.source_message_id is not None:
        source = db.get(ConversationMessage, int(command.source_message_id))
        owner = db.get(Conversation, source.conversation_id) if source else None
        if (
            source is None
            or source.role.lower() != "user"
            or owner is None
            or owner.user_id != user_pk
            or owner.subject_type != "interview_record"
            or owner.subject_id != interview_record_id
        ):
            raise PersonalizationConflictError(
                "Debrief guidance source is outside this InterviewRecord"
            )
    row.debrief_guidance_text = command.guidance
    row.debrief_guidance_source_message_id = command.source_message_id
    row.debrief_guidance_version = int(row.debrief_guidance_version or 0) + 1
    row.updated_at = utc_now()
    db.flush()
    return _interview_view(row)


def resolve_guidance_projection(*, conversation_id: str, user_pk: int) -> str:
    """Read broad-to-specific guidance from its three canonical owners."""
    with SessionLocal() as db:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.user_id == user_pk,
            )
            .one_or_none()
        )
        if conversation is None:
            return ""
        preference = (
            db.query(CopilotPreference)
            .filter(CopilotPreference.user_id == user_pk)
            .one_or_none()
        )
        debrief: InterviewRecord | None = None
        if conversation.subject_type == "interview_record" and conversation.subject_id:
            debrief = (
                db.query(InterviewRecord)
                .filter(
                    InterviewRecord.id == conversation.subject_id,
                    InterviewRecord.user_id == user_pk,
                )
                .one_or_none()
            )
        return GuidanceProjection(
            global_instructions=tuple(preference.instructions_json or [])
            if preference
            else (),
            debrief_guidance=debrief.debrief_guidance_text if debrief else None,
            conversation_guidance=conversation.guidance_text,
        ).render()


def _owned_conversation(db: Session, user_pk: int, identity: str) -> Conversation:
    row = (
        db.query(Conversation)
        .filter(Conversation.id == identity, Conversation.user_id == user_pk)
        .one_or_none()
    )
    if row is None:
        raise PersonalizationNotFoundError("Conversation not found")
    return row


def _owned_interview(db: Session, user_pk: int, identity: str) -> InterviewRecord:
    row = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == identity, InterviewRecord.user_id == user_pk)
        .one_or_none()
    )
    if row is None:
        raise PersonalizationNotFoundError("InterviewRecord not found")
    return row


def _preference_view(row: CopilotPreference) -> CopilotPreferenceView:
    return CopilotPreferenceView(
        id=row.id,
        instructions=list(row.instructions_json or []),
        version=row.version,
        updated_at=row.updated_at,
    )


def _conversation_view(row: Conversation) -> ScopedGuidanceView:
    return ScopedGuidanceView(
        owner_id=row.id,
        guidance=row.guidance_text,
        source_message_id=row.guidance_source_message_id,
        version=int(row.guidance_version or 0),
        updated_at=row.updated_at,
    )


def _interview_view(row: InterviewRecord) -> ScopedGuidanceView:
    return ScopedGuidanceView(
        owner_id=row.id,
        guidance=row.debrief_guidance_text,
        source_message_id=row.debrief_guidance_source_message_id,
        version=int(row.debrief_guidance_version or 0),
        updated_at=row.updated_at,
    )


__all__ = [
    "GuidanceProjection",
    "PersonalizationConflictError",
    "PersonalizationError",
    "PersonalizationNotFoundError",
    "get_copilot_preference",
    "get_conversation_guidance",
    "get_debrief_guidance",
    "replace_copilot_preference",
    "resolve_guidance_projection",
    "update_conversation_guidance",
    "update_debrief_guidance",
]
