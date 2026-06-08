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
import app.models.chat  # noqa: F401
import app.models.file_asset  # noqa: F401
import app.models.interview_qa  # noqa: F401
import app.models.interview_record  # noqa: F401
import app.models.knowledge  # noqa: F401
import app.models.memory_ability_state  # noqa: F401 — v3 memory: per-topic mastery
import app.models.memory_audit_logs  # noqa: F401 — v3 memory: audit trail
import app.models.memory_document  # noqa: F401 — v3 memory: profile/strategy docs
import app.models.mock_interview_session  # noqa: F401
import app.models.resume_section  # noqa: F401
import app.models.user  # noqa: F401

config = context.config

# Single source of truth for the DB URL: app.core.config.settings reads
# DATABASE_URL from the environment (.env in dev, real env vars in prod).
# alembic.ini intentionally has an empty sqlalchemy.url so nothing leaks
# into git. The CLI override `alembic -x url=...` still wins because we
# only fall back to settings when -x wasn't passed.
override = context.get_x_argument(as_dictionary=True).get("url")
database_url = override or settings.DATABASE_URL
if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not configured. Set it in .env (or pass "
        "`alembic -x url=...` for one-off overrides)."
    )
# Escape % so ConfigParser doesn't interpret it as interpolation syntax —
# DATABASE_URLs commonly contain URL-encoded passwords with %xx escapes.
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
