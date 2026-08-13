"""Application Service for the single canonical CareerProfile owner.

All functions flush but do not commit.  The UI and Agent call the same typed
commands.  Draft change-sets are deliberately excluded from profile reads and
only become canonical after an explicit, version-checked acceptance.
"""

from __future__ import annotations

import uuid

from pydantic import TypeAdapter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.career_profile import (
    CareerProfile,
    CareerProfileDirection,
    CareerProfileDraftChange,
)
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.resume import Resume
from app.models.user import User
from app.schemas.career_profile import (
    CareerProfileDirectionView,
    CareerProfileDraftInput,
    CareerProfileView,
    ConfirmationInput,
    ConfirmedPersonalFact,
    DirectionDraftChange,
    DirectionInput,
    FactDraftChange,
    PersonalFactInput,
)

_FACTS = TypeAdapter(list[ConfirmedPersonalFact])
_FACT_CHANGES = TypeAdapter(list[FactDraftChange])
_DIRECTION_CHANGES = TypeAdapter(list[DirectionDraftChange])


class CareerProfileError(ValueError):
    pass


class CareerProfileNotFoundError(CareerProfileError):
    pass


class CareerProfileOwnershipError(CareerProfileError):
    pass


class CareerProfileConflictError(CareerProfileError):
    pass


class CareerProfileSourceError(CareerProfileError):
    pass


def ensure_career_profile(db: Session, *, user_pk: int) -> CareerProfile:
    """Return the user's sole profile, creating its empty canonical root."""

    if db.get(User, user_pk) is None:
        raise CareerProfileOwnershipError(f"Unknown user {user_pk}")
    row = db.query(CareerProfile).filter(CareerProfile.user_id == user_pk).one_or_none()
    if row is not None:
        return row
    row = CareerProfile(user_id=user_pk, personal_facts_json=[], version=1)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        row = db.query(CareerProfile).filter(CareerProfile.user_id == user_pk).one()
    return row


def get_career_profile(db: Session, *, user_pk: int) -> CareerProfileView:
    """Read canonical confirmed facts and owned directions as one aggregate."""

    profile = (
        db.query(CareerProfile).filter(CareerProfile.user_id == user_pk).one_or_none()
    )
    if profile is None:
        raise CareerProfileNotFoundError(f"CareerProfile for user {user_pk} not found")
    return _profile_view(db, profile)


def upsert_personal_fact(
    db: Session,
    *,
    user_pk: int,
    expected_profile_version: int,
    fact: PersonalFactInput,
    confirmation: ConfirmationInput,
    fact_id: str | None = None,
) -> CareerProfileView:
    """Apply one explicit user-confirmed fact or correction."""

    profile = _owned_profile(db, user_pk)
    source_kind, source_id = _confirmed_source(
        db,
        user_pk=user_pk,
        confirmation=confirmation,
    )
    facts = _load_facts(profile)
    canonical_id = fact_id or _id("cpf")
    existing_idx = next(
        (index for index, item in enumerate(facts) if item.id == canonical_id),
        None,
    )
    if fact_id is not None and existing_idx is None:
        raise CareerProfileNotFoundError(f"Personal fact {fact_id} not found")
    canonical = ConfirmedPersonalFact(
        id=canonical_id,
        value=fact,
        confirmed_source_kind=source_kind,
        confirmed_source_id=source_id,
        confirmed_at=utc_now(),
    )
    if existing_idx is None:
        facts.append(canonical)
    else:
        facts[existing_idx] = canonical
    _replace_facts_cas(db, profile, expected_profile_version, facts)
    return _profile_view(db, profile)


