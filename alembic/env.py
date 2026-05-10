from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.db.database import Base
import app.models.agent_trace  # noqa: F401
import app.models.chat  # noqa: F401
import app.models.interview  # noqa: F401
import app.models.interview_record  # noqa: F401
import app.models.resume_section  # noqa: F401
import app.models.knowledge  # noqa: F401
import app.models.memory  # noqa: F401
import app.models.upload  # noqa: F401
import app.models.user  # noqa: F401

config = context.config
database_url = config.get_main_option("sqlalchemy.url") or settings.DATABASE_URL
if database_url == "postgresql://postgres:postgres@localhost:5432/interview_copilot":
    database_url = settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
