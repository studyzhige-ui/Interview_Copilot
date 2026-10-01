"""Small native Messages completion seam for model-backed product commands.

Chat/Agent streaming is owned by ModelProviderAdapter. This class is the inner
wire for the *same* role/model selector and MeteredLLM; it does not create a
second accounting path. Anthropic is not sent OpenAI Chat Completions payloads.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Completion:
    text: str
    raw: Any


class AnthropicCompletion:
    def __init__(self, *, profile, sync_client, async_client, temperature: float):
        self.profile = profile
        self.context_window = profile.context_window
        self.max_tokens = profile.max_output_tokens
        self.model = profile.model
        self.temperature = temperature
        self._client, self._aclient = sync_client, async_client

    def _payload(self, prompt: str, kwargs: dict):
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("completion_prompt_required")
        options = dict(kwargs)
        maximum = options.pop("max_tokens", self.max_tokens)
        temperature = options.pop("temperature", self.temperature)
        response_format = options.pop("response_format", None)
        system = options.pop("system", "")
        if options:
            raise ValueError("unsupported_anthropic_completion_parameters")
        if type(maximum) is not int or not 0 < maximum <= self.max_tokens:
            raise ValueError("completion_output_budget_invalid")
        payload = dict(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=maximum,
            temperature=temperature,
        )
        if response_format is not None:
            # JSON-object mode is an instruction plus existing strict validators,
            # not an assertion of native constrained decoding. Explicit schema
            # mode uses the official Messages output_config contract.
            if response_format == {"type": "json_object"}:
                system = (system + "\nReturn one valid JSON object only.").strip()
            elif (
                isinstance(response_format, dict)
                and response_format.get("type") == "json_schema"
            ):
                schema = (response_format.get("json_schema") or {}).get("schema")
                if not isinstance(schema, dict):
                    raise ValueError("completion_json_schema_required")
                payload["output_config"] = {
                    "format": {"type": "json_schema", "schema": schema}
                }
            else:
                raise ValueError("unsupported_anthropic_response_format")
        if system:
            payload["system"] = system
        return payload

    @staticmethod
    def _result(response):
        text = "".join(block.text for block in response.content if block.type == "text")
        return Completion(text=text, raw=response)

    def complete(self, prompt, **kwargs):
        return self._result(
            self._client.messages.create(**self._payload(prompt, kwargs))
        )

    async def acomplete(self, prompt, **kwargs):
        return self._result(
            await self._aclient.messages.create(**self._payload(prompt, kwargs))
        )

    def _get_client(self):
        return self._client

    def _get_aclient(self):
        return self._aclient
