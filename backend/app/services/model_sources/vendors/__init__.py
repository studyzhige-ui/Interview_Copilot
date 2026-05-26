"""Per-vendor /v1/models adapters (P7-A).

Each module under this package declares a ``SPEC: VendorAdapterSpec``
describing how to talk to one vendor's ``/v1/models`` endpoint. The
shared fetcher in ``base.py`` consumes the spec — no per-vendor
business logic lives outside the spec + an optional ``chat_filter``
predicate.

Adding a new vendor = drop a new file in this package + import it
into ``ALL_SPECS`` below. No edit to the pipeline.
"""
from .base import VendorAdapterSpec, fetch_one_vendor

# Default-enabled (the 9 vendors we ship support for, all with
# /v1/models confirmed working as of P7-A live verification).
from .openai import SPEC as OPENAI_SPEC
from .anthropic import SPEC as ANTHROPIC_SPEC
from .gemini import SPEC as GEMINI_SPEC
from .deepseek import SPEC as DEEPSEEK_SPEC
from .nvidia_nim import SPEC as NVIDIA_SPEC
from .xiaomi import SPEC as XIAOMI_SPEC
from .moonshot import SPEC as MOONSHOT_SPEC
from .zai import SPEC as ZAI_SPEC
from .qwen import SPEC as QWEN_SPEC


ALL_SPECS: list[VendorAdapterSpec] = [
    OPENAI_SPEC,
    ANTHROPIC_SPEC,
    GEMINI_SPEC,
    DEEPSEEK_SPEC,
    NVIDIA_SPEC,
    XIAOMI_SPEC,
    MOONSHOT_SPEC,
    ZAI_SPEC,
    QWEN_SPEC,
]


def get_spec(provider: str) -> VendorAdapterSpec | None:
    for s in ALL_SPECS:
        if s.provider == provider:
            return s
    return None


__all__ = ["VendorAdapterSpec", "fetch_one_vendor", "ALL_SPECS", "get_spec"]
