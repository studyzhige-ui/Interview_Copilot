"""Pinned qwen-tts CustomVoice adapter, imported only by the owned ML child.

The 0.1.1 wrapper does not return a termination reason with decoded waveforms.
Use its codec-generation boundary to reject budget-adjacent output BEFORE
waveform decoding. Neither this guard nor a returned WAV proves speech quality.
This is finite synthesis, NOT streaming synthesis or a cloned human voice.
"""

from __future__ import annotations

from importlib.metadata import version

from .synthesis_audio import MAX_PCM_BYTES, SAMPLE_RATE, encode_synthesis_result


def load(spec):
    if version("qwen-tts") != "0.1.1":
        raise RuntimeError("unsupported_qwen_tts_adapter_version")
    import torch
    from qwen_tts import Qwen3TTSModel

    torch.set_num_threads(4)
    if spec.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("cuda_unavailable")
    model = Qwen3TTSModel.from_pretrained(
        spec.model_path,
        dtype=torch.float32 if spec.device == "cpu" else torch.bfloat16,
        device_map="cpu" if spec.device == "cpu" else "cuda:0",
        local_files_only=True,
        trust_remote_code=False,
    )
    if model.model.tts_model_type != "custom_voice":
        raise ValueError("local_tts_requires_custom_voice_checkpoint")
    return model


def infer(model, spec, task):
    import numpy as np
    import torch

    voices = model.get_supported_speakers() or []
    languages = model.get_supported_languages() or []
    if task["voice"].lower() not in {s.lower() for s in voices} or (
        task["language"] != "Auto"
        and task["language"].lower() not in {s.lower() for s in languages}
    ):
        raise ValueError("unsupported_checkpoint_voice_or_language")
    with torch.inference_mode():
        # Versioned adapter seam from Qwen's 0.1.1 CustomVoice implementation.
        # Single input/speaker, no instruction or untrusted reference recording.
        input_ids = model._tokenize_texts([model._build_assistant_text(task["text"])])
        codes, _ = model.model.generate(
            input_ids=input_ids,
            instruct_ids=[None],
            languages=[task["language"]],
            speakers=[task["voice"]],
            non_streaming_mode=True,
            **model._merge_generate_kwargs(max_new_tokens=spec.max_tokens),
        )
        if (
            len(codes) != 1
            or len(codes[0].shape) != 2
            or not 0 < codes[0].shape[0] < spec.max_tokens - 2
        ):
            raise ValueError("synthesis_incomplete_or_token_capacity")
        waves, rate = model.model.speech_tokenizer.decode([{"audio_codes": codes[0]}])
        if type(rate) is not int or rate != SAMPLE_RATE or len(waves) != 1:
            raise ValueError("invalid_synthesis_waveform_format")
        wave = np.asarray(waves[0])
        if (
            wave.ndim != 1
            or not 0 < wave.size * 2 <= MAX_PCM_BYTES
            or wave.dtype.kind != "f"
            or not np.isfinite(wave).all()
            or (np.abs(wave) > 1).any()
        ):
            raise ValueError("invalid_synthesis_waveform")
        pcm = np.rint(wave * 32767).astype("<i2").tobytes()
        if spec.device == "cuda":
            torch.cuda.synchronize()
    return encode_synthesis_result(task, pcm)
