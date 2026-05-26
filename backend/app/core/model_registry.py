import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from llama_index.llms.openai_like import OpenAILike
from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelProfile:
    id: str
    provider: str
    display_name: str
    model: str
    api_base: str
    api_key_env: str
    supports_function_calling: bool = False
    description: str = ""
    context_window: int = 128_000
    max_output_tokens: int = 4_096


ROLE_DEFAULTS: dict[str, str] = {
    # Three user-facing roles:
    #   primary        — chat / debrief default model (must support function calling
    #                    when the user toggles the AGENT panel button)
    #   agent          — agentic / tool-use chains (function calling required)
    #   mock_interview — drives mock-interview plan + interviewer responses;
    #                    aliased internally as `fast` for back-compat (older
    #                    code paths still read `fast`).
    "primary": "deepseek-v4-flash",
    "fast": "deepseek-v4-flash",
    "agent": "deepseek-v4-pro",
    "mock_interview": "deepseek-v4-flash",
}


MODEL_PROFILES: dict[str, ModelProfile] = {
    "deepseek-v4-flash": ModelProfile(
        id="deepseek-v4-flash",
        provider="deepseek",
        display_name="DeepSeek V4 Flash",
        model="deepseek-v4-flash",
        api_base="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        supports_function_calling=True,
        description=(
            "Default fast DeepSeek V4 model for normal chat, rewrite, router, "
            "memory, and economical generation."
        ),
        context_window=1_000_000,
        max_output_tokens=16_384,
    ),
    "deepseek-v4-pro": ModelProfile(
        id="deepseek-v4-pro",
        provider="deepseek",
        display_name="DeepSeek V4 Pro",
        model="deepseek-v4-pro",
        api_base="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        supports_function_calling=True,
        description=(
            "Stronger DeepSeek V4 model for tool-using agent flows and harder "
            "reasoning tasks."
        ),
        context_window=1_000_000,
        max_output_tokens=16_384,
    ),
    "deepseek-chat": ModelProfile(
        id="deepseek-chat",
        provider="deepseek",
        display_name="DeepSeek Chat",
        model="deepseek-chat",
        api_base="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        supports_function_calling=True,
        description=(
            "Legacy DeepSeek alias. DeepSeek currently routes this to V4 Flash, "
            "but it is scheduled for retirement."
        ),
    ),
    "deepseek-reasoner": ModelProfile(
        id="deepseek-reasoner",
        provider="deepseek",
        display_name="DeepSeek Reasoner",
        model="deepseek-reasoner",
        api_base="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        supports_function_calling=False,
        description=(
            "Legacy DeepSeek reasoning alias. DeepSeek currently routes this to "
            "V4 Flash thinking mode, but it is scheduled for retirement."
        ),
    ),
    "nvidia-meta-llama-3.1-8b": ModelProfile(
        id="nvidia-meta-llama-3.1-8b",
        provider="nvidia",
        display_name="NVIDIA Meta Llama 3.1 8B Instruct",
        model="meta/llama-3.1-8b-instruct",
        api_base=os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1"),
        api_key_env="NVIDIA_API_KEY",
        supports_function_calling=False,
        description="Validated NVIDIA serverless model with fast response for general chat testing.",
    ),
    "nvidia-meta-llama-3.2-1b": ModelProfile(
        id="nvidia-meta-llama-3.2-1b",
        provider="nvidia",
        display_name="NVIDIA Meta Llama 3.2 1B Instruct",
        model="meta/llama-3.2-1b-instruct",
        api_base=os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1"),
        api_key_env="NVIDIA_API_KEY",
        supports_function_calling=False,
        description="Very small NVIDIA serverless model, useful for smoke tests and low-latency prototyping.",
    ),
    "nvidia-google-gemma-3-4b": ModelProfile(
        id="nvidia-google-gemma-3-4b",
        provider="nvidia",
        display_name="NVIDIA Google Gemma 3 4B IT",
        model="google/gemma-3-4b-it",
        api_base=os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1"),
        api_key_env="NVIDIA_API_KEY",
        supports_function_calling=False,
        description="Validated NVIDIA-hosted Gemma profile with stable text completion behavior.",
    ),
    "nvidia-google-gemma-2-2b": ModelProfile(
        id="nvidia-google-gemma-2-2b",
        provider="nvidia",
        display_name="NVIDIA Google Gemma 2 2B IT",
        model="google/gemma-2-2b-it",
        api_base=os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1"),
        api_key_env="NVIDIA_API_KEY",
        supports_function_calling=False,
        description="Validated NVIDIA-hosted Gemma 2 profile with quick responses.",
    ),
    "nvidia-qwen2.5-coder-32b": ModelProfile(
        id="nvidia-qwen2.5-coder-32b",
        provider="nvidia",
        display_name="NVIDIA Qwen2.5 Coder 32B Instruct",
        model="qwen/qwen2.5-coder-32b-instruct",
        api_base=os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1"),
        api_key_env="NVIDIA_API_KEY",
        supports_function_calling=False,
        description="Validated NVIDIA-hosted coding model for code-oriented chat tasks.",
    ),
    "nvidia-deepseek-v3.1-terminus": ModelProfile(
        id="nvidia-deepseek-v3.1-terminus",
        provider="nvidia",
        display_name="NVIDIA DeepSeek V3.1 Terminus",
        model="deepseek-ai/deepseek-v3.1-terminus",
        api_base=os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1"),
        api_key_env="NVIDIA_API_KEY",
        supports_function_calling=False,
        description="Large DeepSeek profile on NVIDIA API Catalog; may exhibit long cold-start latency.",
    ),
    "nvidia-deepseek-v3.2": ModelProfile(
        id="nvidia-deepseek-v3.2",
        provider="nvidia",
        display_name="NVIDIA DeepSeek V3.2",
        model="deepseek-ai/deepseek-v3.2",
        api_base=os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1"),
        api_key_env="NVIDIA_API_KEY",
        supports_function_calling=False,
        description="Large DeepSeek V3.2 profile on NVIDIA API Catalog; suitable for manual experiments, but currently high latency.",
    ),

    # ── OpenAI ───────────────────────────────────────────────────────────
    # Order: newest first. Model ids from LiteLLM model_cost (litellm.model_cost).
    "openai-gpt-5.2": ModelProfile(
        id="openai-gpt-5.2", provider="openai", display_name="GPT-5.2", model="gpt-5.2",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        description="最新 GPT-5 系列旗舰。",
    ),
    "openai-gpt-5.1": ModelProfile(
        id="openai-gpt-5.1", provider="openai", display_name="GPT-5.1", model="gpt-5.1",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        description="GPT-5 系列稳定版。",
    ),
    "openai-gpt-5": ModelProfile(
        id="openai-gpt-5", provider="openai", display_name="GPT-5", model="gpt-5",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        description="GPT-5 首发版。",
    ),
    "openai-o4-mini": ModelProfile(
        id="openai-o4-mini", provider="openai", display_name="o4-mini", model="o4-mini",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        description="o-series 推理小杯，新一代。",
    ),
    "openai-o3-pro": ModelProfile(
        id="openai-o3-pro", provider="openai", display_name="o3 Pro", model="o3-pro",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        description="o3 推理旗舰增强版。",
    ),
    "openai-o3": ModelProfile(
        id="openai-o3", provider="openai", display_name="o3", model="o3",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        description="o-series 推理主力。",
    ),
    "openai-gpt-4.1": ModelProfile(
        id="openai-gpt-4.1", provider="openai", display_name="GPT-4.1", model="gpt-4.1",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        description="4.1 系列旗舰，长上下文。",
    ),
    "openai-gpt-4.1-mini": ModelProfile(
        id="openai-gpt-4.1-mini", provider="openai", display_name="GPT-4.1 Mini", model="gpt-4.1-mini",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        description="4.1 小杯，便宜。",
    ),
    "openai-gpt-4o": ModelProfile(
        id="openai-gpt-4o", provider="openai", display_name="GPT-4o", model="gpt-4o",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        description="旗舰多模态，128k 上下文。",
    ),
    "openai-gpt-4o-mini": ModelProfile(
        id="openai-gpt-4o-mini", provider="openai", display_name="GPT-4o Mini", model="gpt-4o-mini",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        description="性价比首选。",
    ),

    # ── Anthropic ────────────────────────────────────────────────────────
    # 最新到 Claude 4.7 系列（Opus 4.7 + Sonnet 4.6 + Haiku 4.5）。
    "anthropic-claude-opus-4-7": ModelProfile(
        id="anthropic-claude-opus-4-7", provider="anthropic", display_name="Claude Opus 4.7", model="claude-opus-4-7",
        api_base=os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1"),
        api_key_env="ANTHROPIC_API_KEY", supports_function_calling=True,
        description="Opus 4.7 旗舰，强推理 + 1M 上下文。",
    ),
    "anthropic-claude-opus-4-7-1m": ModelProfile(
        id="anthropic-claude-opus-4-7-1m", provider="anthropic", display_name="Claude Opus 4.7 (1M)", model="claude-opus-4-7[1m]",
        api_base=os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1"),
        api_key_env="ANTHROPIC_API_KEY", supports_function_calling=True,
        description="Opus 4.7 长上下文版（1M tokens）。",
    ),
    "anthropic-claude-sonnet-4-6": ModelProfile(
        id="anthropic-claude-sonnet-4-6", provider="anthropic", display_name="Claude Sonnet 4.6", model="claude-sonnet-4-6",
        api_base=os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1"),
        api_key_env="ANTHROPIC_API_KEY", supports_function_calling=True,
        description="Sonnet 4.6 主力工作模型。",
    ),
    "anthropic-claude-haiku-4-5": ModelProfile(
        id="anthropic-claude-haiku-4-5", provider="anthropic", display_name="Claude Haiku 4.5", model="claude-haiku-4-5-20251001",
        api_base=os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1"),
        api_key_env="ANTHROPIC_API_KEY", supports_function_calling=True,
        description="Haiku 最新，最便宜+最快。",
    ),
    "anthropic-claude-sonnet-4-5": ModelProfile(
        id="anthropic-claude-sonnet-4-5", provider="anthropic", display_name="Claude Sonnet 4.5", model="claude-sonnet-4-5",
        api_base=os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1"),
        api_key_env="ANTHROPIC_API_KEY", supports_function_calling=True,
        description="Sonnet 4.5（上一稳定版）。",
    ),
    "anthropic-claude-opus-4-1": ModelProfile(
        id="anthropic-claude-opus-4-1", provider="anthropic", display_name="Claude Opus 4.1", model="claude-opus-4-1",
        api_base=os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1"),
        api_key_env="ANTHROPIC_API_KEY", supports_function_calling=True,
        description="Opus 4.1（上一代）。",
    ),
    "anthropic-claude-3-7-sonnet": ModelProfile(
        id="anthropic-claude-3-7-sonnet", provider="anthropic", display_name="Claude 3.7 Sonnet", model="claude-3-7-sonnet-latest",
        api_base=os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1"),
        api_key_env="ANTHROPIC_API_KEY", supports_function_calling=True,
        description="3.7 上代主力。",
    ),

    # ── Google Gemini ────────────────────────────────────────────────────
    "google-gemini-3-pro": ModelProfile(
        id="google-gemini-3-pro", provider="google", display_name="Gemini 3 Pro", model="gemini-3-pro",
        api_base=os.getenv("GOOGLE_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai"),
        api_key_env="GOOGLE_API_KEY", supports_function_calling=True,
        description="Gemini 3 系列旗舰。",
    ),
    "google-gemini-2.5-pro": ModelProfile(
        id="google-gemini-2.5-pro", provider="google", display_name="Gemini 2.5 Pro", model="gemini-2.5-pro",
        api_base=os.getenv("GOOGLE_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai"),
        api_key_env="GOOGLE_API_KEY", supports_function_calling=True,
        description="2.5 旗舰，2M 上下文。",
    ),
    "google-gemini-2.5-flash": ModelProfile(
        id="google-gemini-2.5-flash", provider="google", display_name="Gemini 2.5 Flash", model="gemini-2.5-flash",
        api_base=os.getenv("GOOGLE_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai"),
        api_key_env="GOOGLE_API_KEY", supports_function_calling=True,
        description="2.5 快速款。",
    ),
    "google-gemini-2.5-flash-lite": ModelProfile(
        id="google-gemini-2.5-flash-lite", provider="google", display_name="Gemini 2.5 Flash Lite", model="gemini-2.5-flash-lite",
        api_base=os.getenv("GOOGLE_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai"),
        api_key_env="GOOGLE_API_KEY", supports_function_calling=True,
        description="2.5 极速极便宜款。",
    ),
    "google-gemini-2.0-flash": ModelProfile(
        id="google-gemini-2.0-flash", provider="google", display_name="Gemini 2.0 Flash", model="gemini-2.0-flash",
        api_base=os.getenv("GOOGLE_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai"),
        api_key_env="GOOGLE_API_KEY", supports_function_calling=True,
        description="2.0 经典快速款。",
    ),

    # ── Qwen / DashScope（阿里通义） ─────────────────────────────────────
    "qwen3-max": ModelProfile(
        id="qwen3-max", provider="qwen", display_name="Qwen3 Max", model="qwen3-max",
        api_base=os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key_env="DASHSCOPE_API_KEY", supports_function_calling=True,
        description="Qwen3 旗舰。",
    ),
    "qwen3-235b": ModelProfile(
        id="qwen3-235b", provider="qwen", display_name="Qwen3 235B Thinking", model="qwen3-235b-a22b-thinking-2507",
        api_base=os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key_env="DASHSCOPE_API_KEY", supports_function_calling=True,
        description="Qwen3 235B MoE 推理版。",
    ),
    "qwen3-coder": ModelProfile(
        id="qwen3-coder", provider="qwen", display_name="Qwen3 Coder", model="qwen3-coder-plus",
        api_base=os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key_env="DASHSCOPE_API_KEY", supports_function_calling=True,
        description="代码专用旗舰。",
    ),
    "qwen3-vl": ModelProfile(
        id="qwen3-vl", provider="qwen", display_name="Qwen3 VL", model="qwen3-vl-plus",
        api_base=os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key_env="DASHSCOPE_API_KEY", supports_function_calling=False,
        description="多模态旗舰。",
    ),
    "qwen-plus": ModelProfile(
        id="qwen-plus", provider="qwen", display_name="Qwen Plus", model="qwen-plus-latest",
        api_base=os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key_env="DASHSCOPE_API_KEY", supports_function_calling=True,
        description="中规格性价比款。",
    ),
    "qwen-turbo": ModelProfile(
        id="qwen-turbo", provider="qwen", display_name="Qwen Turbo", model="qwen-turbo-latest",
        api_base=os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key_env="DASHSCOPE_API_KEY", supports_function_calling=True,
        description="快速款，超长上下文。",
    ),

    # ── Moonshot Kimi ────────────────────────────────────────────────────
    "moonshot-kimi-k2-thinking": ModelProfile(
        id="moonshot-kimi-k2-thinking", provider="moonshot", display_name="Kimi K2 Thinking", model="kimi-k2-thinking",
        api_base=os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1"),
        api_key_env="MOONSHOT_API_KEY", supports_function_calling=True,
        description="Kimi 推理旗舰。",
    ),
    "moonshot-kimi-k2.5": ModelProfile(
        id="moonshot-kimi-k2.5", provider="moonshot", display_name="Kimi K2.5", model="kimi-k2.5",
        api_base=os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1"),
        api_key_env="MOONSHOT_API_KEY", supports_function_calling=True,
        description="K2.5 最新。",
    ),
    "moonshot-kimi-k2": ModelProfile(
        id="moonshot-kimi-k2", provider="moonshot", display_name="Kimi K2", model="kimi-k2-0905-preview",
        api_base=os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1"),
        api_key_env="MOONSHOT_API_KEY", supports_function_calling=True,
        description="K2 MoE 主力。",
    ),
    "moonshot-v1-128k": ModelProfile(
        id="moonshot-v1-128k", provider="moonshot", display_name="Moonshot V1 128k", model="moonshot-v1-128k",
        api_base=os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1"),
        api_key_env="MOONSHOT_API_KEY", supports_function_calling=True,
        description="V1 大上下文。",
    ),

    # ── Zhipu GLM ────────────────────────────────────────────────────────
    "zhipu-glm-5": ModelProfile(
        id="zhipu-glm-5", provider="zhipu", display_name="GLM-5", model="glm-5",
        api_base=os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
        api_key_env="ZHIPU_API_KEY", supports_function_calling=True,
        description="智谱 GLM-5 最新旗舰。",
    ),
    "zhipu-glm-4.7": ModelProfile(
        id="zhipu-glm-4.7", provider="zhipu", display_name="GLM-4.7", model="glm-4.7",
        api_base=os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
        api_key_env="ZHIPU_API_KEY", supports_function_calling=True,
        description="GLM 4.7 主力。",
    ),
    "zhipu-glm-4.7-flash": ModelProfile(
        id="zhipu-glm-4.7-flash", provider="zhipu", display_name="GLM-4.7 Flash", model="glm-4.7-flash",
        api_base=os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
        api_key_env="ZHIPU_API_KEY", supports_function_calling=True,
        description="4.7 快速款。",
    ),
    "zhipu-glm-4.6": ModelProfile(
        id="zhipu-glm-4.6", provider="zhipu", display_name="GLM-4.6", model="glm-4.6",
        api_base=os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
        api_key_env="ZHIPU_API_KEY", supports_function_calling=True,
        description="GLM 4.6 稳定版。",
    ),
    "zhipu-glm-4.5": ModelProfile(
        id="zhipu-glm-4.5", provider="zhipu", display_name="GLM-4.5", model="glm-4.5",
        api_base=os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
        api_key_env="ZHIPU_API_KEY", supports_function_calling=True,
        description="GLM 4.5 通用款。",
    ),
    "zhipu-glm-z1-preview": ModelProfile(
        id="zhipu-glm-z1-preview", provider="zhipu", display_name="GLM-Z1 Preview", model="glm-zero-preview",
        api_base=os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
        api_key_env="ZHIPU_API_KEY", supports_function_calling=False,
        description="推理模型（类 o1）。",
    ),

    # ── Xiaomi MiMo（小米 Token Plan 官方网关，OpenAI 兼容） ────────────
    # 默认指向小米 Token Plan（用户提供）。如需走 ModelScope / OpenRouter，
    # 设置环境变量 MIMO_API_BASE 覆盖。
    "xiaomi-mimo-v2.5-pro": ModelProfile(
        id="xiaomi-mimo-v2.5-pro", provider="xiaomi", display_name="MiMo v2.5 Pro", model="mimo-v2.5-pro",
        api_base=os.getenv("MIMO_API_BASE", "https://token-plan-cn.xiaomimimo.com/v1"),
        api_key_env="MIMO_API_KEY", supports_function_calling=True,
        description="MiMo V2.5 旗舰版（最新）。",
    ),
    "xiaomi-mimo-v2.5": ModelProfile(
        id="xiaomi-mimo-v2.5", provider="xiaomi", display_name="MiMo v2.5", model="mimo-v2.5",
        api_base=os.getenv("MIMO_API_BASE", "https://token-plan-cn.xiaomimimo.com/v1"),
        api_key_env="MIMO_API_KEY", supports_function_calling=True,
        description="MiMo V2.5 主力。",
    ),
    "xiaomi-mimo-v2.5-flash": ModelProfile(
        id="xiaomi-mimo-v2.5-flash", provider="xiaomi", display_name="MiMo v2.5 Flash", model="mimo-v2.5-flash",
        api_base=os.getenv("MIMO_API_BASE", "https://token-plan-cn.xiaomimimo.com/v1"),
        api_key_env="MIMO_API_KEY", supports_function_calling=True,
        description="MiMo V2.5 快速款。",
    ),
    "xiaomi-mimo-v2-pro": ModelProfile(
        id="xiaomi-mimo-v2-pro", provider="xiaomi", display_name="MiMo v2 Pro", model="mimo-v2-pro",
        api_base=os.getenv("MIMO_API_BASE", "https://token-plan-cn.xiaomimimo.com/v1"),
        api_key_env="MIMO_API_KEY", supports_function_calling=True,
        description="MiMo V2 旗舰。",
    ),
    "xiaomi-mimo-v2-flash": ModelProfile(
        id="xiaomi-mimo-v2-flash", provider="xiaomi", display_name="MiMo v2 Flash", model="mimo-v2-flash",
        api_base=os.getenv("MIMO_API_BASE", "https://token-plan-cn.xiaomimimo.com/v1"),
        api_key_env="MIMO_API_KEY", supports_function_calling=True,
        description="MiMo V2 快速款。",
    ),
    "xiaomi-mimo-vl": ModelProfile(
        id="xiaomi-mimo-vl", provider="xiaomi", display_name="MiMo VL", model="mimo-vl",
        api_base=os.getenv("MIMO_API_BASE", "https://token-plan-cn.xiaomimimo.com/v1"),
        api_key_env="MIMO_API_KEY", supports_function_calling=False,
        description="多模态（图文）。",
    ),
}


