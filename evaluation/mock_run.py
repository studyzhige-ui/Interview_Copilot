"""Finite, append-only call evidence for a single mock-evaluation campaign.

No automatic resume/retry: an interrupted dispatch may have incurred a charge.
The production generator keeps its account ledger; the evaluator journal also
covers the independent judge. No keys, prompts, headers or response bodies are
written to call events. Reports remain private local evaluation data.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.llm_factory import EvaluationLLMConfig


class CampaignLimitError(RuntimeError):
    pass


class CallJournal:
    def __init__(self, maximum: int, path: Path | None = None):
        if type(maximum) is not int or not 1 <= maximum <= 100_000:
            raise ValueError("max model calls must be between 1 and 100000")
        self.maximum, self.path, self.count = maximum, path, 0
        self._lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Never overwrite a previous or interrupted campaign's dispatch log.
            with path.open("x", encoding="utf-8"):
                pass
            path.chmod(0o600)

    def record(self, event: dict[str, Any]) -> None:
        record = {"at": datetime.now(timezone.utc).isoformat(), **event}
        with self._lock:
            if self.path is not None:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, allow_nan=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            self.events.append(record)

    def start(self, role: str, prompt: str) -> int:
        with self._lock:
            if self.count >= self.maximum:
                raise CampaignLimitError("campaign_model_call_limit")
            self.count += 1
            identity = self.count
        # Persist BEFORE invoking the model. A write failure cannot send a call.
        self.record(
            {
                "call": identity,
                "role": role,
                "state": "started",
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            }
        )
        return identity

    def finish(self, identity: int, state: str, *, usage=None, error=None):
        event = {"call": identity, "state": state}
        if usage is not None:
            event["usage"] = usage
        if error is not None:
            # Do not log exception messages, which may contain provider input.
            event["error_type"] = type(error).__name__
        self.record(event)


class RecordedGenerator:
    """One already-resolved production model for the entire campaign."""

    def __init__(self, inner, journal: CallJournal):
        self.inner, self.journal = inner, journal

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def complete(self, prompt, **kwargs):
        identity = self.journal.start("generator", prompt)
        try:
            result = self.inner.complete(prompt, **kwargs)
        except BaseException as exc:
            self.journal.finish(identity, "unconfirmed", error=exc)
            raise
        self.journal.finish(identity, "response_received")
        return result

    async def acomplete(self, prompt, **kwargs):
        identity = self.journal.start("generator", prompt)
        try:
            result = await self.inner.acomplete(prompt, **kwargs)
        except BaseException as exc:
            self.journal.finish(identity, "unconfirmed", error=exc)
            raise
        self.journal.finish(identity, "response_received")
        return result


class MockJudgeClient:
    """Use the same EVAL_JUDGE configuration as RAG, without a Ragas dependency."""

    def __init__(
        self, config: EvaluationLLMConfig, journal: CallJournal, *, client=None
    ):
        from openai import AsyncOpenAI

        self.config, self.journal = config, journal
        self.client = (
            client
            if client is not None
            else AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.api_base,
                timeout=90,
                max_retries=0,
            )
        )

    async def complete(self, prompt: str) -> str:
        identity = self.journal.start("judge", prompt)
        try:
            async with asyncio.timeout(90):
                reply = await self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=4096,
                    response_format={"type": "json_object"},
                    extra_body={"thinking": {"type": self.config.thinking_mode}}
                    if self.config.thinking_mode
                    else None,
                )
        except BaseException as exc:
            self.journal.finish(identity, "unconfirmed", error=exc)
            raise
        usage = getattr(reply, "usage", None)
        counters = (
            None
            if usage is None
            else {
                key: getattr(usage, key, None)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
        )
        # A complete but invalid answer was still received and may be billed.
        self.journal.finish(identity, "response_received", usage=counters)
        if len(reply.choices) != 1 or reply.choices[0].finish_reason != "stop":
            raise ValueError("judge response incomplete or ambiguous")
        text = reply.choices[0].message.content
        if not isinstance(text, str) or not text.strip():
            raise ValueError("judge response contains no text")
        return text

    async def aclose(self):
        await self.client.close()


def write_report(path: Path, payload: dict[str, Any]) -> None:
    """Atomic update of an exclusively reserved output. Never logs source text."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    created = False
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            created = True
            temporary.chmod(0o600)
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        # Only this campaign can own its output/temp names.
        if created and temporary.exists():
            temporary.unlink()
