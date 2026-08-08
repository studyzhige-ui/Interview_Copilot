"""Verify evaluation corpus files and the indexed chunk provenance."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("corpus_manifest.json")
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "data" / "evaluation" / "corpus"


def _document_id(filename: str) -> str:
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:24]
    return f"kdoc_eval_{digest}"


def validate_manifest_files(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    *,
    manifest_path: Path = MANIFEST_PATH,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths: list[Path] = []
    entries: list[dict[str, str]] = []
    errors: list[str] = []
    for item in manifest["documents"]:
        path = source_dir / str(item["file"])
        if not path.is_file():
            errors.append(f"missing corpus file: {path}")
            continue
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        expected_sha = str(item.get("sha256") or "").lower()
        if actual_sha != expected_sha:
            errors.append(
                f"corpus SHA-256 mismatch for {path.name}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        paths.append(path)
        entries.append({"file": path.name, "sha256": actual_sha})
    if errors:
        raise ValueError("Corpus validation failed:\n- " + "\n- ".join(errors))
    fingerprint = hashlib.sha256(
        json.dumps(entries, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {"paths": paths, "entries": entries, "fingerprint": fingerprint}


def validate_evaluation_index(
    *,
    username: str = "eval_user_a",
    source_dir: Path = DEFAULT_SOURCE_DIR,
) -> dict[str, Any]:
    from app.core.config import settings
    from app.db.database import SessionLocal
    from app.models.document_chunk import DocumentChunk
    from app.models.knowledge import KnowledgeDocument
    from app.models.user import User

    corpus = validate_manifest_files(source_dir)
    expected_source_hashes = {
        _document_id(item["file"]): item["sha256"] for item in corpus["entries"]
    }
    filenames_by_id = {
        _document_id(item["file"]): item["file"] for item in corpus["entries"]
    }
    expected_documents = set(expected_source_hashes)
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            raise RuntimeError(f"Evaluation user does not exist: {username}")
        documents = (
            db.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.user_id == user.id,
                KnowledgeDocument.deleted_at.is_(None),
            )
            .all()
        )
        chunks = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.user_id == user.id,
                DocumentChunk.deleted_at.is_(None),
            )
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .all()
        )

    errors: list[str] = []
    actual_documents = {str(document.id) for document in documents}
    if actual_documents != expected_documents:
        errors.append(
            "indexed document set differs from corpus manifest "
            f"(missing={sorted(expected_documents - actual_documents)}, "
            f"extra={sorted(actual_documents - expected_documents)})"
        )
    not_ready = [document.id for document in documents if document.status != "ready"]
    if not_ready:
        errors.append(f"documents are not ready: {not_ready}")
    stale_sources = [
        str(document.id)
        for document in documents
        if document.source_ref_type != "evaluation_corpus_sha256"
        or document.source_ref_id != expected_source_hashes.get(str(document.id))
    ]
    if stale_sources:
        errors.append(f"documents do not match current source bytes: {stale_sources}")
    if not chunks:
        errors.append("evaluation index contains no chunks")

    expected_splitter = {
        "chunk_target": settings.RAG_CHUNK_TOKENS,
        "chunk_overlap": settings.RAG_CHUNK_OVERLAP,
        "passage_limit": settings.RAG_RERANK_INPUT_TOKENS
        - settings.RAG_QUERY_TOKEN_RESERVE,
    }
    expected_embedding = {
        "embedding_provider": settings.EMBEDDING_PROVIDER,
        "embedding_model": settings.EMBEDDING_MODEL,
    }
    parser_counts: Counter[str] = Counter()
    parser_documents: dict[str, set[str]] = {}
    fallback_documents: set[str] = set()
    chunk_counts: Counter[str] = Counter()
    canonical_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        chunk_counts[str(chunk.document_id)] += 1
        if chunk.index_status != "indexed":
            errors.append(f"chunk is not indexed: {chunk.id}")
        actual_text_hash = hashlib.sha256(
            (chunk.text or "").encode("utf-8")
        ).hexdigest()
        if chunk.text_hash != actual_text_hash:
            errors.append(f"chunk text hash mismatch: {chunk.id}")
        try:
            metadata = json.loads(chunk.metadata_json or "{}")
        except json.JSONDecodeError:
            errors.append(f"chunk metadata is invalid JSON: {chunk.id}")
            continue
        splitter = metadata.get("splitter_profile") or {}
        embedding = metadata.get("embedding_profile") or {}
        parser_id = str(metadata.get("parser_id") or "")
        if any(splitter.get(key) != value for key, value in expected_splitter.items()):
            errors.append(f"chunk splitter profile mismatch: {chunk.id}")
        if any(
            embedding.get(key) != value for key, value in expected_embedding.items()
        ):
            errors.append(f"chunk embedding profile mismatch: {chunk.id}")
        if not parser_id:
            errors.append(f"chunk parser provenance is missing: {chunk.id}")
        parser_counts[parser_id] += 1
        filename = filenames_by_id.get(str(chunk.document_id), str(chunk.document_id))
        parser_documents.setdefault(parser_id, set()).add(filename)
        fallback_used = bool(
            (metadata.get("parser_profile") or {}).get("fallback_used")
        )
        if fallback_used:
            fallback_documents.add(filename)
        canonical_chunks.append(
            {
                "document_id": chunk.document_id,
                "node_id": chunk.node_id,
                "chunk_index": chunk.chunk_index,
                "text_hash": chunk.text_hash,
                "splitter": {key: splitter.get(key) for key in expected_splitter},
                "embedding": {key: embedding.get(key) for key in expected_embedding},
                "parser_id": parser_id,
                "parser_fallback": fallback_used,
            }
        )
    chunk_documents = {str(chunk.document_id) for chunk in chunks}
    if chunk_documents != expected_documents:
        errors.append("not every manifest document has indexed chunks")
    count_mismatches = [
        str(document.id)
        for document in documents
        if int(document.chunk_count) != chunk_counts[str(document.id)]
    ]
    if count_mismatches:
        errors.append(f"document chunk counts are stale: {count_mismatches}")
    if errors:
        preview = errors[:20]
        suffix = f"\n- ... {len(errors) - 20} more" if len(errors) > 20 else ""
        raise ValueError(
            "Evaluation index provenance validation failed:\n- "
            + "\n- ".join(preview)
            + suffix
        )

    fingerprint_payload = {
        "corpus_fingerprint": corpus["fingerprint"],
        "chunks": canonical_chunks,
    }
    return {
        "fingerprint": hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "corpus_fingerprint": corpus["fingerprint"],
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "splitter_profile": expected_splitter,
        "embedding_profile": expected_embedding,
        "parser_chunk_counts": dict(sorted(parser_counts.items())),
        "parser_documents": {
            parser_id: sorted(filenames)
            for parser_id, filenames in sorted(parser_documents.items())
        },
        "fallback_documents": sorted(fallback_documents),
    }


__all__ = ["validate_evaluation_index", "validate_manifest_files"]