_selection_lock = Lock()
_llm_cache: dict[tuple[str, str], Any] = {}


def _normalize_selection(raw: dict[str, str]) -> dict[str, str]:
    selection = dict(ROLE_DEFAULTS)
    for role in ROLE_DEFAULTS:
        candidate = raw.get(role)
        if candidate in {"deepseek-chat", "deepseek-reasoner"}:
            continue
        if candidate in MODEL_PROFILES:
            selection[role] = candidate
    agent_profile = MODEL_PROFILES[selection["agent"]]
    if not agent_profile.supports_function_calling:
        selection["agent"] = ROLE_DEFAULTS["agent"]
    return selection


def _load_user_selection(user_id: str) -> dict[str, str]:
    """Read a user's persisted ``model_selection_json`` from the DB.

    Returns ROLE_DEFAULTS if the user row has no selection saved
    (NULL column), the JSON is corrupt, or the lookup itself fails.
    Lookup failures are logged but never crash the caller — model
    resolution must always return SOMETHING usable, even if it's
    just the defaults.
    """
    from app.db.database import SessionLocal
    from app.models.user import User

    try:
        with SessionLocal() as db:
            row = (
                db.query(User.model_selection_json)
                .filter(User.username == user_id)
                .first()
            )
        if row is None or not row[0]:
            return dict(ROLE_DEFAULTS)
        data = json.loads(row[0])
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to load model selection for user=%s: %s", user_id, exc,
        )
    return dict(ROLE_DEFAULTS)


