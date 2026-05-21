"""Generic exact-line-match patch protocol for memory documents.

Why generic
-----------
``user_profile_doc_service`` invented this protocol for a single-doc-per-user
case. The new memory architecture (knowledge / strategy / habit / dreaming)
all need the same defensive update pattern, against documents that may be
markdown blobs with section headers + bullet lines.

Protocol shape
--------------
A *patch* is one of three operations:

* ``add``    — append ``new_line`` under ``section_header`` (optional —
               defaults to end of doc). No ``match_line`` required.
* ``update`` — find ``match_line`` (exact match after normalisation),
               replace with ``new_line``. Dropped if no match.
* ``delete`` — find ``match_line``, remove. Dropped if no match.

Sections
--------
The protocol understands markdown ``## Section`` headers. ``add`` with a
``section`` argument inserts the new line at the bottom of that section,
creating the section header if missing. Without ``section`` the line goes
at the end of the doc.

Why exact-match is the safety floor
-----------------------------------
LLMs hallucinate. If we let an LLM rewrite a whole doc, a single bad
generation can erase real data. Exact-line-match means:

* The patch names a specific existing line to modify. If the LLM
  hallucinates a line that doesn't exist, we drop the patch with a log
  warning and the doc is unchanged.
* Unrelated lines cannot be silently rewritten because we never rewrite
  the whole doc.
* Concurrent updates (a parallel realtime extraction touching the same
  doc while a dream is running) are conflict-safe: the second patch's
  ``match_line`` either still matches (apply) or doesn't (drop), but the
  doc never ends up in a corrupt half-merged state.

This module is pure — no DB, no LLM. Callers load their doc body, pass it
through ``apply_patches``, and write the result back inside their own
transaction.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


def _nfkc(s: str) -> str:
    """NFKC-normalise a string. Folds fullwidth/halfwidth digits,
    compatibility brackets, etc. Without this, an LLM that rerenders
    ``"已掌握的认知"`` with a fullwidth space or a fullwidth digit in
    the section header would mismatch the body's halfwidth version
    and every ``add`` patch for that section would be dropped."""
    return unicodedata.normalize("NFKC", s or "")


@dataclass(frozen=True)
class DocPatch:
    """One unit of change."""

    op: str                                  # "add" | "update" | "delete"
    match_line: str = ""                     # required for update / delete
    new_line: str = ""                       # required for add / update
    section: Optional[str] = None            # optional ## header for add


@dataclass
class PatchResult:
    body: str
    applied: int = 0
    dropped: int = 0
    skipped: int = 0


# ── normalisation ──────────────────────────────────────────────────────


def _normalize_line(line: str) -> str:
    """Coerce LLM-supplied line content into a single physical line.

    Steps:
      0. NFKC-normalise so fullwidth ⇄ halfwidth variants collide as
         the same string.
      1. Collapse any embedded newlines / carriage returns into spaces.
         Without this, an LLM that emits ``"- multi\\nline value"``
         would be split into two lines by ``"\\n".join(lines)`` on
         write, breaking the next patch's ``lines.index(match_line)``
         lookup AND scattering content into the wrong section after
         the next canonicalise.
      2. Squash runs of whitespace introduced by step 1.
      3. Strip trailing whitespace.
      4. Strip trailing CJK / ASCII period (LLMs sometimes append one
         and sometimes don't — equality should ignore it).
    """
    if not line:
        return ""
    line = _nfkc(line)
    # Step 1: defang embedded line breaks.
    line = line.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    # Step 2: collapse repeated whitespace (only inner; we preserve
    # leading "- " spacing via the bullet handling in normalisation
    # callers).
    line = " ".join(line.split())
    # Step 4 (3 is implicit in split).
    return line.rstrip("。.")


def _is_section_header(line: str) -> bool:
    s = _nfkc(line or "").lstrip()
    return s.startswith("##") and not s.startswith("###")


def _section_label(header_line: str) -> str:
    """Extract the section name from a ``## Foo`` line, NFKC-normalised."""
    s = _nfkc(header_line or "").lstrip()
    if not s.startswith("##"):
        return ""
    return s.lstrip("#").strip()


# ── core ───────────────────────────────────────────────────────────────


def parse_patches(raw_patches: Iterable[Any]) -> list[DocPatch]:
    """Coerce a list of dicts (from a JSON-parsed LLM response) into
    ``DocPatch`` instances. Invalid entries are silently dropped — they
    don't even count as ``dropped`` in the PatchResult, they never
    became patches in the first place."""
    out: list[DocPatch] = []
    for raw in raw_patches or []:
        if isinstance(raw, DocPatch):
            out.append(raw)
            continue
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op") or "").strip().lower()
        if op not in {"add", "update", "delete"}:
            continue
        match_line = _normalize_line(str(raw.get("match_line") or ""))
        new_line = _normalize_line(str(raw.get("new_line") or ""))
        section = raw.get("section")
        if isinstance(section, str) and section.strip():
            # NFKC-normalise so it matches the body's section header
            # under the same rule.
            section = _nfkc(section).strip()
        else:
            section = None

        if op == "add" and not new_line:
            continue
        if op in {"update", "delete"} and not match_line:
            continue
        if op == "update" and not new_line:
            continue

        out.append(DocPatch(op=op, match_line=match_line, new_line=new_line, section=section))
    return out


def apply_patches(body: str, raw_patches: Iterable[Any]) -> PatchResult:
    """Apply a list of patches to a markdown body.

    Returns the new body plus counts of (applied, dropped, skipped).
    ``skipped`` covers idempotent adds (the line already exists).
    """
    patches = parse_patches(raw_patches)
    if not patches:
        return PatchResult(body=body, applied=0, dropped=0, skipped=0)

    lines = (body or "").splitlines()
    applied = dropped = skipped = 0

    for patch in patches:
        if patch.op == "add":
            new_lines, did_apply, did_skip = _apply_add(lines, patch)
            lines = new_lines
            applied += 1 if did_apply else 0
            skipped += 1 if did_skip else 0
        elif patch.op == "update":
            new_lines, did_apply, did_drop = _apply_update(lines, patch)
            lines = new_lines
            applied += 1 if did_apply else 0
            dropped += 1 if did_drop else 0
        elif patch.op == "delete":
            new_lines, did_apply, did_drop = _apply_delete(lines, patch)
            lines = new_lines
            applied += 1 if did_apply else 0
            dropped += 1 if did_drop else 0

    new_body = "\n".join(lines).strip("\n")
    return PatchResult(body=new_body, applied=applied, dropped=dropped, skipped=skipped)


# ── operations ─────────────────────────────────────────────────────────


def _apply_add(lines: list[str], patch: DocPatch) -> tuple[list[str], bool, bool]:
    new_line = patch.new_line
    if new_line in lines:
        return lines, False, True  # skipped (idempotent)

    if patch.section is None:
        lines.append(new_line)
        return lines, True, False

    # Find or create the section header. Lookup is case-sensitive after
    # whitespace normalisation — LLM should echo back the exact header
    # name we surfaced in the prompt.
    header = f"## {patch.section}"
    insert_at: Optional[int] = None
    for i, line in enumerate(lines):
        if _is_section_header(line) and _section_label(line) == patch.section:
            # Walk forward to find the last line of this section (next
            # ## header or end of doc).
            end = len(lines)
            for j in range(i + 1, len(lines)):
                if _is_section_header(lines[j]):
                    end = j
                    break
            insert_at = end
            break

    if insert_at is not None:
        # Insert before the next section's header (so trailing blank
        # lines from the previous section stay attached to it).
        # Trim trailing blank lines inside the current section first to
        # keep insertions tight.
        cut = insert_at
        while cut > 0 and not lines[cut - 1].strip():
            cut -= 1
        lines.insert(cut, new_line)
        return lines, True, False

    # Section doesn't exist — create it at the doc end.
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(header)
    lines.append(new_line)
    return lines, True, False


def _apply_update(lines: list[str], patch: DocPatch) -> tuple[list[str], bool, bool]:
    try:
        idx = lines.index(patch.match_line)
    except ValueError:
        logger.info(
            "doc_patch: drop update — match_line not found: %r",
            patch.match_line,
        )
        return lines, False, True

    # Don't create a duplicate. If the replacement already appears
    # somewhere else in the doc, treat the update as a delete instead.
    if patch.new_line in lines and lines[idx] != patch.new_line:
        del lines[idx]
    else:
        lines[idx] = patch.new_line
    return lines, True, False


def _apply_delete(lines: list[str], patch: DocPatch) -> tuple[list[str], bool, bool]:
    try:
        lines.remove(patch.match_line)
        return lines, True, False
    except ValueError:
        logger.info(
            "doc_patch: drop delete — match_line not found: %r",
            patch.match_line,
        )
        return lines, False, True


__all__ = [
    "DocPatch",
    "PatchResult",
    "apply_patches",
    "parse_patches",
]
