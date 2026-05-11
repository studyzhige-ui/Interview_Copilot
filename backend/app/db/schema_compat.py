import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


COMPAT_COLUMNS: dict[str, dict[str, str]] = {
    "chat_sessions": {
        "session_type": "VARCHAR DEFAULT 'general' NOT NULL",
        "interview_id": "VARCHAR",
        "session_state": "TEXT",
        "compaction_cursor": "INTEGER DEFAULT 0",
        "memory_extraction_cursor": "INTEGER DEFAULT 0",
        "turn_count": "INTEGER DEFAULT 0",
    },
    "chat_messages": {
        "rewritten_query": "TEXT",
    },
    "memory_items": {
        "scope": "VARCHAR DEFAULT 'user' NOT NULL",
        "importance": "FLOAT DEFAULT 0.5",
        "last_accessed_at": "DATETIME",
        "embedding_status": "VARCHAR DEFAULT 'pending' NOT NULL",
        "embedding_model": "VARCHAR",
        "embedded_at": "DATETIME",
    },
}


def ensure_compatible_schema(engine: Engine) -> None:
    """Deprecated local repair helper.

    Alembic is now the supported schema management path. This helper is kept
    only for temporary manual repair of old local development databases.
    """
    logger.warning("schema_compat is deprecated; use `alembic upgrade head` instead.")
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table_name, required_columns in COMPAT_COLUMNS.items():
            if table_name not in existing_tables:
                continue

            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            for column_name, column_sql in required_columns.items():
                if column_name in existing_columns:
                    continue
                logger.info("Adding missing column %s.%s", table_name, column_name)
                connection.execute(
                    text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {column_sql}')
                )