def _save_user_selection(user_id: str, selection: dict[str, str]) -> None:
    from app.db.database import SessionLocal
    from app.models.user import User

    payload = json.dumps(selection, ensure_ascii=False)
    with SessionLocal() as db:
        db.query(User).filter(User.username == user_id).update(
            {"model_selection_json": payload},
            synchronize_session=False,
        )
        db.commit()


def get_runtime_selection(user_id: str | None = None) -> dict[str, str]:
    """Return the active model selection for ``user_id``.

    Without ``user_id`` (startup contexts like RAG-embedding init or
    the LlamaIndex global ``Settings.llm``) returns ROLE_DEFAULTS —
    those code paths don't have a user context and can't be per-
    user. With ``user_id`` reads ``users.model_selection_json`` and
    falls back to defaults on any error.
    """
    with _selection_lock:
        if user_id is None:
            return dict(ROLE_DEFAULTS)
        return _normalize_selection(_load_user_selection(user_id))


def persist_runtime_selection(
    selection: dict[str, str], user_id: str,
) -> dict[str, str]:
    """Save ``selection`` for ``user_id`` to the DB. Returns the
    normalized form actually written (invalid model ids stripped,
    fallback to ROLE_DEFAULTS for unrecognised roles)."""
    normalized = _normalize_selection(selection)
    with _selection_lock:
        _save_user_selection(user_id, normalized)
        # Clear the (role, profile_id) → LLM-instance cache so the
        # user's next chat constructs a fresh LLM honouring the new
        # selection. The cache is process-wide — harmless to clear
        # all entries even when only one user changed; under typical
        # cardinality (4 roles × ~10 profiles = 40 entries) the
        # rebuild on next call is microseconds.
        _llm_cache.clear()
    return normalized


