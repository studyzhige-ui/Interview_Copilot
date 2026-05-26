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
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show the full id list per vendor (default: head + count).",
    )
    args = parser.parse_args()

    # Imports here so --help works without the full backend stack loaded.
    from app.core.model_registry import MODEL_PROFILES, _provider_specs_for_discovery
    from app.services.model_catalog_service import discover_all, invalidate_all

    specs = _provider_specs_for_discovery()
    if args.provider:
        specs = [s for s in specs if s[0] == args.provider]
        if not specs:
            print(f"No provider '{args.provider}' in MODEL_PROFILES.", file=sys.stderr)
            return 2

    # Per-provider curated-id set, so we can compute "net-new" (the diff
    # between vendor /v1/models and what we've already hand-curated). This
    # is the most useful diagnostic for "we should see GPT-X.Y but don't":
    # if X.Y isn't in vendor's response, the issue is upstream; if it IS
    # there and curated already, you'll see it in the curated count; if
    # it's there and net-new, it'll show in the auto-discovered count.
    curated_by_provider: dict[str, set[str]] = {}
    for profile in MODEL_PROFILES.values():
        curated_by_provider.setdefault(profile.provider, set()).add(profile.model)

    dropped = await invalidate_all()
    discovered = await discover_all(specs, force_refresh=True)

    summary = {
        "discovery_cache_dropped": dropped,
        "providers": {
            provider: {
                "discovered": [m.model for m in models],
                "discovered_count": len(models),
                "curated_count": len(curated_by_provider.get(provider, set())),
                "net_new": [
                    m.model for m in models
                    if m.model not in curated_by_provider.get(provider, set())
                ],
            }
            for provider, models in discovered.items()
        },
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print(f"Dropped {dropped} cached entries.")
    print()
    # Wider columns so per-vendor counts are immediately readable.
    print(f"{'Provider':<12} {'Returned':>8} {'Curated':>8} {'NetNew':>7}  Head of new models")
    print("-" * 90)
    for provider, models in sorted(discovered.items()):
        curated = curated_by_provider.get(provider, set())
        net_new = [m.model for m in models if m.model not in curated]
        if not models:
            # 0 returned == "vendor responded with empty list" OR "no key".
            # The discover_provider layer short-circuits on missing key so
            # we can't distinguish in this view — but checking your env or
            # user_api_keys row for that vendor takes 5 seconds.
            print(f"{provider:<12} {'0':>8} {len(curated):>8} {'-':>7}  (no key, or vendor returned empty)")
            continue
        head = ", ".join(net_new[:4]) if net_new else "(all already curated)"
        more = f" + {len(net_new) - 4} more" if len(net_new) > 4 else ""
        print(
            f"{provider:<12} {len(models):>8} {len(curated):>8} {len(net_new):>7}  {head}{more}"
        )
        if args.verbose and models:
            for m in models:
                tag = "  " if m.model in curated else "★ "  # ★ = net-new
                print(f"              {tag}{m.model}")
    print()
    print(
        "Legend: Returned=ids vendor sent back (post chat-only filter), "
        "Curated=ids in MODEL_PROFILES, NetNew=auto-discovered."
    )
    print(
        "If a model you expect isn't in 'Returned', the vendor isn't exposing "
        "it via /v1/models — there's nothing this script can do about that."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
