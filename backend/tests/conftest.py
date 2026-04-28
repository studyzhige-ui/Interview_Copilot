import os
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


_MAYBE_MISSING = [
    "whisperx",
    "whisperx.diarize",
    "pyannote",
    "pyannote.audio",
]

for module_name in _MAYBE_MISSING:
    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()


os.environ.setdefault("DATABASE_URL", "sqlite:///./test_unit.db")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")

TEST_DB_URL = "sqlite://"


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})

    from app.db.database import Base
    import app.models.agent_trace  # noqa: F401
    import app.models.chat  # noqa: F401
    import app.models.interview  # noqa: F401
    import app.models.interview_state  # noqa: F401
    import app.models.memory  # noqa: F401
    import app.models.user  # noqa: F401

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