def update_runtime_selection(
    updates: dict[str, str], user_id: str,
) -> dict[str, str]:
    current = get_runtime_selection(user_id)
    current.update({k: v for k, v in updates.items() if v is not None})
    return persist_runtime_selection(current, user_id)


def get_profile(profile_id: str) -> ModelProfile:
    if profile_id not in MODEL_PROFILES:
        raise ValueError(f"Unknown model profile: {profile_id}")
    return MODEL_PROFILES[profile_id]


def get_profile_for_role(role: str, user_id: str | None = None) -> ModelProfile:
    selection = get_runtime_selection(user_id)
    profile_id = selection.get(role, ROLE_DEFAULTS[role])
    return get_profile(profile_id)


def resolve_api_key(profile: ModelProfile, user_id: str | None = None) -> str:
    """Resolution priority:
       1) user_api_keys row for (user_id, provider) — encrypted DB storage
       2) os.environ[profile.api_key_env] — legacy .env path
    Both empty → ""; callers downstream will fail at provider auth time.
    """
    if user_id:
        try:
            from app.services.user_api_key_service import get_user_api_key_plaintext
            user_key = get_user_api_key_plaintext(user_id, profile.provider)
            if user_key:
                return user_key
        except Exception as exc:  # noqa: BLE001
            logger.warning("user_api_key lookup failed: %s", exc)
    return os.getenv(profile.api_key_env, "")


