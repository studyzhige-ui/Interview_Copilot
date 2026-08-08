"""OpenAI-compatible LLM factory for the optional evaluation suite."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


@dataclass(frozen=True)
class EvaluationLLMConfig:
    api_key: str
    api_base: str
    model: str
    thinking_mode: str | None


_DEEPSEEK_PRICING_USD_PER_MILLION = {
    "deepseek-v4-flash": {"cache_hit": 0.0028, "cache_miss": 0.14, "output": 0.28},
    "deepseek-v4-pro": {"cache_hit": 0.003625, "cache_miss": 0.435, "output": 0.87},
}
EVALUATION_GENERATOR_TEMPERATURE = 0
EVALUATION_GENERATOR_MAX_TOKENS = 1024
EVALUATION_GENERATOR_TIMEOUT_SECONDS = 90
EVALUATION_GENERATOR_MAX_RETRIES = 0
RAGAS_JUDGE_TEMPERATURE = 0
RAGAS_JUDGE_MAX_TOKENS = 4096
RAGAS_JUDGE_TIMEOUT_SECONDS = 90
RAGAS_JUDGE_MAX_RETRIES = 0


@dataclass
class TokenUsage:
    requests: int = 0
    input_tokens: int = 0
    cache_hit_input_tokens: int = 0
    cache_miss_input_tokens: int = 0
    output_tokens: int = 0
    checkpoint_path: Path | None = None
    repair_truncated_tail: bool = False

    def __post_init__(self) -> None:
        if self.checkpoint_path is None or not self.checkpoint_path.is_file():
            return
        raw_lines = self.checkpoint_path.read_text(encoding="utf-8").splitlines(
            keepends=True
        )
        for index, line in enumerate(raw_lines):
            if line.strip():
                try:
                    self._apply(json.loads(line))
                except json.JSONDecodeError as exc:
                    is_tail = index == len(raw_lines) - 1 and not line.endswith("\n")
                    if not is_tail:
                        raise ValueError(
                            f"Judge usage checkpoint is corrupt: {self.checkpoint_path}"
                        ) from exc
                    if not self.repair_truncated_tail:
                        raise RuntimeError(
                            "Judge usage checkpoint has a truncated final record with "
                            "unknown payment state; pass --retry-unknown-paid-calls "
                            "only after checking provider usage"
                        ) from exc
                    temporary = self.checkpoint_path.with_suffix(
                        self.checkpoint_path.suffix + ".repair"
                    )
                    with temporary.open("w", encoding="utf-8") as handle:
                        handle.writelines(raw_lines[:index])
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, self.checkpoint_path)
                    break

    def _apply(self, usage: dict[str, Any]) -> None:
        self.requests += int(usage.get("requests") or 0)
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.cache_hit_input_tokens += int(usage.get("cache_hit_input_tokens") or 0)
        self.cache_miss_input_tokens += int(usage.get("cache_miss_input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)

    def record(self, payload: dict[str, Any]) -> None:
        usage = payload.get("usage")
        event = {
            "requests": 1,
            "input_tokens": int(usage.get("prompt_tokens") or 0)
            if isinstance(usage, dict)
            else 0,
            "cache_hit_input_tokens": int(usage.get("prompt_cache_hit_tokens") or 0)
            if isinstance(usage, dict)
            else 0,
            "cache_miss_input_tokens": int(usage.get("prompt_cache_miss_tokens") or 0)
            if isinstance(usage, dict)
            else 0,
            "output_tokens": int(usage.get("completion_tokens") or 0)
            if isinstance(usage, dict)
            else 0,
        }
        self._apply(event)
        if self.checkpoint_path is not None:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with self.checkpoint_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def snapshot(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "cache_hit_input_tokens": self.cache_hit_input_tokens,
            "cache_miss_input_tokens": self.cache_miss_input_tokens,
            "output_tokens": self.output_tokens,
        }

    def summary(
        self,
        model: str,
        *,
        since: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        counters = {
            key: value - int((since or {}).get(key, 0))
            for key, value in self.snapshot().items()
        }
        pricing = _DEEPSEEK_PRICING_USD_PER_MILLION.get(model)
        estimated_cost = None
        if pricing is not None:
            uncategorized = max(
                0,
                counters["input_tokens"]
                - counters["cache_hit_input_tokens"]
                - counters["cache_miss_input_tokens"],
            )
            estimated_cost = (
                counters["cache_hit_input_tokens"] * pricing["cache_hit"]
                + (counters["cache_miss_input_tokens"] + uncategorized)
                * pricing["cache_miss"]
                + counters["output_tokens"] * pricing["output"]
            ) / 1_000_000
        return {
            **counters,
            "estimated_cost_usd": round(estimated_cost, 6)
            if estimated_cost is not None
            else None,
            "pricing_snapshot": "DeepSeek official 2026-08-07"
            if pricing is not None
            else None,
        }


@dataclass
class RagasJudge:
    llm: Any
    usage: TokenUsage
    client: Any

    async def aclose(self) -> None:
        await self.client.close()


def _explicit_config(prefix: str) -> EvaluationLLMConfig | None:
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    api_base = os.getenv(f"{prefix}_API_BASE", "").strip()
    model = os.getenv(f"{prefix}_MODEL", "").strip()
    if not any((api_key, api_base, model)):
        return None
    missing = [
        name
        for name, value in (
            (f"{prefix}_API_KEY", api_key),
            (f"{prefix}_API_BASE", api_base),
            (f"{prefix}_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise EnvironmentError("Evaluation model is incomplete: " + ", ".join(missing))
    return EvaluationLLMConfig(
        api_key=api_key,
        api_base=api_base,
        model=model,
        thinking_mode=_thinking_mode(api_base, model),
    )


def _thinking_mode(api_base: str, model: str) -> str | None:
    return (
        "disabled"
        if "api.deepseek.com" in api_base.lower()
        and model.lower().startswith("deepseek-")
        else None
    )


def load_generator_llm_config() -> EvaluationLLMConfig:
    """Load the answer generator without consulting user BYOK settings."""
    load_dotenv()
    explicit = _explicit_config("EVAL_GENERATOR")
    if explicit is not None:
        return explicit
    from app.core.internal_models import get_internal_model_profile

    profile = get_internal_model_profile("worker")
    api_key = os.getenv(profile.api_key_env, "").strip()
    if not api_key:
        raise EnvironmentError(f"Evaluation generator needs {profile.api_key_env}")
    return EvaluationLLMConfig(
        api_key=api_key,
        api_base=profile.api_base,
        model=profile.model,
        thinking_mode=_thinking_mode(profile.api_base, profile.model),
    )


def load_judge_llm_config() -> EvaluationLLMConfig:
    """Load the independently configured RAGAS judge."""
    load_dotenv()
    explicit = _explicit_config("EVAL_JUDGE")
    if explicit is not None:
        return explicit
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if api_key:
        return EvaluationLLMConfig(
            api_key=api_key,
            api_base="https://api.deepseek.com",
            model="deepseek-v4-pro",
            thinking_mode="disabled",
        )
    raise EnvironmentError(
        "RAGAS requires an independent judge: configure EVAL_JUDGE_* or "
        "DEEPSEEK_API_KEY"
    )


def build_evaluation_llm(
    *,
    temperature: float = EVALUATION_GENERATOR_TEMPERATURE,
    max_tokens: int = EVALUATION_GENERATOR_MAX_TOKENS,
) -> ChatOpenAI:
    config = load_generator_llm_config()
    extra_body = (
        {"thinking": {"type": config.thinking_mode}} if config.thinking_mode else None
    )
    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.api_base,
        temperature=temperature,
        max_tokens=max_tokens,
        stream_usage=True,
        timeout=EVALUATION_GENERATOR_TIMEOUT_SECONDS,
        max_retries=EVALUATION_GENERATOR_MAX_RETRIES,
        extra_body=extra_body,
    )


def build_ragas_judge(
    *,
    temperature: float = RAGAS_JUDGE_TEMPERATURE,
    max_tokens: int = RAGAS_JUDGE_MAX_TOKENS,
    usage_checkpoint_path: Path | None = None,
    retry_unknown_paid_calls: bool = False,
) -> RagasJudge:
    """Build the RAGAS adapter from the independently configured judge."""
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory

    config = load_judge_llm_config()
    usage = TokenUsage(
        checkpoint_path=usage_checkpoint_path,
        repair_truncated_tail=retry_unknown_paid_calls,
    )

    async def capture_usage(response: httpx.Response) -> None:
        await response.aread()
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        usage.record(payload if isinstance(payload, dict) else {})

    http_client = httpx.AsyncClient(event_hooks={"response": [capture_usage]})
    extra_body = (
        {"thinking": {"type": config.thinking_mode}} if config.thinking_mode else None
    )
    client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.api_base,
        timeout=RAGAS_JUDGE_TIMEOUT_SECONDS,
        max_retries=RAGAS_JUDGE_MAX_RETRIES,
        http_client=http_client,
    )
    llm = llm_factory(
        config.model,
        provider="openai",
        client=client,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )
    return RagasJudge(llm=llm, usage=usage, client=client)


def build_ragas_embeddings():
    """Adapt the production embedding singleton to RAGAS' modern API.

    Reusing ``Settings.embed_model`` keeps semantic answer metrics aligned with
    the deployed retriever and avoids loading a second copy of the local model.
    ``prepare_runtime`` must be called before this factory.
    """
    from llama_index.core import Settings
    from ragas.embeddings.base import BaseRagasEmbedding

    embed_model = Settings.embed_model

    class LlamaIndexRagasEmbedding(BaseRagasEmbedding):
        def embed_text(self, text: str, **_kwargs) -> list[float]:
            return embed_model.get_text_embedding(text)

        async def aembed_text(self, text: str, **_kwargs) -> list[float]:
            async_method = getattr(embed_model, "aget_text_embedding", None)
            if async_method is not None:
                return await async_method(text)
            return await asyncio.to_thread(embed_model.get_text_embedding, text)

        def embed_texts(self, texts: list[str], **_kwargs) -> list[list[float]]:
            return embed_model.get_text_embedding_batch(texts)

        async def aembed_texts(self, texts: list[str], **_kwargs) -> list[list[float]]:
            async_method = getattr(embed_model, "aget_text_embedding_batch", None)
            if async_method is not None:
                return await async_method(texts)
            return await asyncio.to_thread(embed_model.get_text_embedding_batch, texts)

    return LlamaIndexRagasEmbedding()
