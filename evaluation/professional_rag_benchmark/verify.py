"""Verify the frozen official-source corpus and its minimum coverage gate."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from .acquire import LOCK, OUT, SEED, canonical_text


def main() -> None:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    locked = [
        json.loads(line)
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line
    ]
    runtime = [
        json.loads(line)
        for line in (OUT / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(seed) == len(locked) == len(runtime) >= 40
    for key in ("id", "url"):
        assert len({row[key] for row in seed}) == len(seed), f"Duplicate {key}"
    assert len({row["sha256"] for row in locked}) == len(locked), (
        "Duplicate original bytes"
    )
    assert (
        [row["id"] for row in seed]
        == [row["id"] for row in locked]
        == [row["id"] for row in runtime]
    )
    languages = Counter(row["language"] for row in seed)
    assert languages["en"] >= 20 and languages["zh"] >= 20
    for source, frozen, acquired in zip(seed, locked, runtime):
        assert all(
            source[key] == frozen[key] == acquired[key]
            for key in ("id", "url", "language", "domain", "publisher")
        )
        suffix = ".pdf" if source["url"].lower().endswith(".pdf") else ".html"
        raw = (OUT / "raw" / (source["id"] + suffix)).read_bytes()
        content = (OUT / "text" / (source["id"] + ".txt")).read_text(encoding="utf-8")
        assert hashlib.sha256(raw).hexdigest() == frozen["sha256"] == acquired["sha256"]
        assert canonical_text(raw, suffix) == content
        assert (
            hashlib.sha256(content.encode("utf-8")).hexdigest()
            == frozen["text_sha256"]
            == acquired["text_sha256"]
        )
        assert len(content) == frozen["text_chars"] == acquired["text_chars"]
        assert len(content) >= (1000 if suffix == ".pdf" else 500)
        assert content.count("\ufffd") / len(content) <= 0.01
    failures = json.loads((OUT / "failures.json").read_text(encoding="utf-8"))
    assert not failures, failures
    print(
        json.dumps(
            {
                "documents": len(seed),
                "languages": dict(languages),
                "domains": len({row["domain"] for row in seed}),
                "publishers": len({row["publisher"] for row in seed}),
                "extracted_characters": sum(row["text_chars"] for row in locked),
                "failures": len(failures),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