# ── AsyncOpenAI client cache ────────────────────────────────────────────
# Direct OpenAI-protocol calls (e.g. the /models/ping endpoint, ad-hoc
# completions outside LlamaIndex) used to spin up a fresh AsyncOpenAI per
# request. At dozens of pings/sec that exhausts TCP source ports and adds
# ~50ms of TLS handshake per call. Cache by ``(user_id, profile_id)`` and
# keep a fingerprint of the resolved key so a silently-rotated key trips
# a rebuild on the next call instead of using stale auth.
#
# Scope: PROCESS-LOCAL. With ``uvicorn --workers N`` each worker keeps its
# own cache — N times the memory but trivially small (few KB per client),
# and request affinity isn't required so this is fine. If you ever need
# truly shared connections (e.g. you have 64 workers and want to keep the
# OpenAI keep-alive pool warm globally), you'd move the http transport
# layer into a shared aiohttp/httpx connector — out of scope here.
#
# Bound: ``_ASYNC_OPENAI_CACHE_MAX`` entries, LRU-evicted on overflow.
# 256 covers ~10 active users × 25 profiles each. Increase if you have a
# burstier mix; memory cost is ~5 KB / client.
import hashlib
from collections import OrderedDict

_ASYNC_OPENAI_CACHE_MAX = 256
_async_openai_cache: "OrderedDict[tuple[str | None, str], tuple[str, AsyncOpenAI]]" = OrderedDict()


