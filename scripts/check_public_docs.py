"""Require tracked documentation to stay within startup and user-help scope."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
HELP = {
    "README.md",
    "desktop/README.md",
    "docs/README.md",
    "docs/getting-started.md",
    "docs/usage.md",
    "docs/deployment/community.md",
    "docs/deployment/cloud.md",
    "docs/deployment/local-first.md",
}
RESOURCES = {
    "backend/app/conversation/context_templates/prompt.md",
    "backend/app/conversation/context_templates/summary_prefix.md",
    "third_party/codex-context/prompt.md",
    "third_party/codex-context/summary_prefix.md",
    "frontend/public/fonts/OFL.txt",
    "requirements/local-document.txt",
    "requirements/realtime.txt",
    "evaluation/mtrag/prompts/query_rewrite_v2.txt",
    "evaluation/mtrag/prompts/query_rewrite_v2_1.txt",
}
DOCUMENT_SUFFIXES = {
    ".md",
    ".rst",
    ".txt",
    ".doc",
    ".docx",
    ".pdf",
    ".ppt",
    ".pptx",
    ".odt",
    ".adoc",
    ".rtf",
}


def main() -> int:
    tracked = set(
        subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        .decode("utf-8")
        .split("\0")
    ) - {""}
    forbidden = sorted(
        name
        for name in tracked
        if (name.startswith("docs/") or Path(name).suffix.lower() in DOCUMENT_SUFFIXES)
        and name not in HELP | RESOURCES
    )
    missing = sorted(HELP - tracked)
    for name in forbidden:
        print(f"Internal documentation must remain local: {name}")
    for name in missing:
        print(f"Required startup/user help is missing: {name}")
    if forbidden or missing:
        return 1
    print(f"Public documentation scope passed: {len(HELP)} startup/user-help files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
