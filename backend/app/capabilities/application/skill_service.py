from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml
from sqlalchemy.orm import Session, object_session

from app.models.agent_task import AgentTask
from app.models.agent_task_skill import AgentTaskSkillBinding
from app.models.user_skill import UserSkill, UserSkillResource

_FRONTMATTER = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    content: str
    applicable_profiles: tuple[str, ...]
    required_tools: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    content_hash: str


_PROFILES = {"career", "debrief"}
_RESOURCE_KINDS = {"reference", "script", "template", "asset"}


def _string_list(metadata: dict[str, Any], key: str) -> tuple[str, ...]:
    value = metadata.get(key, [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Skill frontmatter {key} must be a list of strings")
    return tuple(dict.fromkeys(item.strip() for item in value if item.strip()))


def parse_skill(content: str) -> SkillDefinition:
    text = content.strip()
    match = _FRONTMATTER.match(text)
    if match is None:
        raise ValueError("Skill must start with YAML frontmatter enclosed by ---")
    metadata = yaml.safe_load(match.group(1)) or {}
    if not isinstance(metadata, dict):
        raise ValueError("Skill frontmatter must be a YAML object")
    name = str(metadata.get("name") or "").strip()
    description = str(metadata.get("description") or "").strip()
    if not _NAME.fullmatch(name):
        raise ValueError("Skill name must contain only letters, numbers, _ or -")
    if not description or len(description) > 500:
        raise ValueError("Skill description must contain 1-500 characters")
    if not text[match.end() :].strip():
        raise ValueError("Skill instructions are empty")
    profiles = _string_list(metadata, "profiles")
    if any(profile not in _PROFILES for profile in profiles):
        raise ValueError("Skill profiles may only contain career or debrief")
    required_tools = _string_list(metadata, "required-tools")
    allowed_tools = _string_list(metadata, "allowed-tools")
    return SkillDefinition(
        name=name,
        description=description,
        content=text,
        applicable_profiles=profiles,
        required_tools=required_tools,
        allowed_tools=allowed_tools,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def skill_payload(row: UserSkill, *, include_content: bool = True) -> dict:
    value = {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "revision": int(row.revision or 1),
        "content_hash": row.content_hash,
        "source": row.source,
        "applicable_profiles": list(row.applicable_profiles_json or []),
        "required_tools": list(row.required_tools_json or []),
        "allowed_tools": list(row.allowed_tools_json or []),
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_content:
        value["content"] = row.content
        value["resources"] = resource_manifest(row)
    return value


def resource_manifest(row: UserSkill) -> list[dict[str, Any]]:
    resources = (
        row.__dict__.get("_resource_manifest")
        if isinstance(row.__dict__.get("_resource_manifest"), list)
        else None
    )
    if resources is not None:
        return resources
    session = object_session(row)
    if session is None:
        return []
    return [
        {
            "path": item.path,
            "kind": item.kind,
            "content_hash": item.content_hash,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in (
            session.query(UserSkillResource)
            .filter(UserSkillResource.skill_id == row.id)
            .order_by(UserSkillResource.path)
            .all()
        )
    ]


def list_skills(
    db: Session,
    user_pk: int,
    *,
    enabled_only: bool = False,
    include_content: bool = True,
) -> list[dict]:
    query = db.query(UserSkill).filter(UserSkill.user_id == user_pk)
    if enabled_only:
        query = query.filter(UserSkill.enabled.is_(True))
    return [
        skill_payload(row, include_content=include_content)
        for row in query.order_by(UserSkill.name).all()
    ]


def get_skill(db: Session, user_pk: int, skill_id: int) -> UserSkill | None:
    return (
        db.query(UserSkill)
        .filter(
            UserSkill.id == skill_id,
            UserSkill.user_id == user_pk,
        )
        .one_or_none()
    )


def create_skill(db: Session, user_pk: int, content: str, enabled: bool) -> dict:
    definition = parse_skill(content)
    if (
        db.query(UserSkill.id)
        .filter(
            UserSkill.user_id == user_pk,
            UserSkill.name == definition.name,
        )
        .first()
    ):
        raise ValueError(f"Skill '{definition.name}' already exists")
    row = UserSkill(
        user_id=user_pk,
        name=definition.name,
        description=definition.description,
        content=definition.content,
        revision=1,
        content_hash=definition.content_hash,
        source="user",
        applicable_profiles_json=list(definition.applicable_profiles),
        required_tools_json=list(definition.required_tools),
        allowed_tools_json=list(definition.allowed_tools),
        enabled=enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return skill_payload(row)


def update_skill(
    db: Session,
    user_pk: int,
    skill_id: int,
    *,
    content: str | None,
    enabled: bool | None,
) -> dict | None:
    row = get_skill(db, user_pk, skill_id)
    if row is None:
        return None
    if content is not None:
        definition = parse_skill(content)
        duplicate = (
            db.query(UserSkill.id)
            .filter(
                UserSkill.user_id == user_pk,
                UserSkill.name == definition.name,
                UserSkill.id != skill_id,
            )
            .first()
        )
        if duplicate:
            raise ValueError(f"Skill '{definition.name}' already exists")
        row.name = definition.name
        row.description = definition.description
        row.content = definition.content
        row.revision = int(row.revision or 1) + 1
        row.content_hash = definition.content_hash
        row.applicable_profiles_json = list(definition.applicable_profiles)
        row.required_tools_json = list(definition.required_tools)
        row.allowed_tools_json = list(definition.allowed_tools)
    if enabled is not None:
        row.enabled = enabled
    db.commit()
    db.refresh(row)
    return skill_payload(row)


def delete_skill(db: Session, user_pk: int, skill_id: int) -> bool:
    row = get_skill(db, user_pk, skill_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def search(rows: list[dict], query: str, *, limit: int = 5) -> list[dict]:
    needle = query.strip().casefold()
    if not needle:
        return rows[:limit]

    def score(row: dict) -> tuple[int, str]:
        name = row["name"].casefold()
        description = row["description"].casefold()
        value = 100 if name == needle else 0
        value += 30 if needle in name else 0
        value += 10 if needle in description else 0
        value += sum(1 for term in needle.split() if term in f"{name} {description}")
        return value, name

    ranked = sorted(rows, key=score, reverse=True)
    return [row for row in ranked if score(row)[0] > 0][:limit]


def replace_resources(
    db: Session,
    *,
    user_pk: int,
    skill_id: int,
    resources: list[dict[str, Any]],
) -> dict | None:
    row = get_skill(db, user_pk, skill_id)
    if row is None:
        return None
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for resource in resources:
        path = str(resource.get("path") or "").replace("\\", "/").strip("/")
        pure = PurePosixPath(path)
        kind = str(resource.get("kind") or "").strip()
        content = str(resource.get("content") or "")
        if not path or pure.is_absolute() or ".." in pure.parts or len(path) > 255:
            raise ValueError("Skill resource path must be a safe relative path")
        if kind not in _RESOURCE_KINDS:
            raise ValueError("Unsupported Skill resource kind")
        if not content or len(content) > 500_000:
            raise ValueError("Skill resource content must contain 1-500000 characters")
        if path in seen:
            raise ValueError(f"Duplicate Skill resource path: {path}")
        seen.add(path)
        normalized.append({"path": path, "kind": kind, "content": content})

    db.query(UserSkillResource).filter(UserSkillResource.skill_id == row.id).delete()
    for resource in normalized:
        content = resource["content"]
        db.add(
            UserSkillResource(
                skill_id=row.id,
                path=resource["path"],
                kind=resource["kind"],
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
        )
    row.revision = int(row.revision or 1) + 1
    db.commit()
    db.refresh(row)
    return skill_payload(row)


def load_resource(
    db: Session,
    *,
    user_pk: int,
    skill_id: int,
    path: str,
) -> UserSkillResource | None:
    return (
        db.query(UserSkillResource)
        .join(UserSkill, UserSkill.id == UserSkillResource.skill_id)
        .filter(
            UserSkillResource.skill_id == skill_id,
            UserSkillResource.path == path,
            UserSkill.user_id == user_pk,
            UserSkill.enabled.is_(True),
        )
        .one_or_none()
    )


def list_resources(
    db: Session,
    *,
    user_pk: int,
    skill_id: int,
) -> list[dict[str, Any]] | None:
    row = get_skill(db, user_pk, skill_id)
    if row is None:
        return None
    return [
        {
            "path": item.path,
            "kind": item.kind,
            "content": item.content,
            "content_hash": item.content_hash,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in (
            db.query(UserSkillResource)
            .filter(UserSkillResource.skill_id == skill_id)
            .order_by(UserSkillResource.path)
            .all()
        )
    ]


def bind_skill_to_agent_task(
    db: Session,
    *,
    turn_id: str | None,
    user_pk: int,
    skill: UserSkill,
) -> None:
    if not turn_id:
        return
    task = db.query(AgentTask).filter(AgentTask.turn_id == turn_id).one_or_none()
    if task is None:
        return
    binding = (
        db.query(AgentTaskSkillBinding)
        .filter(
            AgentTaskSkillBinding.agent_task_id == task.id,
            AgentTaskSkillBinding.skill_name == skill.name,
        )
        .one_or_none()
    )
    if binding is None:
        binding = AgentTaskSkillBinding(
            agent_task_id=task.id,
            skill_id=skill.id,
            skill_name=skill.name,
            skill_source=skill.source,
            skill_revision=int(skill.revision or 1),
            content_hash=skill.content_hash,
        )
        db.add(binding)
    elif (
        binding.skill_revision != int(skill.revision or 1)
        or binding.content_hash != skill.content_hash
    ):
        raise ValueError("skill_revision_changed_for_active_task")
    db.flush()


def activate_skill_for_turn(
    db: Session,
    *,
    turn_id: str | None,
    user_pk: int,
    skill: UserSkill,
) -> None:
    """Persist only the versioned activation seam needed to resume a Turn.

    The Turn snapshot is operational execution state, not a second Skill
    owner and never a model-visible checkpoint narrative.  AgentTask gets the
    same immutable reference when a complex plan exists.
    """

    if not turn_id:
        return
    from app.models.conversation_turn import ConversationTurn

    turn = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.id == turn_id,
            ConversationTurn.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if turn is None:
        raise ValueError("skill_turn_not_found")
    snapshot = dict(turn.tool_snapshot_json or {})
    refs = [
        dict(item)
        for item in snapshot.get("activated_skills", [])
        if isinstance(item, dict) and item.get("name") != skill.name
    ]
    refs.append(
        {
            "id": skill.id,
            "name": skill.name,
            "source": skill.source,
            "revision": int(skill.revision or 1),
            "content_hash": skill.content_hash,
        }
    )
    snapshot["activated_skills"] = sorted(refs, key=lambda item: item["name"])
    turn.tool_snapshot_json = snapshot
    bind_skill_to_agent_task(
        db,
        turn_id=turn_id,
        user_pk=user_pk,
        skill=skill,
    )
    db.flush()


def load_activated_skills_for_turn(
    db: Session,
    *,
    turn_id: str | None,
    user_pk: int,
    pinned_refs: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Reload and validate every explicitly pinned Skill reference.

    A missing, disabled, renamed, or incompatible revision is returned as a
    blocking error.  Runtime never silently swaps in a newer workflow.
    """

    refs: list[dict[str, Any]] = [dict(item) for item in (pinned_refs or [])]
    if turn_id:
        from app.models.conversation_turn import ConversationTurn

        turn = (
            db.query(ConversationTurn)
            .filter(
                ConversationTurn.id == turn_id,
                ConversationTurn.user_id == user_pk,
            )
            .one_or_none()
        )
        if turn is not None:
            refs.extend(
                dict(item)
                for item in (turn.tool_snapshot_json or {}).get("activated_skills", [])
                if isinstance(item, dict)
            )
    deduped = {
        (str(item.get("source") or "user"), str(item.get("name") or "")): item
        for item in refs
        if item.get("name")
    }
    loaded: list[dict[str, Any]] = []
    errors: list[str] = []
    for (_source, name), ref in sorted(deduped.items()):
        skill_id = ref.get("id")
        row = (
            db.query(UserSkill)
            .filter(
                UserSkill.id == skill_id,
                UserSkill.user_id == user_pk,
                UserSkill.enabled.is_(True),
            )
            .one_or_none()
        )
        if row is None or row.name != name or row.source != ref.get("source", "user"):
            errors.append(f"skill_unavailable:{name}")
            continue
        if int(row.revision or 1) != int(
            ref.get("revision") or 0
        ) or row.content_hash != ref.get("content_hash"):
            errors.append(f"skill_revision_changed:{name}")
            continue
        bind_skill_to_agent_task(
            db,
            turn_id=turn_id,
            user_pk=user_pk,
            skill=row,
        )
        payload = skill_payload(row)
        loaded.append(payload)
    db.flush()
    return loaded, errors