def _key_fingerprint(api_key: str) -> str:
    # Truncated SHA-256 so we never persist the raw key, even in memory keys.
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16] if api_key else ""


def _close_client_quietly(client: AsyncOpenAI) -> None:
    """Best-effort cleanup of a cached AsyncOpenAI when we drop it.

    Newer ``openai-python`` versions make ``close()`` a coroutine; older
    ones expose a sync ``close`` and an async ``aclose``. We try the
    async path first because that's what the current SDK ships, and
    only call the sync path when we know we're outside an event loop.
    Failure to close is non-fatal — Python GC + httpx will eventually
    release the underlying connection pool.
    """
    import asyncio

    aclose = getattr(client, "aclose", None) or getattr(client, "close", None)
    if not callable(aclose):
        return
    try:
        result = aclose()
    except Exception:  # noqa: BLE001
        return
    if asyncio.iscoroutine(result):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and not loop.is_closed():
            # Schedule on the live loop and forget — close is best-effort.
            loop.create_task(result)
        else:
            # No loop to schedule on → cancel the coroutine to suppress the
            # "coroutine was never awaited" RuntimeWarning. The HTTP client
            # will be cleaned up by GC.
            result.close()


def get_async_openai_client(profile: ModelProfile, user_id: str | None = None) -> AsyncOpenAI:
    """Return a process-cached ``AsyncOpenAI`` for ``profile`` + ``user_id``.

    Auto-invalidates if the resolved key changes since the last call (e.g.
    the user updated their stored key but ``clear_llm_cache_for_provider``
    didn't fire on this exact tuple). LRU-bounded — least-recently-used
    entries get evicted once the cache passes ``_ASYNC_OPENAI_CACHE_MAX``.
    """
    api_key = resolve_api_key(profile, user_id=user_id)
    fp = _key_fingerprint(api_key)
    cache_key = (user_id, profile.id)
    with _selection_lock:
        cached = _async_openai_cache.get(cache_key)
        if cached is not None and cached[0] == fp:
            # LRU touch — move to MRU end so eviction skips it.
            _async_openai_cache.move_to_end(cache_key)
            return cached[1]
        # Key changed (rotation) → drop the stale client before building new.
        if cached is not None:
            _close_client_quietly(cached[1])
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=profile.api_base,
            timeout=30.0,
        )
        _async_openai_cache[cache_key] = (fp, client)
        _async_openai_cache.move_to_end(cache_key)
        # Evict from the LRU (oldest) end if we've overshot the cap.
        while len(_async_openai_cache) > _ASYNC_OPENAI_CACHE_MAX:
            _, evicted = _async_openai_cache.popitem(last=False)
            _close_client_quietly(evicted[1])
        return client


