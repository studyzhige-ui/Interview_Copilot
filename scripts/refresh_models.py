"""CLI: force-refresh the LiteLLM-driven model catalog.

P6-L: the catalog's only data source is LiteLLM's
``model_prices_and_context_window.json``. This CLI is identical in
effect to ``POST /api/v1/models/refresh-catalog`` and the daily
Celery beat — useful for verifying what the LiteLLM JSON currently
contains for each provider and for pre-warming on first deploy.

Usage::

    python scripts/refresh_models.py                     # all providers
    python scripts/refresh_models.py --json              # JSON output
    python scripts/refresh_models.py --provider openai   # filter one
    python scripts/refresh_models.py --verbose           # show every id
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the LiteLLM-driven model catalog and print a "
        "per-provider summary.",
    )
    parser.add_argument(
        "--provider", default=None,
        help="Filter output to one provider (e.g. 'openai'). The fetch "
        "still pulls the full JSON — this only narrows the print view.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show every model id per provider (default: head + count).",
    )
    args = parser.parse_args()

    # Lazy imports so --help doesn't load the full backend stack.
    from app.services.model_sources.litellm_loader import (
        LiteLLMFetchFailed,
        fetch_litellm_catalog,
    )
    from app.services.model_sources.pipeline import refresh_catalog
    from app.services.model_sources.providers import PROVIDERS

    try:
        grouped = await refresh_catalog()
    except LiteLLMFetchFailed as exc:
        print(f"LiteLLM fetch failed: {exc}", file=sys.stderr)
        return 2

    # Order rows by PROVIDERS dict iteration so the table matches the
    # Models page card order (default-enabled first, opt-in after).
    provider_order = [
        p for p in PROVIDERS.keys() if (not args.provider or p == args.provider)
    ]
    # Include any LiteLLM providers we got data for that aren't yet in
    # PROVIDERS — useful for spotting "should we add this to PROVIDERS?"
    extras = [
        p for p in sorted(grouped.keys())
        if p not in PROVIDERS and (not args.provider or p == args.provider)
    ]

    if args.json:
        out = {
            "providers": {
                p: [
                    {
                        "model": e.model,
                        "display_name": e.display_name,
                        "supports_function_calling": e.supports_function_calling,
                        "context_window": e.context_window,
                        "supports_vision": e.supports_vision,
                    }
                    for e in grouped.get(p, [])
                ]
                for p in provider_order + extras
            },
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"Catalog refreshed from LiteLLM. {sum(len(v) for v in grouped.values())} chat models total.")
    print()
    print(f"{'Provider':<14} {'Models':>7}  Head of available models")
    print("-" * 90)
    for provider in provider_order:
        entries = grouped.get(provider, [])
        defaults = PROVIDERS.get(provider)
        label = defaults.display_label if defaults else provider
        if not entries:
            print(f"{provider:<14} {'0':>7}  ({label}: no chat entries in LiteLLM JSON)")
            continue
        head = ", ".join(e.model for e in entries[:4])
        more = f" + {len(entries) - 4} more" if len(entries) > 4 else ""
        print(f"{provider:<14} {len(entries):>7}  {head}{more}")
        if args.verbose:
            for e in entries:
                fc = "✓" if e.supports_function_calling else " "
                print(f"              {fc} {e.model}")
    if extras:
        print()
        print("Providers present in LiteLLM JSON but NOT in PROVIDERS (add to "
              "model_sources/providers.py to surface in the UI):")
        for p in extras:
            print(f"   - {p}: {len(grouped[p])} chat model(s)")
    print()
    print(
        "Source: LiteLLM model_prices_and_context_window.json. "
        "Set LITELLM_CATALOG_URL to override the source URL."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
