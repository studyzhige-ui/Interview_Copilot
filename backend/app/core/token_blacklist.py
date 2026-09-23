"""Durable JWT consumption. The caller owns the SQL transaction.

A unique jti arbitrates concurrent refreshes in the database. A successful
logout is acknowledged only after commit; Redis is not a security authority.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.token_revocation import TokenRevocation


def is_revoked(db: Session, jti: str | None) -> bool:
    return not jti or db.get(TokenRevocation, jti) is not None


def consume(db: Session, jti: str, exp: int | float) -> bool:
    """Return True for the single winner, without committing unrelated work."""
    if not jti or len(jti) > 64:
        raise ValueError("Invalid token identifier")
    expiry = datetime.fromtimestamp(exp, timezone.utc).replace(tzinfo=None)
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    result = db.execute(
        insert(TokenRevocation)
        .values(jti=jti, expires_at=expiry)
        .on_conflict_do_nothing(index_elements=["jti"])
    )
    return result.rowcount == 1


def revoke(db: Session, jti: str, exp: int | float) -> None:
    """Idempotently persist revocation; storage errors deliberately propagate."""
    consume(db, jti, exp)


def prune_expired(db: Session, *, limit: int = 1000) -> int:
    """Bounded maintenance; an expired JWT cannot authorize another request."""
    expired = (
        select(TokenRevocation.jti)
        .where(
            TokenRevocation.expires_at < datetime.now(timezone.utc).replace(tzinfo=None)
        )
        .limit(limit)
    )
    result = db.execute(delete(TokenRevocation).where(TokenRevocation.jti.in_(expired)))
    return result.rowcount