def clear_llm_cache_for_provider(provider: str) -> None:
    """Drop cached LLM + AsyncOpenAI instances for ``provider``.

    Called after a user changes their API key so the next LLM call rebuilds
    with the new credentials instead of reusing the old cached client.
    """
    with _selection_lock:
        # LlamaIndex LLM cache: key is (role, profile_id)
        to_drop_llm = [
            key for key in _llm_cache
            if key[1] in MODEL_PROFILES and MODEL_PROFILES[key[1]].provider == provider
        ]
        for k in to_drop_llm:
            _llm_cache.pop(k, None)
        # AsyncOpenAI cache: key is (user_id, profile_id). Tear down each
        # evicted client so the underlying TCP pool gets released promptly.
        to_drop_async = [
            key for key in _async_openai_cache
            if key[1] in MODEL_PROFILES and MODEL_PROFILES[key[1]].provider == provider
        ]
        for k in to_drop_async:
            entry = _async_openai_cache.pop(k, None)
            if entry is not None:
                _close_client_quietly(entry[1])


def profile_ready(profile: ModelProfile, user_id: str | None = None) -> bool:
    """A profile is ready when *some* key resolves for it.

    With ``user_id`` we also check the encrypted ``user_api_keys`` row, so a
    user who saved their key in-app is treated as configured even when the
    corresponding ``.env`` var is empty. Without ``user_id`` we fall back to
    env-only (legacy callers, ping endpoint, etc).
    """
    return bool(resolve_api_key(profile, user_id=user_id)) and bool(profile.model.strip())


def _provider_specs_for_discovery() -> list[tuple[str, str, str]]:
    """Build (provider, api_base, api_key_env) tuples from MODEL_PROFILES,
    deduped on provider id. Used by the discovery service to know which
    vendors to query.
    """
    seen: dict[str, tuple[str, str, str]] = {}
    for prof in MODEL_PROFILES.values():
        if prof.provider in seen:
            continue
        seen[prof.provider] = (prof.provider, prof.api_base, prof.api_key_env)
    return list(seen.values())


def _serialize_profile(profile: ModelProfile, selection: dict, user_id: str | None) -> dict[str, Any]:
    return {
        **asdict(profile),
        "ready": profile_ready(profile, user_id=user_id),
        "selected_for": [role for role, pid in selection.items() if pid == profile.id],
        "auto_discovered": False,
    }


def _synthesize_discovered_profile(provider: str, model: str, api_base: str, api_key_env: str) -> ModelProfile:
    """Build a ModelProfile for a vendor-discovered model that has no curated entry.

    Sensible defaults: assume function calling is supported (most chat models
    do), 128 K context window, 8 K max output. Operators who care about the
    exact metadata for a specific model can promote it to MODEL_PROFILES.
    """
    safe = re.sub(r"[^A-Za-z0-9]+", "-", model).strip("-").lower()
    return ModelProfile(
        id=f"{provider}-{safe}-auto",
        provider=provider,
        display_name=model,
        model=model,
        api_base=api_base,
        api_key_env=api_key_env,
        supports_function_calling=True,
        description=f"Auto-discovered via {provider}/v1/models. Promote to MODEL_PROFILES for curated metadata.",
        context_window=128_000,
        max_output_tokens=8_192,
    )


def list_profiles(user_id: str | None = None) -> list[dict[str, Any]]:
    """Return curated profiles only (sync, no discovery side-effects).

    Use ``list_profiles_with_discovery()`` from async contexts to also
    surface vendor-listed models that aren't in the curated set.
    """
    selection = get_runtime_selection(user_id)
    return [_serialize_profile(p, selection, user_id) for p in MODEL_PROFILES.values()]


