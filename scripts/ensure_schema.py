import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import app.models.agent_trace  # noqa: F401
import app.models.chat  # noqa: F401
import app.models.interview  # noqa: F401
import app.models.interview_state  # noqa: F401
import app.models.memory  # noqa: F401
import app.models.user  # noqa: F401
from app.db.database import engine
from app.db.schema_compat import ensure_compatible_schema


def main() -> None:
    print("Deprecated: use `alembic upgrade head` for normal schema management.")
    ensure_compatible_schema(engine)
    print("legacy schema compatibility pass completed")


if __name__ == "__main__":
    main()
