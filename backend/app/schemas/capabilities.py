from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SkillCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)
    enabled: bool = True


class SkillUpdateRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=200_000)
    enabled: bool | None = None


class MCPServerConfigRequest(BaseModel):
    name: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    )
    transport: Literal["streamable_http", "stdio"]
    url: str | None = Field(default=None, max_length=2_000)
    command: str | None = Field(default=None, max_length=2_000)
    args: list[str] = Field(default_factory=list, max_length=50)
    headers: dict[str, str] | None = None
    env: dict[str, str] | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_transport(self):
        if self.transport == "streamable_http":
            if not self.url or not self.url.startswith(("http://", "https://")):
                raise ValueError("streamable_http requires an http(s) URL")
            self.command = None
            self.args = []
        elif not self.command:
            raise ValueError("stdio requires a command")
        return self


class CapabilityEnabledRequest(BaseModel):
    enabled: bool


class SessionCapabilityPermissionRequest(BaseModel):
    capability: str = Field(min_length=1, max_length=128)
    decision: Literal["allow", "deny", "inherit"]
