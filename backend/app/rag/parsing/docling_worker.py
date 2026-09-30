"""Trusted, credential-free, CPU-only Docling interpreter entrypoint.

Only the owned parser process runner starts this file, with fixed JSON on stdin.
No application configuration or .env is imported in this interpreter. Offline
flags and the Python network audit hook are guards, not a native-code sandbox.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys

CONTRACT = "docling-cpu-isolated-v1"
EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
}
IMAGES = EXTENSIONS - {".pdf", ".docx", ".pptx", ".html", ".htm"}


def deny_network(event, _args):
    if event in {
        "socket.connect",
        "socket.connect_ex",
        "socket.getaddrinfo",
        "socket.sendto",
    }:
        raise RuntimeError("document_network_denied")


def validate_input(value):
    expected = {
        "contract",
        "source",
        "sha256",
        "artifacts",
        "ocr",
        "max_input_bytes",
        "max_pages",
        "max_text_bytes",
        "timeout",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value["contract"] != CONTRACT
    ):
        raise ValueError("invalid_document_request")
    for key, maximum in (
        ("max_input_bytes", 500 * 1024 * 1024),
        ("max_pages", 10000),
        ("max_text_bytes", 8_000_000),
    ):
        if type(value[key]) is not int or not 1 <= value[key] <= maximum:
            raise ValueError("invalid_document_limits")
    if (
        type(value["ocr"]) is not bool
        or type(value["timeout"]) not in (int, float)
        or not math.isfinite(value["timeout"])
        or not 0 < value["timeout"] <= 3600
    ):
        raise ValueError("invalid_document_options")
    if not isinstance(value["sha256"], str) or not re.fullmatch(
        "[a-f0-9]{64}", value["sha256"]
    ):
        raise ValueError("invalid_document_digest")
    for key in ("source", "artifacts"):
        if not isinstance(value[key], str) or not Path(value[key]).is_absolute():
            raise ValueError("invalid_document_path")
    source = Path(value["source"])
    if source.parent != Path.cwd() or source.suffix.lower() not in EXTENSIONS:
        raise ValueError("invalid_document_source")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or not 0 < info.st_size <= value["max_input_bytes"]
            or info.st_mode & 0o222
        ):
            raise ValueError("invalid_document_snapshot")
        digest, count = hashlib.sha256(), 0
        while block := os.read(fd, 1024 * 1024):
            count += len(block)
            if count > value["max_input_bytes"]:
                raise ValueError("document_input_capacity")
            digest.update(block)
        if digest.hexdigest() != value["sha256"]:
            raise ValueError("document_source_changed")
    finally:
        os.close(fd)
    return value


def export_document(result, value):
    from docling.datamodel.base_models import ConversionStatus

    if result.status is not ConversionStatus.SUCCESS:
        raise RuntimeError("document_conversion_incomplete")
    document = result.document
    numbers = sorted(document.pages)
    if len(numbers) > value["max_pages"] or any(
        type(n) is not int or not 1 <= n <= value["max_pages"] for n in numbers
    ):
        raise ValueError("document_page_capacity")
    pages, total = [], 0
    for number in numbers or [None]:
        if number is not None:
            from docling_core.types.doc import ContentLayer

            text = document.export_to_markdown(
                page_no=number, included_content_layers={ContentLayer.BODY}
            )
        else:
            text = document.export_to_markdown()
        if not isinstance(text, str):
            raise ValueError("invalid_document_text")
        total += len(text.encode("utf-8"))
        if total > value["max_text_bytes"]:
            raise ValueError("document_output_capacity")
        pages.append({"text": text, "number": number})
    return pages


def convert(value):
    version = importlib.metadata.version("docling")
    if version != "2.118.1":
        raise ValueError("document_sdk_version_mismatch")
    artifacts = Path(value["artifacts"])
    if not artifacts.is_dir():
        raise ValueError("document_assets_unavailable")
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import (
        DocumentConverter,
        ImageFormatOption,
        PdfFormatOption,
    )

    ocr = value["ocr"] and importlib.util.find_spec("rapidocr") is not None
    options = PdfPipelineOptions(
        do_ocr=ocr,
        ocr_options=RapidOcrOptions(backend="onnxruntime"),
        artifacts_path=artifacts,
        accelerator_options=AcceleratorOptions(device="cpu", num_threads=2),
        document_timeout=value["timeout"],
        enable_remote_services=False,
        allow_external_plugins=False,
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
        }
    )
    result = converter.convert(
        Path(value["source"]),
        max_num_pages=value["max_pages"],
        max_file_size=value["max_input_bytes"],
    )
    return {
        "contract": CONTRACT,
        "sha256": value["sha256"],
        "package_version": version,
        "pages": export_document(result, value),
        "ocr_enabled": ocr,
        # Images require OCR. The SDK does not certify which PDF pages used it.
        "ocr_used": bool(ocr and Path(value["source"]).suffix.lower() in IMAGES),
    }


def bind_parent():
    if sys.platform.startswith("linux"):
        import ctypes

        parent = os.getppid()
        if (
            parent == 1
            or ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0
            or os.getppid() != parent
        ):
            raise RuntimeError("document_parent_lost")


def main():
    try:
        bind_parent()
        sys.addaudithook(deny_network)
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("document_request_capacity")
        value = validate_input(json.loads(raw))
        with contextlib.redirect_stdout(sys.stderr):
            result = convert(value)
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        if len(encoded) > min(16 * 1024 * 1024, value["max_text_bytes"] * 2 + 65536):
            raise ValueError("document_wire_capacity")
        sys.stdout.buffer.write(encoded)
        return 0
    except Exception:
        # Do not disclose source content, file names or model exception traces.
        sys.stderr.write("local_document_failed\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
