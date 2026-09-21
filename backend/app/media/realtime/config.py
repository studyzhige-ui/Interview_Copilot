"""Explicit local live-media settings. No downloads or model imports at startup."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RealtimeConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REALTIME_", env_file=".env", extra="ignore"
    )
    enabled: bool = False
    max_sessions: int = Field(2, ge=1, le=16)
    session_seconds: int = Field(900, ge=30, le=3600)
    max_turn_seconds: int = Field(180, ge=2, le=300)
    allowed_cidrs: str = (
        "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
    )
    vad_path: str = ""
    vad_sha256: str = ""
    turn_path: str = ""
    turn_sha256: str = ""
    speech_threshold: float = Field(0.5, ge=0.1, le=0.95)
    endpoint_threshold: float = Field(0.5, ge=0.1, le=0.95)
    silence_ms: int = Field(800, ge=320, le=3000)
    partial_seconds: int = Field(3, ge=2, le=10)


config = RealtimeConfig()
