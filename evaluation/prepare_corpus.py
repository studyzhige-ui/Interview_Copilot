"""Prepare the isolated tenant used by the RAG quality suite.

The source PDFs and real golden dataset are intentionally git-ignored. This
command creates ``eval_user_a`` when needed and indexes each distinct
``source_file`` through the production parser/chunker/embedding pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import secrets
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.security import get_password_hash  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.models.document_chunk import DocumentChunk  # noqa: E402
from app.models.knowledge import KnowledgeDocument  # noqa: E402
from app.models.user import User  # noqa: E402
from app.rag.embeddings import init_rag_settings  # noqa: E402
from app.rag.ingestion import ingest_document  # noqa: E402
from app.rag.milvus_hybrid import KNOWLEDGE, delete_by_user  # noqa: E402
from evaluation.runners import load_dataset  # noqa: E402


def _source_paths(dataset: Path, source_dir: Path) -> list[Path]:
    names = {
        str(row["source_file"])
        for row in load_dataset(path=dataset)
        if row.get("source_file")
    }
    paths = [source_dir / name for name in sorted(names)]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        joined = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Evaluation source files are missing:\n{joined}")
    return paths


def _ensure_user(username: str) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            user = User(
                username=username,
                hashed_password=get_password_hash(secrets.token_urlsafe(32)),
                is_active=False,
                email_verified=False,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return int(user.id)


def _reset_user_corpus(user_pk: int) -> None:
    delete_by_user(KNOWLEDGE, user_pk)
    with SessionLocal() as db:
        db.query(DocumentChunk).filter(DocumentChunk.user_id == user_pk).delete(
            synchronize_session=False
        )
        db.query(KnowledgeDocument).filter(KnowledgeDocument.user_id == user_pk).delete(
            synchronize_session=False
        )
        db.commit()


def _document_id(path: Path) -> str:
    digest = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:24]
    return f"kdoc_eval_{digest}"


async def _index_file(path: Path, user_pk: int) -> tuple[str, int]:
    document_id = _document_id(path)
    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, document_id)
        if document is not None and document.status == "ready":
            return path.name, int(document.chunk_count)
        if document is None:
            document = KnowledgeDocument(
                id=document_id,
                user_id=user_pk,
                title=path.stem,
                category="Evaluation",
                source_kind="user_upload",
                status="processing",
            )
            db.add(document)
        else:
            document.status = "processing"
            document.error_message = None
        db.commit()

    try:
        result = await ingest_document(
            str(path),
            "user_upload",
            user_pk,
            document_id=document_id,
        )
    except Exception as exc:
        with SessionLocal() as db:
            document = db.get(KnowledgeDocument, document_id)
            if document is not None:
                document.status = "failed"
                document.error_message = str(exc)[:500]
                db.commit()
        raise

    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, document_id)
        if document is None:
            raise RuntimeError(f"Evaluation document disappeared: {document_id}")
        document.chunk_count = int(result["chunk_count"])
        document.content_text = result.get("content_text")
        document.status = "ready" if result.get("indexed", True) else "processing"
        document.error_message = None
        db.commit()
        return path.name, document.chunk_count


async def _run(paths: list[Path], user_pk: int) -> None:
    for index, path in enumerate(paths, 1):
        print(f"[{index}/{len(paths)}] indexing {path.name}")
        name, chunk_count = await _index_file(path, user_pk)
        print(f"  ready: {name} ({chunk_count} chunks)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "golden_dataset.jsonl",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "storage" / "uploads",
    )
    parser.add_argument("--user", default="eval_user_a")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    paths = _source_paths(args.dataset.resolve(), args.source_dir.resolve())
    user_pk = _ensure_user(args.user)
    if args.reset:
        _reset_user_corpus(user_pk)

    init_rag_settings(include_primary_llm=False)
    asyncio.run(_run(paths, user_pk))
    print(f"Evaluation corpus ready for {args.user}: {len(paths)} source files.")


if __name__ == "__main__":
    main()
