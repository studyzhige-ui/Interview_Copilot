"""Generate the live-media protocol group without an API, DB or model startup."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from pydantic.json_schema import models_json_schema  # noqa: E402
from app.schemas.realtime import (  # noqa: E402
    MediaOffer,
    MediaAnswer,
    MediaControl,
    MediaPlaybackReport,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    roots, definitions = models_json_schema(
        [
            (MediaOffer, "validation"),
            (MediaAnswer, "serialization"),
            (MediaPlaybackReport, "serialization"),
            (MediaControl, "validation"),
        ],
        ref_template="#/components/schemas/{model}",
    )
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Live media contracts", "version": "1"},
        "paths": {},
        "components": {"schemas": definitions["$defs"]},
    }
    output = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    target = ROOT / "frontend/contracts/realtime.openapi.json"
    if args.check:
        if not target.is_file() or target.read_text() != output:
            raise SystemExit("realtime protocol snapshot needs regeneration")
    else:
        target.write_text(output)


if __name__ == "__main__":
    main()
