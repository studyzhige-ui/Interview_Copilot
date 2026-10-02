"""Prepare owner-isolated HNSW graphs on existing BGE projections.

Run in a maintenance window. Default is a DDL preview; --apply creates indexes.
No model calls, source changes or vector regeneration occur.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db.database import SessionLocal  # noqa: E402
from app.models.retrieval_index import RetrievalGeneration  # noqa: E402
from app.rag.index.hnsw import index_spec, prepare  # noqa: E402
from app.rag.index.identity import current_index_identity  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-pk", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    identity = current_index_identity()
    name, ddl = index_spec(identity, args.user_pk)
    if args.apply:
        with SessionLocal() as db:
            if db.get(RetrievalGeneration, identity.fingerprint) is None:
                raise ValueError("index the BGE generation before preparing HNSW")
            prepare(db, identity, args.user_pk)
            db.commit()
    print(json.dumps({"index": name, "ddl": ddl, "applied": args.apply}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
