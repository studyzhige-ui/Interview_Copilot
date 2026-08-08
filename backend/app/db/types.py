"""Database value types shared by every persistence model."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    """Return an aware UTC timestamp for defaults and lifecycle comparisons."""
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """Normalize legacy naive UTC values and aware values to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware timestamp with a stable UTC Python representation.

    PostgreSQL stores ``TIMESTAMP WITH TIME ZONE``. SQLite drops timezone
    metadata, so the result hook restores UTC for tests and local tooling.
    Legacy naive values are interpreted as UTC, matching the project's prior
    ``datetime.utcnow()`` convention.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        return as_utc(value)

    def process_result_value(self, value, dialect):
        return as_utc(value)


# PostgreSQL uses JSONB for native structured values and future containment
# indexes; SQLite uses its portable JSON type in unit tests. Encrypted strings
# and deliberately opaque text snapshots remain Text.
JSONValue = JSON().with_variant(JSONB(), "postgresql")


__all__ = ["JSONValue", "UTCDateTime", "as_utc", "utc_now"]