def remove_personal_fact(
    db: Session,
    *,
    user_pk: int,
    expected_profile_version: int,
    fact_id: str,
    confirmation: ConfirmationInput,
) -> CareerProfileView:
    """Remove a confirmed fact after an explicit user edit/correction."""

    profile = _owned_profile(db, user_pk)
    _confirmed_source(db, user_pk=user_pk, confirmation=confirmation)
    facts = _load_facts(profile)
    remaining = [fact for fact in facts if fact.id != fact_id]
    if len(remaining) == len(facts):
        raise CareerProfileNotFoundError(f"Personal fact {fact_id} not found")
    _replace_facts_cas(db, profile, expected_profile_version, remaining)
    return _profile_view(db, profile)


def upsert_profile_direction(
    db: Session,
    *,
    user_pk: int,
    expected_profile_version: int,
    direction: DirectionInput,
    confirmation: ConfirmationInput,
    direction_id: str | None = None,
) -> CareerProfileView:
    """Create or revise an owned direction without a TargetDirection service."""

    profile = _owned_profile(db, user_pk)
    source_kind, source_id = _confirmed_source(
        db,
        user_pk=user_pk,
        confirmation=confirmation,
    )
    existing = None
    if direction_id is not None:
        existing = _owned_direction(db, profile.id, direction_id)
    with db.begin_nested():
        _bump_profile_cas(db, profile, expected_profile_version)
        now = utc_now()
        row = existing or CareerProfileDirection(
            id=direction_id or _id("cpd"),
            career_profile_id=profile.id,
            created_at=now,
        )
        _apply_direction(
            row,
            direction,
            source_kind=source_kind,
            source_id=source_id,
            confirmed_at=now,
        )
        db.add(row)
        db.flush()
    return _profile_view(db, profile)


def set_profile_direction_lifecycle(
    db: Session,
    *,
    user_pk: int,
    expected_profile_version: int,
    direction_id: str,
    lifecycle: str,
    confirmation: ConfirmationInput,
) -> CareerProfileView:
    """Change direction lifecycle independently of its priority."""

    if lifecycle not in {"exploring", "active", "paused", "archived"}:
        raise CareerProfileError(f"Unsupported direction lifecycle: {lifecycle}")
    profile = _owned_profile(db, user_pk)
    row = _owned_direction(db, profile.id, direction_id)
    source_kind, source_id = _confirmed_source(
        db,
        user_pk=user_pk,
        confirmation=confirmation,
    )
    _bump_profile_cas(db, profile, expected_profile_version)
    now = utc_now()
    row.lifecycle = lifecycle
    row.confirmed_source_kind = source_kind
    row.confirmed_source_id = source_id
    row.confirmed_at = now
    row.updated_at = now
    db.add(row)
    db.flush()
    return _profile_view(db, profile)


def create_profile_draft_change(
    db: Session,
    *,
    user_pk: int,
    draft: CareerProfileDraftInput,
) -> CareerProfileDraftChange:
    """Persist a reviewable non-canonical change-set from a real source."""

    profile = _owned_profile(db, user_pk)
    _require_draft_source(
        db,
        user_pk=user_pk,
        source_kind=draft.source_kind,
        source_id=draft.source_id,
    )
    row = CareerProfileDraftChange(
        career_profile_id=profile.id,
        source_kind=draft.source_kind,
        source_id=draft.source_id,
        base_profile_version=profile.version,
        proposed_facts_json=[
            item.model_dump(mode="json") for item in draft.proposed_facts
        ],
        proposed_directions_json=[
            item.model_dump(mode="json") for item in draft.proposed_directions
        ],
        status="pending",
        version=1,
    )
    db.add(row)
    db.flush()
    return row


def list_profile_draft_changes(
    db: Session,
    *,
    user_pk: int,
    include_resolved: bool = False,
) -> list[CareerProfileDraftChange]:
    """Return reviewable proposals owned by the user's canonical profile."""

    profile = _owned_profile(db, user_pk)
    query = db.query(CareerProfileDraftChange).filter(
        CareerProfileDraftChange.career_profile_id == profile.id
    )
    if not include_resolved:
        query = query.filter(CareerProfileDraftChange.status == "pending")
    return query.order_by(CareerProfileDraftChange.created_at.desc()).all()


