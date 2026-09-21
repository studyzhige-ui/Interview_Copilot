"""Finite local TTS wire contract. Generated audio is not a playback receipt.

The envelope fits the existing 4 MiB IPC frame. No paths, URLs, voice cloning
prompts or caller-selected executable/model settings cross this boundary.
"""

from __future__ import annotations

import base64
import binascii
import hashlib

from .errors import ProtocolError

SYNTHESIS_CONTRACT = "qwen-tts-0.1.1-custom-voice-pcm24-v1"
SYNTHESIS_TOKENS = 1024
SAMPLE_RATE = 24000
MAX_SECONDS = 60
MAX_PCM_BYTES = SAMPLE_RATE * MAX_SECONDS * 2
MAX_TEXT_CHARACTERS = 600
VOICES = frozenset(
    {
        "Vivian",
        "Serena",
        "Uncle_Fu",
        "Dylan",
        "Eric",
        "Ryan",
        "Aiden",
        "Ono_Anna",
        "Sohee",
    }
)
LANGUAGES = frozenset(
    {
        "Auto",
        "Chinese",
        "English",
        "Japanese",
        "Korean",
        "German",
        "French",
        "Russian",
        "Portuguese",
        "Spanish",
        "Italian",
    }
)


def validate_synthesis_request(task):
    text, voice, language = task["text"], task["voice"], task["language"]
    if (
        task["operation"] != "synthesize"
        or not isinstance(text, str)
        or not text.strip()
        or len(text) > MAX_TEXT_CHARACTERS
        or len(text.encode("utf-8")) > MAX_TEXT_CHARACTERS * 4
        or not isinstance(voice, str)
        or voice not in VOICES
        or not isinstance(language, str)
        or language not in LANGUAGES
    ):
        raise ProtocolError("invalid_synthesis_input")
    return task


def encode_synthesis_result(task, pcm: bytes) -> dict:
    if not isinstance(pcm, bytes) or not 0 < len(pcm) <= MAX_PCM_BYTES or len(pcm) % 2:
        raise ProtocolError("invalid_synthesis_pcm")
    return {
        "encoding": "pcm_s16le",
        "sample_rate": SAMPLE_RATE,
        "samples": len(pcm) // 2,
        "sha256": hashlib.sha256(pcm).hexdigest(),
        "data": base64.b64encode(pcm).decode("ascii"),
        "text_sha256": hashlib.sha256(task["text"].encode("utf-8")).hexdigest(),
        "voice": task["voice"],
        "language": task["language"],
    }


def decode_synthesis_result(task, value) -> bytes:
    if not isinstance(value, dict) or set(value) != {
        "encoding",
        "sample_rate",
        "samples",
        "sha256",
        "data",
        "text_sha256",
        "voice",
        "language",
    }:
        raise ProtocolError("invalid_synthesis_result")
    if (
        value["encoding"] != "pcm_s16le"
        or type(value["sample_rate"]) is not int
        or value["sample_rate"] != SAMPLE_RATE
        or type(value["samples"]) is not int
        or not 0 < value["samples"] <= SAMPLE_RATE * MAX_SECONDS
        or value["text_sha256"]
        != hashlib.sha256(task["text"].encode("utf-8")).hexdigest()
        or value["voice"] != task["voice"]
        or value["language"] != task["language"]
    ):
        raise ProtocolError("synthesis_identity_mismatch")
    encoded = value["data"]
    if not isinstance(encoded, str) or len(encoded) > (MAX_PCM_BYTES + 2) // 3 * 4:
        raise ProtocolError("synthesis_output_capacity")
    try:
        pcm = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ProtocolError("invalid_synthesis_base64") from None
    if (
        len(pcm) != value["samples"] * 2
        or hashlib.sha256(pcm).hexdigest() != value["sha256"]
    ):
        raise ProtocolError("synthesis_audio_identity_mismatch")
    return pcm


def validate_synthesis_result(task, value):
    decode_synthesis_result(task, value)
    return value