async def list_profiles_with_discovery(
    user_id: str | None = None,
    *,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Curated profiles + every chat model the vendors currently advertise.

    Discovery is best-effort and cached in Redis 24h — see
    ``app.services.model_catalog_service``. Curated entries always take
    precedence over auto-discovered ones with the same (provider, model)
    so manually-written display_name / description aren't clobbered.
    """
    from app.services.model_catalog_service import discover_all

    selection = get_runtime_selection(user_id)
    out: list[dict[str, Any]] = [
        _serialize_profile(p, selection, user_id) for p in MODEL_PROFILES.values()
    ]
    seen_pairs = {(p.provider, p.model) for p in MODEL_PROFILES.values()}

    discovered = await discover_all(
        _provider_specs_for_discovery(), force_refresh=force_refresh,
    )
    for provider, models in discovered.items():
        for m in models:
            if (m.provider, m.model) in seen_pairs:
                continue
            seen_pairs.add((m.provider, m.model))
            synth = _synthesize_discovered_profile(
                m.provider, m.model, m.api_base, m.api_key_env,
            )
            payload = _serialize_profile(synth, selection, user_id)
            payload["auto_discovered"] = True
            out.append(payload)

    return out


def validate_role_update(role: str, profile_id: str, user_id: str | None = None) -> ModelProfile:
    profile = get_profile(profile_id)
    if not profile_ready(profile, user_id=user_id):
        raise ValueError(
            f"Model profile '{profile_id}' is not ready. "
            f"Please configure {profile.api_key_env} first."
        )
    if role == "agent" and not profile.supports_function_calling:
        raise ValueError(
            f"Model profile '{profile_id}' does not support function calling and cannot be used for agent role."
        )
    return profile


def _build_llm_instance(profile: ModelProfile):
    """Construct a LlamaIndex LLM for ``profile``.

    Every supported provider exposes (or is configured against) an
    OpenAI-compatible /v1/chat/completions endpoint:

      * DeepSeek           → https://api.deepseek.com
      * OpenAI             → https://api.openai.com/v1
      * Anthropic          → https://api.anthropic.com/v1     (OpenAI-compat shim)
      * NVIDIA             → https://integrate.api.nvidia.com/v1
      * Google Gemini      → https://generativelanguage.googleapis.com/v1beta/openai
      * Alibaba DashScope  → https://dashscope.aliyuncs.com/compatible-mode/v1
      * Moonshot / Zhipu / Xiaomi modelscope / SiliconFlow / …

    So provider switching is purely a matter of (api_base, api_key, model_id) —
    no special-case wrappers, no optional dependencies. Adding a new provider
    is a single new ``MODEL_PROFILES`` entry; the runtime code below never
    grows a branch.

    LangSmith tracing: when ``LANGSMITH_TRACING=true`` we force-wrap the
    LLM's internal ``AsyncOpenAI`` / sync ``OpenAI`` clients here. This is
    redundant with the module-level monkey-patch in ``app.core.llm_tracing``
    when import order works in our favor — but it's a critical fallback
    for the FastAPI process where module import ordering used to let
    chat-path calls slip past tracing. By wrapping the cached clients
    at LLM-construction time we guarantee that every chat / completion
    flow goes through ``wrap_openai`` regardless of what got imported when.
    """
    llm = OpenAILike(
        model=profile.model,
        api_key=resolve_api_key(profile),
        api_base=profile.api_base,
        is_chat_model=True,
        is_function_calling_model=profile.supports_function_calling,
        context_window=profile.context_window,
        temperature=0.2,
    )

    # Force-wrap the underlying OpenAI clients for LangSmith. ``_get_client``
    # / ``_get_aclient`` lazily construct the SDK clients on first use and
    # cache them on the LLM instance — touching them here means subsequent
    # ``astream_chat`` / ``astream_complete`` calls run through wrapped
    # methods. ``wrap_existing_client`` is a no-op when tracing is disabled
    # or when the client has already been wrapped (idempotent), so this is
    # cheap and safe to call unconditionally.
    try:
        from app.core.llm_tracing import wrap_existing_client

        wrap_existing_client(llm._get_aclient())
        wrap_existing_client(llm._get_client())
    except Exception as exc:  # noqa: BLE001 — tracing is best-effort
        logger.warning("LangSmith client wrap failed for %s: %s", profile.id, exc)

    return llm


def get_llm_for_role(role: str, user_id: str | None = None):
    """Build (or fetch from cache) a llama-index LLM for ``role``.

    ``user_id`` selects the per-user role→profile mapping; without
    one we fall back to ROLE_DEFAULTS (used by global LlamaIndex
    Settings.llm during startup). Cache key includes profile.id
    not user_id directly, so users who pick the same profile
    share a single LLM instance (cheap; LLM clients are heavy).
    """
    profile = get_profile_for_role(role, user_id=user_id)
    cache_key = (role, profile.id)
    with _selection_lock:
        cached = _llm_cache.get(cache_key)
        if cached is not None:
            return cached
        instance = _build_llm_instance(profile)
        _llm_cache[cache_key] = instance
        return instance


def build_async_openai_client_for_role(
    role: str,
    user_id: str | None = None,
) -> tuple[AsyncOpenAI, ModelProfile]:
    """Return a cached ``AsyncOpenAI`` + profile for the current selection.

    Thin wrapper over :func:`get_async_openai_client` so existing call sites
    that pass a role name don't have to resolve the profile themselves.
    ``user_id`` plumbs through both the selection lookup and the
    API-key resolution so per-user model + per-user key compose.
    """
    profile = get_profile_for_role(role, user_id=user_id)
    return get_async_openai_client(profile, user_id=user_id), profile


class RuntimeLLMProxy:
    """Process-global LLM proxy. Always resolves with user_id=None
    (i.e. uses ROLE_DEFAULTS) — this proxy is wired into
    LlamaIndex ``Settings.llm`` and other module-level singletons
    where there's no per-request user context. Per-user model
    selection goes through ``build_async_openai_client_for_role
    (role, user_id=current_user.username)`` in the conversation
    engine instead.
    """
    def __init__(self, role: str):
        self.role = role

    def _delegate(self):
        return get_llm_for_role(self.role)  # global default, no user_id

    async def acomplete(self, *args, **kwargs):
        return await self._delegate().acomplete(*args, **kwargs)

    async def astream_complete(self, *args, **kwargs):
        return await self._delegate().astream_complete(*args, **kwargs)

    def complete(self, *args, **kwargs):
        return self._delegate().complete(*args, **kwargs)
