"""Download and verify the public, versioned RAG evaluation corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("corpus_manifest.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_corpus(output_dir: Path, *, force: bool = False) -> list[Path]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    ready: list[Path] = []
    for item in manifest["documents"]:
        target = output_dir / item["file"]
        expected = item["sha256"]
        if target.is_file() and not force and _sha256(target) == expected:
            print(f"ready    {target.name}")
            ready.append(target)
            continue

        request = Request(
            item["url"], headers={"User-Agent": "Interview-Copilot-Eval/1"}
        )
        temporary = target.with_suffix(target.suffix + ".download")
        with urlopen(request, timeout=60) as response, temporary.open("wb") as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
        actual = _sha256(temporary)
        if actual != expected:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(
                f"Corpus checksum changed for {target.name}: expected {expected}, "
                f"received {actual}. Review the upstream change before updating the dataset."
            )
        temporary.replace(target)
        print(f"download {target.name}")
        ready.append(target)
    return ready


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "corpus",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    paths = download_corpus(args.output_dir.resolve(), force=args.force)
    print(f"Verified {len(paths)} evaluation documents in {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