def accept_profile_draft_change(
    db: Session,
    *,
    user_pk: int,
    draft_id: str,
    expected_draft_version: int,
    expected_profile_version: int,
) -> CareerProfileView:
    """Atomically merge a still-current draft into canonical Profile state."""

    profile, draft = _owned_draft(db, user_pk=user_pk, draft_id=draft_id)
    if draft.status != "pending" or draft.version != expected_draft_version:
        raise CareerProfileConflictError(
            f"Draft {draft_id} is {draft.status}/version={draft.version}"
        )
    if (
        profile.version != expected_profile_version
        or draft.base_profile_version != expected_profile_version
    ):
        raise CareerProfileConflictError(
            "Profile changed after this draft was produced; review it again"
        )
    _require_draft_source(
        db,
        user_pk=user_pk,
        source_kind=draft.source_kind,
        source_id=draft.source_id,
    )

    fact_changes = _FACT_CHANGES.validate_python(draft.proposed_facts_json or [])
    direction_changes = _DIRECTION_CHANGES.validate_python(
        draft.proposed_directions_json or []
    )
    facts = _apply_fact_changes(
        _load_facts(profile),
        fact_changes,
        draft_id=draft.id,
    )
    directions = {
        row.id: row
        for row in db.query(CareerProfileDirection)
        .filter(CareerProfileDirection.career_profile_id == profile.id)
        .all()
    }
    _validate_direction_targets(direction_changes, directions)
    with db.begin_nested():
        _replace_facts_cas(db, profile, expected_profile_version, facts)

        now = utc_now()
        for change in direction_changes:
            if change.operation == "archive":
                row = directions[change.target_direction_id]
                row.lifecycle = "archived"
                row.confirmed_source_kind = "draft_acceptance"
                row.confirmed_source_id = draft.id
                row.confirmed_at = now
                row.updated_at = now
                db.add(row)
                continue
            row = (
                directions[change.target_direction_id]
                if change.target_direction_id is not None
                else CareerProfileDirection(
                    id=_id("cpd"),
                    career_profile_id=profile.id,
                    created_at=now,
                )
            )
            _apply_direction(
                row,
                change.direction,
                source_kind="draft_acceptance",
                source_id=draft.id,
                confirmed_at=now,
            )
            db.add(row)

        changed = (
            db.query(CareerProfileDraftChange)
            .filter(
                CareerProfileDraftChange.id == draft.id,
                CareerProfileDraftChange.status == "pending",
                CareerProfileDraftChange.version == expected_draft_version,
            )
            .update(
                {
                    CareerProfileDraftChange.status: "accepted",
                    CareerProfileDraftChange.version: (
                        CareerProfileDraftChange.version + 1
                    ),
                    CareerProfileDraftChange.resolved_at: now,
                },
                synchronize_session=False,
            )
        )
        if changed != 1:
            raise CareerProfileConflictError(f"Draft {draft.id} changed concurrently")
        db.flush()
    return _profile_view(db, profile)


