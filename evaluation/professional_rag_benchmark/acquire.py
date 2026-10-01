"""Download original professional knowledge sources; never synthesize missing text."""

from __future__ import annotations

import hashlib
import gzip
import json
import re
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
SEED = Path(__file__).with_name("sources.seed.json")
LOCK = Path(__file__).with_name("manifest.lock.jsonl")
OUT = ROOT / "data/evaluation/professional_rag_benchmark"


def canonical_text(raw: bytes, suffix: str) -> str:
    if raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    if suffix == ".pdf":
        import fitz

        document = fitz.open(stream=raw, filetype="pdf")
        content = "\n".join(page.get_text(sort=True) for page in document)
    else:
        soup = BeautifulSoup(raw, "html.parser")
        for node in soup(["script", "style", "nav", "footer", "header"]):
            node.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        content = main.get_text("\n", strip=True)
    return re.sub(r"[ \t]+", " ", content).strip()


def main() -> None:
    sources = json.loads(SEED.read_text(encoding="utf-8"))
    expected = {
        row["id"]: row
        for row in (
            json.loads(line)
            for line in LOCK.read_text(encoding="utf-8").splitlines()
            if line
        )
    }
    if {row["id"] for row in sources} != set(expected):
        raise ValueError("Source IDs differ from the frozen manifest")
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    (OUT / "text").mkdir(parents=True, exist_ok=True)
    manifest = []
    failures = []
    for source in sources:
        suffix = ".pdf" if source["url"].lower().endswith(".pdf") else ".html"
        path = OUT / "raw" / (source["id"] + suffix)
        try:
            if source["url"] != expected[source["id"]]["url"]:
                raise ValueError("Source URL differs from the frozen manifest")
            if path.exists():
                raw = path.read_bytes()
            else:
                request = urllib.request.Request(
                    source["url"],
                    headers={"User-Agent": "Mozilla/5.0 CareerRAGResearch/0.1"},
                )
                with urllib.request.urlopen(request, timeout=45) as response:
                    raw = response.read()
                path.write_bytes(raw)
            text = canonical_text(raw, suffix)
            raw_hash = hashlib.sha256(raw).hexdigest()
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if raw_hash != expected[source["id"]]["sha256"]:
                raise ValueError("Original file SHA-256 differs from frozen manifest")
            if text_hash != expected[source["id"]]["text_sha256"]:
                raise ValueError("Extracted text SHA-256 differs from frozen manifest")
            replacement_ratio = text.count("\ufffd") / max(1, len(text))
            minimum = 500 if suffix == ".html" else 1000
            if len(text) < minimum or replacement_ratio > 0.01:
                raise ValueError(
                    f"Unusable extracted text: chars={len(text)}, replacement_ratio={replacement_ratio:.3f}"
                )
            (OUT / "text" / (source["id"] + ".txt")).write_text(text, encoding="utf-8")
            manifest.append(
                {
                    **source,
                    "raw_file": path.name,
                    "sha256": raw_hash,
                    "text_sha256": text_hash,
                    "text_chars": len(text),
                    "status": "downloaded_and_extracted",
                }
            )
            print(f"OK {source['id']} {len(raw)} bytes {len(text)} chars", flush=True)
        except Exception as exc:  # Preserve failures as data, never mark as downloaded.
            failures.append(
                {"id": source["id"], "url": source["url"], "error": str(exc)}
            )
            print(f"FAILED {source['id']}: {exc}", flush=True)
    (OUT / "manifest.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in manifest),
        encoding="utf-8",
    )
    (OUT / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"downloaded": len(manifest), "failed": len(failures)}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
