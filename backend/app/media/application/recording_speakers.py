"""Recording-wide identity from the configured diarization model's clustering.

Only bounded acoustic observations are retained between PCM windows. They are
never persisted: transcript tracks keep opaque recording-local speaker IDs.
"""

from app.local_inference.speaker_audio import MAX_RECORDING_OBSERVATIONS


class RecordingSpeakers:
    def __init__(self):
        self.embeddings = []

    def observe(self, observations):
        if len(self.embeddings) + len(observations) > MAX_RECORDING_OBSERVATIONS:
            raise ValueError("recording_clustering_capacity")
        self.embeddings.extend(observations)

    async def resolve(self, client, *, min_speakers, max_speakers):
        if not self.embeddings:
            return []
        centroids = await client.cluster(
            self.embeddings, min_speakers=min_speakers, max_speakers=max_speakers
        )
        self.embeddings.clear()
        return centroids
