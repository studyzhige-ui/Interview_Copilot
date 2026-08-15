"""Legacy completion wrappers keep provider-specific payloads deterministic."""

from types import SimpleNamespace

from app.core.llm_client_factory import _legacy_request_overrides


def test_deepseek_legacy_structured_calls_disable_thinking_content_split():
    assert _legacy_request_overrides(SimpleNamespace(provider="deepseek")) == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }


def test_other_legacy_providers_need_no_payload_override():
    assert _legacy_request_overrides(SimpleNamespace(provider="openai")) is None
