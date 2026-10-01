"""Explicit LlamaParse v2 REST adapter, without deprecated SDK/event-loop patching.

Official API guide: https://developers.llamaindex.ai/llamaparse/parse/guides/api-reference/
One admitted paid job, no retry of POST. Polls are bounded control-plane reads.
Raw document bytes and parser output never enter the consumption ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.model_policy import require_local_model
from app.core.execution_errors import ModelOutcomeUnknownError
from app.rag.documents import ParsedDocument, ParsedPage
from app.usage import runtime


def _json(client, method, url, deadline, **kwargs):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("cloud_parse_deadline")
    body = bytearray()
    with client.stream(method, url, timeout=min(remaining, 60), **kwargs) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            if time.monotonic() > deadline:
                raise TimeoutError("cloud_parse_deadline")
            body.extend(chunk)
            if len(body) > settings.CLOUD_PARSE_MAX_OUTPUT_BYTES:
                raise ValueError("cloud_parse_output_capacity")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("cloud_parse_response_shape")
    return data


def parse(file_path: str) -> ParsedDocument:
    require_local_model("document_parsing", is_local=False)
    path = Path(file_path).resolve(strict=True)
    if (
        not path.is_file()
        or not 0 < path.stat().st_size <= settings.CLOUD_PARSE_MAX_INPUT_BYTES
    ):
        raise ValueError("cloud_parse_input_capacity")
    if not settings.LLAMA_CLOUD_API_KEY.strip():
        raise ValueError("cloud_parse_key_missing")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    limit = settings.CLOUD_PARSE_MAX_PAGES
    # For non-paginated formats only the server can establish page count. Reserve
    # the requested upper bound; reaching it is not proof the whole file parsed.
    known_pages = None
    if path.suffix.lower() == ".pdf":
        import fitz

        with fitz.open(path) as document:
            known_pages = document.page_count
        if not 0 < known_pages <= limit:
            raise ValueError("cloud_parse_page_capacity")
    count = known_pages or limit
    config = {
        "tier": settings.CLOUD_PARSE_TIER,
        "version": settings.CLOUD_PARSE_VERSION,
        "page_ranges": {"max_pages": count},
    }
    units = {
        "requests": 1,
        "documents": 1,
        "pages": count,
        "bytes": path.stat().st_size,
    }
    receipt = runtime.begin(
        meter="document_parsing",
        provider="llamacloud",
        model=f"{settings.CLOUD_PARSE_TIER}:{settings.CLOUD_PARSE_VERSION}",
        content={"sha256": digest.hexdigest(), "configuration": config},
        units=units,
    )
    output_key = "text" if settings.CLOUD_PARSE_TIER == "fast" else "markdown"
    accepted = False
    job_completed = False
    observed_units = None
    try:
        deadline = time.monotonic() + settings.CLOUD_PARSE_DEADLINE_SECONDS
        with httpx.Client(
            base_url="https://api.cloud.llamaindex.ai",
            follow_redirects=False,
            headers={"Authorization": f"Bearer {settings.LLAMA_CLOUD_API_KEY}"},
        ) as client:
            with path.open("rb") as stream:
                created = _json(
                    client,
                    "POST",
                    "/api/v2/parse/upload",
                    deadline,
                    files={"file": (path.name, stream, "application/octet-stream")},
                    data={"configuration": json.dumps(config)},
                )
            accepted = True
            job_id = created.get("id")
            if not isinstance(job_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}", job_id
            ):
                raise ValueError("cloud_parse_job_identity")
            runtime.provider_reference(receipt, job_id)
            while True:
                result = _json(
                    client,
                    "GET",
                    f"/api/v2/parse/{job_id}",
                    deadline,
                    params={"expand": f"{output_key},usage"},
                )
                job = result.get("job")
                if not isinstance(job, dict) or job.get("id") != job_id:
                    raise ValueError("cloud_parse_job_mismatch")
                status = job.get("status")
                if status == "COMPLETED":
                    job_completed = True
                    break
                if status in {"FAILED", "CANCELLED"}:
                    # A failed accepted job may still be billed; not a rejected POST.
                    raise RuntimeError("cloud_parse_accepted_job_failed")
                if status not in {"PENDING", "RUNNING"}:
                    raise ValueError("cloud_parse_unknown_status")
                time.sleep(min(1.0, max(0, deadline - time.monotonic())))
            pages = (result.get(output_key) or {}).get("pages")
            if not isinstance(pages, list) or not pages or len(pages) > count:
                raise ValueError("cloud_parse_pages_invalid")
            parsed = []
            page_numbers = set()
            for index, page in enumerate(pages):
                if not isinstance(page, dict) or not isinstance(
                    page.get(output_key), str
                ):
                    raise ValueError("cloud_parse_markdown_invalid")
                if page.get("success") is False:
                    raise ValueError("cloud_parse_page_incomplete")
                number = page.get("page_number")
                if type(number) is not int or number < 1 or number in page_numbers:
                    raise ValueError("cloud_parse_page_number_invalid")
                page_numbers.add(number)
                parsed.append(ParsedPage(text=page[output_key], number=number))
            observed_units = {**units, "pages": len(parsed)}
            # Refuse silent truncation instead of recording a partial file as complete.
            if (known_pages is not None and len(parsed) != known_pages) or (
                known_pages is None and len(parsed) >= limit
            ):
                raise ValueError("cloud_parse_coverage_incomplete")
            document = ParsedDocument(
                pages=parsed,
                parser_id="llamaparse",
                content_kind="text" if output_key == "text" else "markdown",
            )
    except BaseException as exc:
        outcome = (
            "completed"
            if job_completed
            else "unknown"
            if accepted
            else runtime.failure_outcome(exc)
        )
        runtime.finish(receipt, outcome, observed_units)
        if outcome == "unknown" and isinstance(exc, Exception):
            raise ModelOutcomeUnknownError("cloud_parse_outcome_unknown") from exc
        raise
    # Result validation and HTTP client cleanup precede settlement. A lost
    # settlement acknowledgement must not re-enter the provider failure path.
    runtime.finish(receipt, "completed", observed_units)
    return document
