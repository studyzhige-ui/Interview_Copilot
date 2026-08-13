"""Dry-run or apply the conservative Stage 2 legacy Memory migration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Support ``python scripts/migrate_legacy_memory.py`` from the repository root
# and the equivalent container layout without installing ``backend/app``.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

from app.db.database import SessionLocal  # noqa: E402
from app.services.legacy_memory_migration import migrate_legacy_memory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create eligible canonical AbilitySignals; default is dry-run",
    )
    args = parser.parse_args()
    db = SessionLocal()
    try:
        report = migrate_legacy_memory(db, apply=args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
