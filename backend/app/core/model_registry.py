import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from llama_index.llms.deepseek import DeepSeek
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


ROLE_DEFAULTS: dict[str, str] = {
    "primary": "deepseek-reasoner",
    "fast": "deepseek-chat",
    "agent": "deepseek-chat",
}


MODEL_PROFILES: dict[str, ModelProfile] = {
    "deepseek-chat": ModelProfile(
        id="deepseek-chat",
        provider="deepseek",
        display_name="DeepSeek Chat",
        model="deepseek-chat",
        api_base="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        supports_function_calling=True,
        description="Fast general-purpose chat model for rewrite, router, memory, and tool use.",
    ),
    "deepseek-reasoner": ModelProfile(
        id="deepseek-reasoner",
        provider="deepseek",
        display_name="DeepSeek Reasoner",
        model="deepseek-reasoner",
        api_base="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        supports_function_calling=False,
        description="Stronger reasoning model for primary answer generation and analysis tasks.",
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
}


_selection_lock = Lock()
_llm_cache: dict[tuple[str, str], Any] = {}


def _selection_file() -> Path:
    configured = os.getenv("MODEL_SELECTION_FILE")
    if configured:
        return Path(configured)
    return Path(settings.APP_DATA_DIR) / "runtime" / "model_selection.json"


def _read_selection_file() -> dict[str, str]:
    path = _selection_file()
    if not path.exists():
        return dict(ROLE_DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read model selection file %s: %s", path, exc)
    return dict(ROLE_DEFAULTS)


def _normalize_selection(raw: dict[str, str]) -> dict[str, str]:
    selection = dict(ROLE_DEFAULTS)
    for role in ROLE_DEFAULTS:
        candidate = raw.get(role)
        if candidate in MODEL_PROFILES:
            selection[role] = candidate
    agent_profile = MODEL_PROFILES[selection["agent"]]
    if not agent_profile.supports_function_calling:
        selection["agent"] = ROLE_DEFAULTS["agent"]
    return selection


def get_runtime_selection() -> dict[str, str]:
    with _selection_lock:
        return _normalize_selection(_read_selection_file())


def persist_runtime_selection(selection: dict[str, str]) -> dict[str, str]:
    normalized = _normalize_selection(selection)
    path = _selection_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _selection_lock:
        path.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _llm_cache.clear()
    return normalized


def update_runtime_selection(updates: dict[str, str]) -> dict[str, str]:
    current = get_runtime_selection()
    current.update({k: v for k, v in updates.items() if v is not None})
    return persist_runtime_selection(current)


def get_profile(profile_id: str) -> ModelProfile:
    if profile_id not in MODEL_PROFILES:
        raise ValueError(f"Unknown model profile: {profile_id}")
    return MODEL_PROFILES[profile_id]


def get_profile_for_role(role: str) -> ModelProfile:
    selection = get_runtime_selection()
    profile_id = selection.get(role, ROLE_DEFAULTS[role])
    return get_profile(profile_id)


def resolve_api_key(profile: ModelProfile) -> str:
    return os.getenv(profile.api_key_env, "")


def profile_ready(profile: ModelProfile) -> bool:
    return bool(resolve_api_key(profile)) and bool(profile.model.strip())


def list_profiles() -> list[dict[str, Any]]:
    selection = get_runtime_selection()
    return [
        {
            **asdict(profile),
            "ready": profile_ready(profile),
            "selected_for": [role for role, pid in selection.items() if pid == profile.id],
        }
        for profile in MODEL_PROFILES.values()
    ]


def validate_role_update(role: str, profile_id: str) -> ModelProfile:
    profile = get_profile(profile_id)
    if not profile_ready(profile):
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
    api_key = resolve_api_key(profile)
    if profile.provider == "deepseek":
        return DeepSeek(
            model=profile.model,
            api_key=api_key,
            api_base=profile.api_base,
        )
    return OpenAILike(
        model=profile.model,
        api_key=api_key,
        api_base=profile.api_base,
        temperature=0.2,
    )


def get_llm_for_role(role: str):
    profile = get_profile_for_role(role)
    cache_key = (role, profile.id)
    with _selection_lock:
        cached = _llm_cache.get(cache_key)
        if cached is not None:
            return cached
        instance = _build_llm_instance(profile)
        _llm_cache[cache_key] = instance
        return instance


def build_async_openai_client_for_role(role: str) -> tuple[AsyncOpenAI, ModelProfile]:
    profile = get_profile_for_role(role)
    return (
        AsyncOpenAI(
            api_key=resolve_api_key(profile),
            base_url=profile.api_base,
        ),
        profile,
    )


class RuntimeLLMProxy:
    def __init__(self, role: str):
        self.role = role

    def _delegate(self):
        return get_llm_for_role(self.role)

    async def acomplete(self, *args, **kwargs):
        return await self._delegate().acomplete(*args, **kwargs)

    async def astream_complete(self, *args, **kwargs):
        return await self._delegate().astream_complete(*args, **kwargs)

    def complete(self, *args, **kwargs):
        return self._delegate().complete(*args, **kwargs)
