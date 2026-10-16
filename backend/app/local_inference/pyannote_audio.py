"""Official pyannote Community adapter, loaded only in its isolated interpreter.

Reference: pyannote.audio 4 SpeakerDiarization/DiarizeOutput. Each call receives
at most 30 seconds of PCM, never an arbitrary file path, URL or cloud token.
"""

from __future__ import annotations

from .audio import SAMPLE_RATE, decode_pcm
from .speaker_audio import validate_diarization_result


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
    from pyannote.core import Segment

    if task["operation"] == "cluster":
        from pyannote.core import SlidingWindow, SlidingWindowFeature
        from .speaker_audio import decode_embeddings, validate_clustering_result

        embeddings = np.array(decode_embeddings(task["embeddings"]))[:, None, :]
        active = np.ones((len(embeddings), 1, 1))
        # VBx needs the filtered observations, not one averaged centroid per
        # window: averaging discards the sample support of each voice.
        _, _, centroids = model.clustering(
            embeddings,
            segmentations=SlidingWindowFeature(
                active, SlidingWindow(duration=1, step=1)
            ),
            min_clusters=task["min_speakers"],
            max_clusters=task["max_speakers"],
        )
        return validate_clustering_result(task, centroids.tolist())

    samples = np.frombuffer(decode_pcm(task["audio"]), dtype="<i2").astype(np.float32)
    samples /= 32768.0
    with torch.inference_mode():
        audio = {
            "waveform": torch.from_numpy(samples).unsqueeze(0),
            "sample_rate": SAMPLE_RATE,
        }
        observations = []
        if task["centroids"]:
            output = _reconstruct(model, audio, np.asarray(task["centroids"]))
        else:
            from pyannote.audio.utils.signal import binarize

            captured = {}

            def capture(step, value, **kwargs):
                if step in {"segmentation", "embeddings"}:
                    captured[step] = value

            output = model(
                audio, min_speakers=1, max_speakers=task["max_speakers"], hook=capture
            )
            if "embeddings" in captured:
                segments = captured["segmentation"]
                binary = (
                    segments
                    if model._segmentation.model.specifications.powerset
                    else binarize(
                        segments,
                        onset=model.segmentation.threshold,
                        initial_state=False,
                    )
                )
                filtered, _, _ = model.clustering.filter_embeddings(
                    captured["embeddings"], segmentations=binary
                )
                observations = filtered.tolist()
        extent = Segment(0, len(samples) / SAMPLE_RATE)
        regular = output.speaker_diarization.crop(extent)
        exclusive = output.exclusive_speaker_diarization.crop(extent)

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
            "embeddings": observations,
        }
        if spec.device == "cuda":
            torch.cuda.synchronize()
    return validate_diarization_result(task, result)


def _reconstruct(model, audio, centroids):
    """Reconstruct local frames using the whole recording's speaker centroids."""
    import numpy as np
    from scipy.spatial.distance import cdist
    from pyannote.audio.pipelines.speaker_diarization import DiarizeOutput
    from pyannote.audio.utils.signal import binarize

    segments = model.get_segmentations(audio)
    binary = (
        segments
        if model._segmentation.model.specifications.powerset
        else binarize(segments, onset=model.segmentation.threshold, initial_state=False)
    )
    embeddings = model.get_embeddings(
        audio, binary, exclude_overlap=model.embedding_exclude_overlap
    )
    scores = 2 - cdist(
        embeddings.reshape(-1, embeddings.shape[-1]),
        centroids,
        metric=model.clustering.metric,
    )
    scores = scores.reshape(*embeddings.shape[:2], len(centroids))
    active = binary.data.sum(axis=1) > 0
    scores[~active] = -1
    clusters = model.clustering.constrained_argmax(scores)
    clusters[~active] = -2
    count = model.speaker_count(
        binary, model._segmentation.model.receptive_field, warm_up=(0.0, 0.0)
    )
    count.data = np.minimum(count.data, len(centroids)).astype(np.int8)
    regular = model.to_annotation(
        model.reconstruct(segments, clusters, count),
        min_duration_on=0,
        min_duration_off=model.segmentation.min_duration_off,
    )
    count.data = np.minimum(count.data, 1)
    exclusive = model.to_annotation(
        model.reconstruct(segments, clusters, count),
        min_duration_on=0,
        min_duration_off=model.segmentation.min_duration_off,
    )
    labels = regular.labels()
    names = {label: f"speaker_{label + 1:03d}" for label in labels}
    return DiarizeOutput(
        speaker_diarization=regular.rename_labels(mapping=names),
        exclusive_speaker_diarization=exclusive.rename_labels(mapping=names),
        speaker_embeddings=centroids[labels],
    )
