"""CLI: force-refresh the model catalog from every vendor's /v1/models.

Identical in effect to ``POST /api/v1/models/refresh-catalog`` and
the daily Celery beat — useful for verifying what each vendor's API
currently exposes, pre-warming the cache on first deploy, and
regenerating the shipped ``seed_catalog.json`` snapshot.

Usage::

    python scripts/refresh_models.py                     # all providers
    python scripts/refresh_models.py --json              # JSON output
    python scripts/refresh_models.py --provider openai   # filter one
    python scripts/refresh_models.py --verbose           # show every id
    python scripts/refresh_models.py --write-seed        # regenerate the
                                                         # repo-shipped snapshot
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
# override=True so an empty value in the parent shell (e.g. left over
# from a prior `unset` or test run) does NOT silently mask a populated
# value in .env — without this, a single stale ``ANTHROPIC_API_KEY=``
# in the shell would skip Anthropic refresh forever.
load_dotenv(ROOT / ".env", override=True)


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the model catalog from every vendor's "
        "/v1/models endpoint and print a per-provider summary.",
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
    parser.add_argument(
        "--write-seed", action="store_true",
        help="After refreshing, write backend/app/services/model_sources/"
             "seed_catalog.json with the current catalog snapshot. "
             "This file ships with the repo so fresh clones show a "
             "populated Models page before users configure any keys.",
    )
    args = parser.parse_args()

    # Lazy imports so --help doesn't load the full backend stack.
    from app.services.model_sources.pipeline import refresh_catalog
    from app.services.model_sources.providers import PROVIDERS

    # Pipeline never raises — vendor-level failures fall back to LKG
    # internally. If ALL 9 vendors fail (cold cache + no LKG), we get
    # an empty dict back.
    grouped = await refresh_catalog()

    if args.write_seed:
        import json as _json
        from pathlib import Path as _Path

        seed_path = _Path("backend/app/services/model_sources/seed_catalog.json")
        snapshot = {
            provider: [
                {
                    "provider": e.provider,
                    "model": e.model,
                    "display_name": e.display_name,
                    "supports_function_calling": e.supports_function_calling,
                    "context_window": e.context_window,
                    "max_output_tokens": e.max_output_tokens,
                    "supports_vision": e.supports_vision,
                }
                for e in entries
            ]
            for provider, entries in grouped.items() if entries
        }
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        with seed_path.open("w", encoding="utf-8") as f:
            _json.dump(snapshot, f, ensure_ascii=False, indent=2)
        total = sum(len(v) for v in snapshot.values())
        print(f"Wrote seed catalog: {total} models across "
              f"{len(snapshot)} providers → {seed_path}")
        print()

    # Order rows by PROVIDERS dict iteration so the table matches the
    # Models page card order (default-enabled first, opt-in after).
    provider_order = [
        p for p in PROVIDERS.keys() if (not args.provider or p == args.provider)
    ]
    # No "extras" path post-P7-A — PROVIDERS is now the complete set
    # of vendors we ship adapters for; the pipeline never returns a
    # provider that's not in PROVIDERS.
    extras: list[str] = []

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

    print(f"Catalog refreshed from vendor /v1/models endpoints. {sum(len(v) for v in grouped.values())} chat models total.")
    print()
    print(f"{'Provider':<14} {'Models':>7}  Head of available models")
    print("-" * 90)
    for provider in provider_order:
        entries = grouped.get(provider, [])
        defaults = PROVIDERS.get(provider)
        label = defaults.display_label if defaults else provider
        if not entries:
            print(f"{provider:<14} {'0':>7}  ({label}: no API key in .env, or vendor returned no chat models)")
            continue
        head = ", ".join(e.model for e in entries[:4])
        more = f" + {len(entries) - 4} more" if len(entries) > 4 else ""
        print(f"{provider:<14} {len(entries):>7}  {head}{more}")
        if args.verbose:
            for e in entries:
                # ASCII-only marker for Windows console (cp936) compat.
                fc = "[fc]" if e.supports_function_calling else "    "
                print(f"              {fc} {e.model}")
    print()
    print(
        "Source: each vendor's official /v1/models endpoint. "
        "An empty count means either no API key for that vendor in .env, "
        "or the vendor returned no chat models (after applying the "
        "vendor adapter's chat-only filter)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
