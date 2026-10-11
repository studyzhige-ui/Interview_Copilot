"""Current mainline contracts: isolated database and explicit provider doubles."""

import os

os.environ.update(
    DATABASE_URL="sqlite://",
    SECRET_KEY="contract-suite-not-a-production-secret",
    LANGSMITH_TRACING="false",
)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="session")
def engine():
    import app.models  # noqa: F401
    from app.db.database import Base

    value = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(value)
    yield value
    value.dispose()


@pytest.fixture
def db(engine):
    connection = engine.connect()
    transaction = connection.begin()
    with Session(
        connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    ) as session:
        yield session
    transaction.rollback()
    connection.close()


@pytest.fixture
def owners(db):
    from app.models.user import User

    users = [
        User(username=name, hashed_password="not-a-login-hash")
        for name in ("contract_owner", "contract_other")
    ]
    db.add_all(users)
    db.flush()
    return users
