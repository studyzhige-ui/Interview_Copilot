"""Report or quarantine legacy chat-attachment projections safely."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Support direct execution from the repository root without installing the
# backend package.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

from app.db.database import SessionLocal  # noqa: E402
from app.services.legacy_attachment_migration import (  # noqa: E402
    migrate_legacy_attachments,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "soft-quarantine projections without canonical scope; default is "
            "a read-only report"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional UTF-8 JSON report path; stdout is always written",
    )
    args = parser.parse_args()
    db = SessionLocal()
    try:
        report = migrate_legacy_attachments(db, apply=args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload + "\n", encoding="utf-8")
        print(payload)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
