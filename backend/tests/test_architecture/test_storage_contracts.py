"""Prevent storage semantics from drifting back to legacy conventions."""

from __future__ import annotations

from pathlib import Path

import app.models  # noqa: F401 -- register every mapper
from app.db.database import Base
from app.db.types import JSONValue, UTCDateTime
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.sqltypes import DateTime

APP_ROOT = Path(__file__).parents[3] / "app"


def test_application_never_creates_naive_utc_timestamps() -> None:
    violations = []
    for path in APP_ROOT.rglob("*.py"):
        if path.name == "types.py" and path.parent.name == "db":
            continue
        source = path.read_text(encoding="utf-8")
        if "datetime.utcnow(" in source or "datetime.now()" in source:
            violations.append(str(path.relative_to(APP_ROOT)))
    assert not violations, f"Naive timestamp creation found in: {violations}"


def test_every_orm_datetime_uses_utc_value_type() -> None:
    violations = []
    utc_columns = 0
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, UTCDateTime):
                utc_columns += 1
            elif isinstance(column.type, DateTime):
                violations.append(f"{table.name}.{column.name}")
    assert utc_columns > 0
    assert not violations, f"Datetime columns bypass UTCDateTime: {violations}"


def test_structured_value_type_uses_jsonb_on_postgres() -> None:
    resolved = JSONValue.dialect_impl(postgresql.dialect())
    assert isinstance(resolved, JSONB)
