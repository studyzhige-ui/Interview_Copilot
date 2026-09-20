"""Explicit operator configuration. Safe to import without the application .env."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .protocol import LOCAL_EMBEDDING_CONTRACT, ROLES, loads


def binding_for(
    role, model_id, revision, dimension, max_tokens, query_prefix="", text_prefix=""
) -> str:
    # Execution details (device, cache, interpreter) do not change semantic identity.
    # Changing an instruction or adapter contract DOES require a new index.
    value = [
        LOCAL_EMBEDDING_CONTRACT,
        role,
        model_id,
        revision,
        dimension,
        max_tokens,
        query_prefix,
        text_prefix,
    ]
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def positive(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"invalid_{name}")


@dataclass(frozen=True)
class ModelSpec:
    role: str
    model_id: str
    model_path: str
    python: str
    device: str = "cpu"
    revision: str | None = None
    dimension: int = 1024
    max_tokens: int = 8192
    reservation_mib: int = 4096
    query_prefix: str = ""
    text_prefix: str = ""

    def __post_init__(self):
        if self.role not in ROLES or self.device not in {"cpu", "cuda"}:
            raise ValueError("invalid_role_or_device")
        if not isinstance(self.model_id, str) or not 1 <= len(self.model_id) <= 200:
            raise ValueError("invalid_model_id")
        if self.revision is not None and (
            not isinstance(self.revision, str)
            or len(self.revision) != 40
            or any(c not in "0123456789abcdef" for c in self.revision)
        ):
            raise ValueError("invalid_revision")
        for name, maximum in (
            ("dimension", 4096),
            ("max_tokens", 32768),
            ("reservation_mib", 131072),
        ):
            positive(getattr(self, name), name, maximum)
        for name in ("model_path", "python"):
            if (
                not isinstance(getattr(self, name), str)
                or not Path(getattr(self, name)).is_absolute()
            ):
                raise ValueError("model_and_python_paths_must_be_absolute")
        for name in ("query_prefix", "text_prefix"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > 2048:
                raise ValueError("invalid_prompt_prefix")
        if self.role == "reranking" and (
            self.dimension != 1 or self.query_prefix or self.text_prefix
        ):
            raise ValueError("invalid_reranker_spec")

    @property
    def binding(self):
        return binding_for(
            self.role,
            self.model_id,
            self.revision,
            self.dimension,
            self.max_tokens,
            self.query_prefix,
            self.text_prefix,
        )


@dataclass(frozen=True)
class BrokerConfig:
    socket_path: str
    cache_root: str
    models: tuple[ModelSpec, ...]
    capacity_mib: int = 12000
    max_pending: int = 16
    max_connections: int = 24
    idle_seconds: int = 300
    load_timeout: int = 180

    def __post_init__(self):
        for name, maximum in (
            ("capacity_mib", 131072),
            ("max_pending", 128),
            ("max_connections", 256),
            ("idle_seconds", 86400),
            ("load_timeout", 600),
        ):
            positive(getattr(self, name), name, maximum)
        if not 1 <= len(self.models) <= len(ROLES) or len(
            {m.role for m in self.models}
        ) != len(self.models):
            raise ValueError("duplicate_or_empty_models")
        for name in ("socket_path", "cache_root"):
            if (
                not isinstance(getattr(self, name), str)
                or not Path(getattr(self, name)).is_absolute()
            ):
                raise ValueError("runtime_paths_must_be_absolute")
        if len(os.fsencode(self.socket_path)) > 100:
            raise ValueError("unix_socket_path_too_long")
        if any(m.reservation_mib > self.capacity_mib for m in self.models):
            raise ValueError("model_exceeds_memory_reservation")
        cache = Path(self.cache_root).resolve()
        if any(cache.is_relative_to(Path(m.model_path).resolve()) for m in self.models):
            raise ValueError("cache_must_not_be_inside_weights")

    @classmethod
    def load(cls, path: Path):
        with path.open("rb") as file:
            raw = file.read(65537)
        if len(raw) > 65536:
            raise ValueError("broker_config_too_large")
        value = loads(raw)
        if not isinstance(value, dict) or not isinstance(value.get("models"), list):
            raise ValueError("invalid_broker_config")
        return cls(
            **{**value, "models": tuple(ModelSpec(**m) for m in value["models"])}
        )

    def as_dict(self):
        return asdict(self)
