from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.types import JSONValue, UTCDateTime, as_utc, utc_now
from sqlalchemy import Column, Integer, create_engine
from sqlalchemy.orm import DeclarativeBase, Session


class _Base(DeclarativeBase):
    pass


class _TypedRow(_Base):
    __tablename__ = "typed_rows"

    id = Column(Integer, primary_key=True)
    occurred_at = Column(UTCDateTime, nullable=False)
    payload = Column(JSONValue, nullable=False)


def test_as_utc_normalizes_legacy_and_offset_values() -> None:
    legacy = datetime(2026, 8, 5, 10, 30)
    assert as_utc(legacy) == legacy.replace(tzinfo=UTC)

    offset = datetime(2026, 8, 5, 18, 30, tzinfo=UTC) + timedelta(0)
    assert as_utc(offset).tzinfo is UTC
    assert utc_now().tzinfo is UTC


def test_sqlite_round_trip_restores_aware_utc_and_structured_json() -> None:
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            _TypedRow(
                id=1,
                occurred_at=datetime(2026, 8, 5, 10, 30),
                payload={"items": [1, 2], "enabled": True},
            )
        )
        session.commit()
        row = session.get(_TypedRow, 1)

    assert row.occurred_at == datetime(2026, 8, 5, 10, 30, tzinfo=UTC)
    assert row.payload == {"items": [1, 2], "enabled": True}
