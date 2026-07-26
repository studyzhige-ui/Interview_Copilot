"""OpenAI-compatible LLM factory for the optional evaluation suite."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


@dataclass(frozen=True)
class EvaluationLLMConfig:
    api_key: str
    api_base: str
    model: str


def load_evaluation_llm_config() -> EvaluationLLMConfig:
    """Load evaluator credentials independently from product user BYOK state."""
    load_dotenv()
    api_key = os.getenv("EVAL_LLM_API_KEY", "").strip()
    api_base = os.getenv("EVAL_LLM_API_BASE", "").strip()
    model = os.getenv("EVAL_LLM_MODEL", "").strip()
    missing = [
        name
        for name, value in (
            ("EVAL_LLM_API_KEY", api_key),
            ("EVAL_LLM_API_BASE", api_base),
            ("EVAL_LLM_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise EnvironmentError(
            "Evaluation LLM is not configured: " + ", ".join(missing)
        )
    return EvaluationLLMConfig(api_key=api_key, api_base=api_base, model=model)


def build_evaluation_llm(
    *,
    temperature: float = 0,
    max_tokens: int = 8192,
) -> ChatOpenAI:
    config = load_evaluation_llm_config()
    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.api_base,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def build_ragas_llm(
    *,
    temperature: float = 0,
    max_tokens: int = 8192,
):
    """Build the RAGAS adapter with the same evaluator configuration."""
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory

    config = load_evaluation_llm_config()
    client = AsyncOpenAI(api_key=config.api_key, base_url=config.api_base)
    return llm_factory(
        config.model,
        provider="openai",
        client=client,
        temperature=temperature,
        max_tokens=max_tokens,
    )
