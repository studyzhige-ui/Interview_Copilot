"""CLI: force-refresh the live LLM model catalog from every configured vendor.

Reads each ``EMBEDDING_PROVIDER`` / ``RERANKER_PROVIDER`` / ... env var,
plus the curated ``MODEL_PROFILES`` table, and hits each vendor's
``/v1/models`` endpoint to enumerate the chat models the API key can see.
Results land in Redis with a 24h TTL.

Usage::

    python scripts/refresh_models.py                # refresh all vendors
    python scripts/refresh_models.py --json         # machine-readable output
    python scripts/refresh_models.py --provider deepseek    # one vendor only

Same effect as POSTing to ``/api/v1/models/refresh-catalog``; this CLI is
useful for cron jobs / CI pre-warming so the first user request doesn't
pay a discovery roundtrip.
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
        description="Refresh the live LLM model catalog from each configured vendor.",
    )
    parser.add_argument(
        "--provider", default=None,
        help="Refresh only this provider (e.g. 'deepseek'). Default: all.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    # Imports here so --help works without the full backend stack loaded.
    from app.core.model_registry import _provider_specs_for_discovery
    from app.services.model_catalog_service import discover_all, invalidate_all

    specs = _provider_specs_for_discovery()
    if args.provider:
        specs = [s for s in specs if s[0] == args.provider]
        if not specs:
            print(f"No provider '{args.provider}' in MODEL_PROFILES.", file=sys.stderr)
            return 2

    dropped = await invalidate_all()
    discovered = await discover_all(specs, force_refresh=True)

    summary = {
        "discovery_cache_dropped": dropped,
        "providers": {
            provider: [m.model for m in models]
            for provider, models in discovered.items()
        },
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print(f"Dropped {dropped} cached entries.")
    print()
    print(f"{'Provider':<14} {'Discovered':<12} Models")
    print("-" * 78)
    for provider, models in sorted(discovered.items()):
        if not models:
            print(f"{provider:<14} {'0 (no key?)':<12}")
            continue
        head = ", ".join(m.model for m in models[:3])
        more = f" + {len(models) - 3} more" if len(models) > 3 else ""
        print(f"{provider:<14} {len(models):<12} {head}{more}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
