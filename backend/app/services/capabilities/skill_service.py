from __future__ import annotations

import re
from dataclasses import dataclass

import yaml
from sqlalchemy.orm import Session

from app.models.user_skill import UserSkill


_FRONTMATTER = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    content: str


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
    return SkillDefinition(name=name, description=description, content=text)


def _payload(row: UserSkill, *, include_content: bool = True) -> dict:
    value = {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_content:
        value["content"] = row.content
    return value


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
        _payload(row, include_content=include_content)
        for row in query.order_by(UserSkill.name).all()
    ]


def get_enabled_by_name(db: Session, user_pk: int, name: str) -> dict | None:
    row = (
        db.query(UserSkill)
        .filter(
            UserSkill.user_id == user_pk,
            UserSkill.name == name,
            UserSkill.enabled.is_(True),
        )
        .one_or_none()
    )
    return _payload(row) if row else None


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
        enabled=enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _payload(row)


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
    if enabled is not None:
        row.enabled = enabled
    db.commit()
    db.refresh(row)
    return _payload(row)


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
