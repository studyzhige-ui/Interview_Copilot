"""Trusted local qwen-asr adapter, imported only by the isolated ML child.

Reference API: QwenLM/Qwen3-ASR README, Transformers / ForcedAligner examples.
Do not select vLLM here: its continuous streaming protocol is a separate feature.
"""

from __future__ import annotations

from .audio import SAMPLE_RATE, decode_pcm, validate_audio_result

LANGUAGES = {
    "zh": "Chinese",
    "en": "English",
    "yue": "Cantonese",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "ru": "Russian",
    "it": "Italian",
}


def load(spec):
    import torch
    from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner

    torch.set_num_threads(4)
    if spec.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("cuda_unavailable")
    common = dict(
        dtype=torch.float32 if spec.device == "cpu" else torch.bfloat16,
        device_map="cpu" if spec.device == "cpu" else "cuda:0",
        local_files_only=True,
        trust_remote_code=False,
    )
    if spec.role == "transcription":
        return Qwen3ASRModel.from_pretrained(
            spec.model_path,
            max_inference_batch_size=1,
            max_new_tokens=spec.max_tokens,
            **common,
        )
    return Qwen3ForcedAligner.from_pretrained(spec.model_path, **common)


def infer(model, spec, task):
    import numpy as np
    import torch

    samples = (
        np.frombuffer(decode_pcm(task["audio"]), dtype="<i2").astype(np.float32)
        / 32768.0
    )
    requested_language = task["language"]
    language = LANGUAGES.get(requested_language, requested_language)
    with torch.inference_mode():
        if spec.role == "transcription":
            result = model.transcribe(
                audio=(samples, SAMPLE_RATE),
                language=language,
                return_time_stamps=False,
            )
            if len(result) != 1:
                raise ValueError("asr_result_count")
            value = {
                "text": result[0].text,
                "language": result[0].language,
                "words": [],
            }
        else:
            result = model.align(
                audio=(samples, SAMPLE_RATE), text=task["text"], language=language
            )
            if len(result) != 1:
                raise ValueError("alignment_result_count")
            words = []
            for item in result[0]:
                start, end = float(item.start_time), float(item.end_time)
                # Upstream can produce a zero-length alignment. Keep the token,
                # explicitly unaligned; never invent an interval/confidence.
                if start == end:
                    start, end = None, None
                words.append({"text": item.text, "start": start, "end": end})
            value = {
                "text": task["text"],
                "language": requested_language,
                "words": words,
            }
        if spec.device == "cuda":
            torch.cuda.synchronize()
    return validate_audio_result(task, value)
