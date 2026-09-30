"""Bounded local document execution using the shared process-lifecycle owner.

CPU parsing never occupies the GPU broker or imports Docling in the caller.
The upstream file-asset boundary owns authorization; this boundary pins bytes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from threading import BoundedSemaphore

from app.core.config import settings
from app.core.isolated_process import run_isolated
from app.core.runtime_files import runtime_temp_dir
from app.rag.documents import ParsedDocument, ParsedPage

CONTRACT = "docling-cpu-isolated-v1"
SLOTS = BoundedSemaphore(1)


class DocumentSourceChanged(ValueError):
    """Do not fall back to a parser reading a different revision of the source."""


def signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def snapshot(path: str, *, maximum: int):
    source = Path(path).absolute()
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ValueError("document_input_capacity")
        with tempfile.TemporaryDirectory(
            prefix="document-", dir=runtime_temp_dir()
        ) as directory:
            target = Path(directory) / ("source" + source.suffix.lower())
            digest, count = hashlib.sha256(), 0
            with target.open("xb") as out:
                while block := os.read(fd, 1024 * 1024):
                    count += len(block)
                    if count > maximum:
                        raise ValueError("document_input_capacity")
                    digest.update(block)
                    out.write(block)
            if signature(os.fstat(fd)) != signature(before) or count != before.st_size:
                raise DocumentSourceChanged("document_source_changed")
            target.chmod(0o400)
            try:
                yield target, digest.hexdigest()
            finally:
                try:
                    unchanged = signature(source.lstat()) == signature(before)
                except OSError:
                    unchanged = False
                if not unchanged or signature(os.fstat(fd)) != signature(before):
                    raise DocumentSourceChanged("document_source_changed")

    finally:
        os.close(fd)


def validate_result(value, *, digest: str, max_pages: int, max_text: int):
    if not isinstance(value, dict) or set(value) != {
        "contract",
        "sha256",
        "pages",
        "ocr_used",
        "ocr_enabled",
        "package_version",
    }:
        raise ValueError("invalid_document_result")
    if (
        value["contract"] != CONTRACT
        or value["sha256"] != digest
        or value["package_version"] != "2.118.1"
    ):
        raise ValueError("document_result_identity_mismatch")
    if type(value["ocr_used"]) is not bool or type(value["ocr_enabled"]) is not bool:
        raise ValueError("invalid_document_ocr_observation")
    rows = value["pages"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= max_pages:
        raise ValueError("document_page_capacity")
    pages, total, previous = [], 0, 0
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"text", "number"}
            or not isinstance(row["text"], str)
        ):
            raise ValueError("invalid_document_page")
        number = row["number"]
        if number is not None:
            if type(number) is not int or not previous < number <= max_pages:
                raise ValueError("invalid_document_page_number")
            previous = number
        total += len(row["text"].encode("utf-8"))
        if total > max_text:
            raise ValueError("document_output_capacity")
        pages.append(ParsedPage(text=row["text"], number=number))
    return ParsedDocument(
        pages=pages,
        parser_id="docling",
        content_kind="markdown",
        ocr_used=value["ocr_used"],
        runtime_profile={
            "contract": CONTRACT,
            "device": "cpu",
            "package_version": value["package_version"],
            "ocr_enabled": value["ocr_enabled"],
        },
    )


def parse_local_document(path: str) -> ParsedDocument:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("local_document_requires_linux_or_wsl2")
    executable = (
        Path(settings.PARSER_LOCAL_PYTHON or sys.executable).expanduser().absolute()
    )
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("invalid_document_interpreter")
    deadline = time.monotonic() + settings.PARSER_TIMEOUT_SECONDS
    if not SLOTS.acquire(timeout=settings.PARSER_TIMEOUT_SECONDS):
        raise TimeoutError("document_queue_deadline")
    try:
        from app.core.model_assets import local_path
        from app.core.hf_runtime import DOCLING_MODELS_DIR

        cache = local_path(settings.CACHE_DIR).absolute() / "document-runtime"
        cache.mkdir(parents=True, exist_ok=True)
        # No API, database, provider credentials, proxy or user PYTHONPATH.
        env = {
            key: os.environ[key]
            for key in ("PATH", "LD_LIBRARY_PATH")
            if key in os.environ
        }
        env.update(
            {
                "HOME": str(cache),
                "HF_HOME": str(cache / "huggingface"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "CUDA_VISIBLE_DEVICES": "",
                "OMP_NUM_THREADS": "2",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        with snapshot(path, maximum=settings.PARSER_MAX_INPUT_BYTES) as (
            source,
            digest,
        ):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("document_deadline")
            payload = {
                "contract": CONTRACT,
                "source": str(source),
                "sha256": digest,
                "artifacts": str(DOCLING_MODELS_DIR.absolute()),
                "ocr": settings.RAG_OCR_ENABLED,
                "max_input_bytes": settings.PARSER_MAX_INPUT_BYTES,
                "max_pages": settings.PARSER_MAX_PAGES,
                "max_text_bytes": settings.PARSER_MAX_TEXT_BYTES,
                "timeout": remaining,
            }
            result = asyncio.run(
                run_isolated(
                    [
                        str(executable),
                        "-I",
                        "-B",
                        str(Path(__file__).with_name("docling_worker.py")),
                    ],
                    env=env,
                    cwd=source.parent,
                    input_data=json.dumps(payload).encode(),
                    timeout_seconds=remaining,
                    max_output_bytes=min(
                        16 * 1024 * 1024, settings.PARSER_MAX_TEXT_BYTES * 2 + 65536
                    ),
                )
            )
            if result.returncode:
                # Native/library diagnostics may contain source text: never forward them.
                raise RuntimeError("local_document_failed_or_assets_unavailable")
            parsed = validate_result(
                json.loads(result.stdout),
                digest=digest,
                max_pages=settings.PARSER_MAX_PAGES,
                max_text=settings.PARSER_MAX_TEXT_BYTES,
            )
        return parsed
    finally:
        SLOTS.release()
