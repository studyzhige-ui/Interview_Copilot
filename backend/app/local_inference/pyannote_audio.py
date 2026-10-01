"""Official pyannote Community adapter, loaded only in its isolated interpreter.

Reference: pyannote.audio 4 SpeakerDiarization/DiarizeOutput. Each call receives
at most 30 seconds of PCM, never an arbitrary file path, URL or cloud token.
"""

from __future__ import annotations

from .audio import SAMPLE_RATE, decode_pcm
from .speaker_audio import DIARIZATION_MAX_SPEAKERS, validate_diarization_result


def load(spec):
    import torch
    from pyannote.audio import Pipeline

    torch.set_num_threads(4)
    if spec.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("cuda_unavailable")
    # The broker has verified a local asset path. Offline flags and the child's
    # network-denying audit hook remain active; this is not an OS sandbox.
    model = Pipeline.from_pretrained(spec.model_path)
    model.to(torch.device("cpu" if spec.device == "cpu" else "cuda:0"))
    model.segmentation_batch_size = 1
    model.embedding_batch_size = 1
    return model


def infer(model, spec, task):
    import numpy as np
    import torch

    samples = np.frombuffer(decode_pcm(task["audio"]), dtype="<i2").astype(np.float32)
    samples /= 32768.0
    with torch.inference_mode():
        output = model(
            {
                "waveform": torch.from_numpy(samples).unsqueeze(0),
                "sample_rate": SAMPLE_RATE,
            },
            min_speakers=1,
            max_speakers=DIARIZATION_MAX_SPEAKERS,
        )
        regular = output.speaker_diarization
        exclusive = output.exclusive_speaker_diarization
        identities = regular.labels()
        embeddings = output.speaker_embeddings
        if (
            embeddings is None
            or embeddings.ndim != 2
            or len(embeddings) != len(identities)
        ):
            raise ValueError("diarization_embeddings_missing")

        def intervals(annotation):
            return sorted(
                [
                    {
                        "start": float(segment.start),
                        "end": float(segment.end),
                        "speaker_id": label,
                    }
                    for segment, _, label in annotation.itertracks(yield_label=True)
                ],
                key=lambda item: (item["start"], item["end"], item["speaker_id"]),
            )

        result = {
            "regular": intervals(regular),
            "exclusive": intervals(exclusive),
            "speakers": [
                {"speaker_id": label, "embedding": embeddings[i].tolist()}
                for i, label in enumerate(identities)
            ],
        }
        if spec.device == "cuda":
            torch.cuda.synchronize()
    return validate_diarization_result(task, result)
