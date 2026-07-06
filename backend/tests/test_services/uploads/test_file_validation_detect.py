"""Byte-level unit tests for detect_head_format (UP-6).

These pin the actual magic detection per PURPOSE_REGISTRY content kind —
especially the ``knowledge`` kind, whose gate must accept everything
document_formats.ALLOWED_KNOWLEDGE_EXTENSIONS can parse (html/markdown/
csv/json/code/images/legacy Office) while still rejecting binary junk.
"""
from __future__ import annotations

import pytest

from app.services.uploads.file_validation import detect_head_format

_PDF = b"%PDF-1.7 xxxxxxxxxxxxxxxxxxxxxxxx"
_ZIP = b"PK\x03\x04" + bytes(28)
_OLE = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1]) + bytes(24)
_PNG = bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A]) + bytes(24)
_EXE = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00" + bytes(22)  # PE header (has NULs)
_HTML = b"<!doctype html><html><head>tests"
_JSON = b'{"key": "value", "n": 1, "b": tr'
_WEBM = b"\x1a\x45\xdf\xa3" + bytes(28)
_M4A_ISO5 = bytes([0, 0, 0, 24]) + b"ftypiso5" + bytes(20)
_MP3 = b"ID3\x04\x00" + bytes(27)


@pytest.mark.parametrize(
    "head,kind,ext,expected_ok",
    [
        # document (strict resume/JD family)
        (_PDF, "document", ".pdf", True),
        (_ZIP, "document", ".docx", True),
        (b"# markdown notes\nplain text ok", "document", ".md", True),
        (_EXE, "document", ".pdf", False),
        (_HTML, "document", ".html", False),  # html not in the resume family
        # knowledge (everything the knowledge whitelist parses)
        (_PDF, "knowledge", ".pdf", True),
        (_ZIP, "knowledge", ".pptx", True),
        (_OLE, "knowledge", ".doc", True),
        (_PNG, "knowledge", ".png", True),
        (_HTML, "knowledge", ".html", True),
        (_JSON, "knowledge", ".json", True),
        (b"def main():\n    return 42\n# ok", "knowledge", ".py", True),
        (_EXE, "knowledge", ".html", False),  # binary junk still blocked
        # audio
        (_MP3, "audio", ".mp3", True),
        (_WEBM, "audio", ".webm", True),
        (_M4A_ISO5, "audio", ".m4a", True),  # Safari MediaRecorder audio/mp4
        (_PDF, "audio", ".mp3", False),
        # image
        (_PNG, "image", ".png", True),
        (_EXE, "image", ".png", False),
        # text
        (b"hello plain text", "text", "", True),
        (_EXE, "text", "", False),
        # empty head never passes
        (b"", "knowledge", ".txt", False),
    ],
)
def test_detect_head_format(head, kind, ext, expected_ok):
    detected = detect_head_format(head, kind, ext)
    assert (detected is not None) == expected_ok, (kind, ext, detected)


def test_chinese_text_head_cut_mid_character_still_passes():
    """A 32-byte window can cut a UTF-8 multibyte char — not binary."""
    head = ("这是一份中文简历，包含多字节字符" .encode("utf-8"))[:32]
    assert detect_head_format(head, "knowledge", ".txt") is not None
