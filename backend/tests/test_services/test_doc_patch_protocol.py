"""Tests for the exact-line patch protocol (``_doc_patch_protocol``).

This is the security-critical anti-injection / anti-corruption layer underneath
``memory_document_service`` (user_profile / learning_strategy). Ported from the
old checkpoint-3 F4 coverage when the single-doc service it used to live behind
was deleted in MEM-CUTOVER — the protocol itself is unchanged and still load-
bearing, so it keeps direct tests.
"""
from __future__ import annotations

from app.services.memory._doc_patch_protocol import _normalize_line, apply_patches


# ── _normalize_line: the anti-injection normaliser ───────────────────────


def test_normalize_collapses_embedded_newlines():
    # A patch line with embedded newlines must fold to ONE physical line, or a
    # later ``lines.index(match_line)`` lookup breaks and content scatters into
    # the wrong section.
    assert _normalize_line("理解 A\n然后 B") == "理解 A 然后 B"
    assert _normalize_line("- multi\r\nline value") == "- multi line value"


def test_normalize_nfkc_folds_fullwidth():
    # Fullwidth ⇄ halfwidth must collide so an LLM re-rendering a section header
    # with fullwidth chars doesn't drop every patch for it.
    assert _normalize_line("Ｓｔｒｉｐｅ") == "Stripe"
    assert _normalize_line("１２３") == "123"


def test_normalize_strips_trailing_period():
    assert _normalize_line("已掌握 Redis。") == "已掌握 Redis"
    assert _normalize_line("done.") == "done"


# ── apply_patches: add / update / delete / section ───────────────────────


def test_add_appends_then_idempotent():
    r = apply_patches("", [{"op": "add", "new_line": "- x"}])
    assert r.applied == 1 and "- x" in r.body
    r2 = apply_patches(r.body, [{"op": "add", "new_line": "- x"}])
    assert r2.skipped == 1 and r2.applied == 0  # already present


def test_add_into_named_section():
    body = "## 已掌握的认知\n- a"
    r = apply_patches(body, [{"op": "add", "section": "已掌握的认知", "new_line": "- b"}])
    assert r.applied == 1
    lines = r.body.splitlines()
    assert "- a" in lines and "- b" in lines


def test_update_replaces_matching_line():
    r = apply_patches("- old", [{"op": "update", "match_line": "- old", "new_line": "- new"}])
    assert r.applied == 1 and "- new" in r.body and "- old" not in r.body


def test_update_drops_when_no_match():
    r = apply_patches("- a", [{"op": "update", "match_line": "- nope", "new_line": "- x"}])
    assert r.dropped == 1 and r.applied == 0 and r.body == "- a"


def test_delete_removes_line():
    r = apply_patches("- a\n- b", [{"op": "delete", "match_line": "- a"}])
    assert r.applied == 1 and "- a" not in r.body and "- b" in r.body


def test_section_header_injection_rejected():
    # A ``new_line`` that impersonates a ## header must be dropped at parse so it
    # can't inject a fake section the finder later treats as real.
    r = apply_patches("- a", [{"op": "add", "new_line": "## fake"}])
    assert r.applied == 0 and "## fake" not in r.body
