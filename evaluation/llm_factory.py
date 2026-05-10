"""DeepSeek LLM factory for evaluation scripts.

Centralizes LLM construction so every evaluation module uses the same
DeepSeek V4 model with identical parameters.

RAGAS v0.4.3 requires ``llm_factory()`` with an OpenAI-compatible client
instead of the deprecated ``LangchainLLMWrapper``.
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI


def _require_env(key: str) -> str:
    value = os.environ.get(key, "")
    if not value:
        # Try loading from .env lazily
        try:
            from dotenv import load_dotenv

            load_dotenv()
            value = os.environ.get(key, "")
        except ImportError:
            pass
    if not value:
        raise EnvironmentError(f"Environment variable '{key}' is required but not set.")
    return value


def build_deepseek_llm(
    *,
    temperature: float = 0,
    max_tokens: int = 8192,
) -> ChatOpenAI:
    """Build a ChatOpenAI instance pointing to DeepSeek V4."""
    return ChatOpenAI(
        model="deepseek-chat",
        api_key=_require_env("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        temperature=temperature,
        max_tokens=max_tokens,
    )


def build_ragas_llm(
    *,
    temperature: float = 0,
    max_tokens: int = 8192,
):
    """Build a RAGAS v0.4.3 compatible InstructorLLM via llm_factory().

    Uses DeepSeek's OpenAI-compatible API endpoint.
    """
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory

    client = AsyncOpenAI(
        api_key=_require_env("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )
    return llm_factory(
        "deepseek-chat",
        provider="openai",
        client=client,
        temperature=temperature,
        max_tokens=max_tokens,
    )
