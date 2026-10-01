from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    # SQLite does not support connection pooling or check_same_thread.
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        connect_args={"connect_timeout": 5},
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,  # Detect stale connections before use.
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """One cached session per handler/auth dependency graph.

    Always declare Depends(get_db, scope="function"). Mixing FastAPI scopes
    creates separate sessions, making an authenticated ORM User unusable by
    mutation handlers. Function scope closes before a streaming response body;
    generators must capture scalar data or open their own short-lived sessions.
    The architecture regression enforces this shared lifetime contract.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
