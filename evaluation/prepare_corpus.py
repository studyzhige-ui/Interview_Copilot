"""Index the verified public corpus through the production RAG pipeline."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
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
from app.rag.ingestion import ingest_document, ingest_text  # noqa: E402
from app.rag.milvus_hybrid import KNOWLEDGE, delete_by_field  # noqa: E402

from evaluation.runners import load_dataset  # noqa: E402
from evaluation.isolation_probe import (  # noqa: E402
    ISOLATION_DOCUMENT_ID,
    ISOLATION_TEXT,
    ISOLATION_USER,
)
from evaluation.index_provenance import validate_manifest_files  # noqa: E402


def _source_paths(dataset: Path, source_dir: Path) -> list[Path]:
    names: set[str] = set()
    for row in load_dataset(path=dataset):
        if row.get("source_file"):
            names.add(str(row["source_file"]))
        names.update(str(name) for name in row.get("source_files", []) if name)
    paths = [source_dir / name for name in sorted(names)]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        joined = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Evaluation source files are missing:\n{joined}")
    return paths


def _manifest_paths(source_dir: Path) -> list[Path]:
    return list(validate_manifest_files(source_dir)["paths"])


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
    delete_by_field(KNOWLEDGE, "user_id", user_pk)
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
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, document_id)
        if (
            document is not None
            and document.status == "ready"
            and document.source_ref_type == "evaluation_corpus_sha256"
            and document.source_ref_id == source_sha
        ):
            return path.name, int(document.chunk_count)
        if document is not None:
            delete_by_field(KNOWLEDGE, "document_id", document_id)
            db.query(DocumentChunk).filter(
                DocumentChunk.document_id == document_id
            ).delete(synchronize_session=False)
        if document is None:
            document = KnowledgeDocument(
                id=document_id,
                user_id=user_pk,
                title=path.stem,
                category="Evaluation",
                source_kind="user_upload",
                source_ref_type="evaluation_corpus_sha256",
                source_ref_id=source_sha,
                status="processing",
            )
            db.add(document)
        else:
            document.status = "processing"
            document.error_message = None
            document.source_ref_type = "evaluation_corpus_sha256"
            document.source_ref_id = source_sha
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


async def _prepare_isolation_probe(*, reset: bool) -> int:
    user_pk = _ensure_user(ISOLATION_USER)
    if reset:
        _reset_user_corpus(user_pk)
    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, ISOLATION_DOCUMENT_ID)
        if document is not None and document.status == "ready":
            return user_pk
        if document is None:
            document = KnowledgeDocument(
                id=ISOLATION_DOCUMENT_ID,
                user_id=user_pk,
                title="Tenant isolation probe",
                category="Evaluation",
                source_kind="manual_text",
                content_text=ISOLATION_TEXT,
                status="processing",
            )
            db.add(document)
        else:
            document.status = "processing"
            document.error_message = None
        db.commit()

    result = await ingest_text(
        ISOLATION_TEXT,
        "manual_text",
        user_pk,
        document_id=ISOLATION_DOCUMENT_ID,
    )
    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, ISOLATION_DOCUMENT_ID)
        if document is None:
            raise RuntimeError("Tenant isolation probe disappeared during indexing")
        document.chunk_count = int(result["chunk_count"])
        document.ref_doc_ids = json.dumps(result.get("ref_doc_ids") or [])
        document.status = "ready"
        document.error_message = None
        db.commit()
    return user_pk


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Index only files referenced by this dataset; the default indexes "
        "every verified manifest document.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "corpus",
    )
    parser.add_argument("--user", default="eval_user_a")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    from evaluation.workflow_lock import evaluation_index_lock

    with evaluation_index_lock():
        source_dir = args.source_dir.resolve()
        paths = (
            _source_paths(args.dataset.resolve(), source_dir)
            if args.dataset is not None
            else _manifest_paths(source_dir)
        )
        user_pk = _ensure_user(args.user)
        if args.reset:
            _reset_user_corpus(user_pk)

        init_rag_settings()
        asyncio.run(_run(paths, user_pk))
        asyncio.run(_prepare_isolation_probe(reset=args.reset))
    print(f"Evaluation corpus ready for {args.user}: {len(paths)} source files.")


if __name__ == "__main__":
    main()
