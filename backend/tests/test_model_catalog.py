import json

import pytest

from app.providers.catalog.pipeline import _deserialize_entries
from app.providers.catalog.vendors import get_spec


@pytest.mark.parametrize(
    "provider,model",
    [
        ("openai", "gpt-4o-transcribe-diarize"),
        ("openai", "sora-2-pro"),
        ("openai", "babbage-002"),
        ("openai", "davinci-002"),
        ("nvidia_nim", "baai/bge-m3"),
    ],
)
def test_non_chat_models_cannot_reenter_via_persisted_catalog(provider, model):
    row = {"provider": provider, "model": model, "display_name": model}
    assert not get_spec(provider).chat_filter(row, model)
    assert _deserialize_entries(json.dumps([row])) == []


def test_cached_chat_models_keep_their_capabilities():
    rows = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "display_name": "GPT 4o",
            "supports_function_calling": True,
        },
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "display_name": "Gemini Flash",
        },
        {
            "provider": "nvidia_nim",
            "model": "meta/llama-3.3-70b-instruct",
            "display_name": "Llama",
        },
    ]
    models = _deserialize_entries(json.dumps(rows))
    assert [model.model for model in models] == [row["model"] for row in rows]
    assert models[0].supports_function_calling is True