def reject_profile_draft_change(
    db: Session,
    *,
    user_pk: int,
    draft_id: str,
    expected_draft_version: int,
    resolution_note: str | None = None,
) -> CareerProfileDraftChange:
    """Reject a draft without changing canonical profile state."""

    _profile, draft = _owned_draft(db, user_pk=user_pk, draft_id=draft_id)
    now = utc_now()
    changed = (
        db.query(CareerProfileDraftChange)
        .filter(
            CareerProfileDraftChange.id == draft.id,
            CareerProfileDraftChange.status == "pending",
            CareerProfileDraftChange.version == expected_draft_version,
        )
        .update(
            {
                CareerProfileDraftChange.status: "rejected",
                CareerProfileDraftChange.resolution_note: (
                    resolution_note.strip() if resolution_note else None
                ),
                CareerProfileDraftChange.version: CareerProfileDraftChange.version + 1,
                CareerProfileDraftChange.resolved_at: now,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise CareerProfileConflictError(f"Draft {draft.id} changed concurrently")
    db.flush()
    return (
        db.query(CareerProfileDraftChange)
        .populate_existing()
        .filter(CareerProfileDraftChange.id == draft.id)
        .one()
    )


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _owned_profile(db: Session, user_pk: int) -> CareerProfile:
    row = db.query(CareerProfile).filter(CareerProfile.user_id == user_pk).one_or_none()
    if row is None:
        raise CareerProfileNotFoundError(f"CareerProfile for user {user_pk} not found")
    return row


def _owned_direction(
    db: Session, profile_id: str, direction_id: str
) -> CareerProfileDirection:
    row = (
        db.query(CareerProfileDirection)
        .filter(
            CareerProfileDirection.id == direction_id,
            CareerProfileDirection.career_profile_id == profile_id,
        )
        .one_or_none()
    )
    if row is None:
        raise CareerProfileNotFoundError(f"Profile direction {direction_id} not found")
    return row


def _owned_draft(
    db: Session, *, user_pk: int, draft_id: str
) -> tuple[CareerProfile, CareerProfileDraftChange]:
    row = (
        db.query(CareerProfile, CareerProfileDraftChange)
        .join(
            CareerProfileDraftChange,
            CareerProfileDraftChange.career_profile_id == CareerProfile.id,
        )
        .filter(CareerProfileDraftChange.id == draft_id)
        .one_or_none()
    )
    if row is None:
        raise CareerProfileNotFoundError(f"Profile draft {draft_id} not found")
    profile, draft = row
    if profile.user_id != user_pk:
        raise CareerProfileOwnershipError(
            f"User {user_pk} does not own draft {draft_id}"
        )
    return profile, draft


def _confirmed_source(
    db: Session,
    *,
    user_pk: int,
    confirmation: ConfirmationInput,
) -> tuple[str, str | None]:
    if confirmation.kind == "user_edit":
        return "user_edit", None
    message_id = confirmation.source_message_id
    owned = (
        db.query(ConversationMessage.id)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .filter(ConversationMessage.id == message_id, Conversation.user_id == user_pk)
        .scalar()
    )
    if owned is None:
        raise CareerProfileSourceError(f"Conversation message {message_id} not found")
    return "conversation_message", str(message_id)


def _require_draft_source(
    db: Session,
    *,
    user_pk: int,
    source_kind: str,
    source_id: str,
) -> None:
    if source_kind == "resume":
        exists = (
            db.query(Resume.id)
            .filter(Resume.id == source_id, Resume.user_id == user_pk)
            .scalar()
        )
    elif source_kind == "conversation_message":
        try:
            message_id = int(source_id)
        except ValueError as exc:
            raise CareerProfileSourceError("Invalid conversation message id") from exc
        exists = (
            db.query(ConversationMessage.id)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .filter(
                ConversationMessage.id == message_id,
                Conversation.user_id == user_pk,
            )
            .scalar()
        )
    elif source_kind == "model_inference":
        exists = (
            db.query(ConversationTurn.id)
            .filter(
                ConversationTurn.id == source_id,
                ConversationTurn.user_id == user_pk,
            )
            .scalar()
        )
    else:  # Pydantic and the DB CHECK also guard this path.
        raise CareerProfileSourceError(f"Unsupported draft source: {source_kind}")
    if exists is None:
        raise CareerProfileSourceError(
            f"Owned {source_kind} source {source_id} does not exist"
        )


def _load_facts(profile: CareerProfile) -> list[ConfirmedPersonalFact]:
    return _FACTS.validate_python(profile.personal_facts_json or [])


def _replace_facts_cas(
    db: Session,
    profile: CareerProfile,
    expected_version: int,
    facts: list[ConfirmedPersonalFact],
) -> None:
    now = utc_now()
    changed = (
        db.query(CareerProfile)
        .filter(
            CareerProfile.id == profile.id,
            CareerProfile.version == expected_version,
        )
        .update(
            {
                CareerProfile.personal_facts_json: [
                    fact.model_dump(mode="json") for fact in facts
                ],
                CareerProfile.version: CareerProfile.version + 1,
                CareerProfile.updated_at: now,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise CareerProfileConflictError(
            f"CareerProfile version is no longer {expected_version}"
        )
    db.flush()


def _bump_profile_cas(
    db: Session, profile: CareerProfile, expected_version: int
) -> None:
    now = utc_now()
    changed = (
        db.query(CareerProfile)
        .filter(
            CareerProfile.id == profile.id,
            CareerProfile.version == expected_version,
        )
        .update(
            {
                CareerProfile.version: CareerProfile.version + 1,
                CareerProfile.updated_at: now,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise CareerProfileConflictError(
            f"CareerProfile version is no longer {expected_version}"
        )
    db.flush()


def _apply_fact_changes(
    facts: list[ConfirmedPersonalFact],
    changes: list[FactDraftChange],
    *,
    draft_id: str,
) -> list[ConfirmedPersonalFact]:
    by_id = {fact.id: fact for fact in facts}
    now = utc_now()
    for change in changes:
        target = change.target_fact_id
        if change.operation == "remove":
            if target not in by_id:
                raise CareerProfileNotFoundError(f"Personal fact {target} not found")
            del by_id[target]
            continue
        if target is not None and target not in by_id:
            raise CareerProfileNotFoundError(f"Personal fact {target} not found")
        canonical_id = target or _id("cpf")
        by_id[canonical_id] = ConfirmedPersonalFact(
            id=canonical_id,
            value=change.fact,
            confirmed_source_kind="draft_acceptance",
            confirmed_source_id=draft_id,
            confirmed_at=now,
        )
    return list(by_id.values())


def _validate_direction_targets(
    changes: list[DirectionDraftChange],
    directions: dict[str, CareerProfileDirection],
) -> None:
    for change in changes:
        if (
            change.target_direction_id is not None
            and change.target_direction_id not in directions
        ):
            raise CareerProfileNotFoundError(
                f"Profile direction {change.target_direction_id} not found"
            )


def _apply_direction(
    row: CareerProfileDirection,
    value: DirectionInput,
    *,
    source_kind: str,
    source_id: str | None,
    confirmed_at,
) -> None:
    row.label = value.label.strip()
    row.criteria_json = value.criteria.model_dump(mode="json")
    row.lifecycle = value.lifecycle
    row.priority = value.priority
    row.confirmed_source_kind = source_kind
    row.confirmed_source_id = source_id
    row.confirmed_at = confirmed_at
    row.updated_at = confirmed_at


def _profile_view(db: Session, profile: CareerProfile) -> CareerProfileView:
    profile = (
        db.query(CareerProfile)
        .populate_existing()
        .filter(CareerProfile.id == profile.id)
        .one()
    )
    directions = (
        db.query(CareerProfileDirection)
        .filter(CareerProfileDirection.career_profile_id == profile.id)
        .order_by(
            CareerProfileDirection.priority.desc(),
            CareerProfileDirection.created_at.asc(),
        )
        .all()
    )
    return CareerProfileView(
        id=profile.id,
        user_id=profile.user_id,
        personal_facts=_load_facts(profile),
        directions=[
            CareerProfileDirectionView.model_validate(row) for row in directions
        ],
        version=profile.version,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


__all__ = [
    "CareerProfileConflictError",
    "CareerProfileError",
    "CareerProfileNotFoundError",
    "CareerProfileOwnershipError",
    "CareerProfileSourceError",
    "accept_profile_draft_change",
    "create_profile_draft_change",
    "ensure_career_profile",
    "get_career_profile",
    "list_profile_draft_changes",
    "reject_profile_draft_change",
    "remove_personal_fact",
    "set_profile_direction_lifecycle",
    "upsert_personal_fact",
    "upsert_profile_direction",
]
