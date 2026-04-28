from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".env",
    ".example",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {".env", ".env.docker", ".env.example", ".gitignore", "AGENTS.md"}
SKIP_PARTS = {".git", ".pytest_cache", "__pycache__"}
SKIP_PREFIXES = {
    Path("data/cache"),
}


def is_skipped(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in SKIP_PARTS for part in rel.parts):
        return True
    return any(rel.is_relative_to(prefix) for prefix in SKIP_PREFIXES)


def is_text_candidate(path: Path) -> bool:
    return path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES


def main() -> int:
    failures: list[str] = []
    checked = 0

    for path in ROOT.rglob("*"):
        if not path.is_file() or is_skipped(path) or not is_text_candidate(path):
            continue

        checked += 1
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            rel = path.relative_to(ROOT)
            failures.append(f"{rel}: byte {exc.start}: {exc.reason}")

    if failures:
        print("Non-UTF-8 text files found:")
        print("\n".join(failures))
        return 1

    print(f"All checked text files are UTF-8 ({checked} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
