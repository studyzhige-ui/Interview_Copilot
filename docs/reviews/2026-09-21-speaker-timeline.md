# Speaker timeline correctness and lookup cost

A word spanning 0.9–1.1 seconds touched speaker A at 0–1 and speaker B at
1–2. The prior implementation marked that word as overlapping speech even
though there was no positive-duration coexistence. This was reproduced before
changing the implementation.

`SpeakerTimeline` now sweeps the regular tracks once to index actual multi-voice
regions, counting distinct speaker identities rather than intervals. Duplicate
and nested intervals from one speaker cannot fabricate overlap; coincident
start/end boundaries have no duration. Primary identity and its coverage-based
confidence still come from the exclusive track, independently of overlap.

Exclusive-track lookup uses binary search over starts and prefix ends. For the
validated non-overlapping exclusive track this visits only intersecting
intervals after O(log N) indexing, instead of rescanning the whole recording for
each word. Overlap queries are O(log N) after one O(N log N) sweep. Original
regular/exclusive observations, source identities, words and schema v2 remain
unchanged; existing persisted evidence is not silently rewritten.

Seven deterministic test nodes cover boundaries, gaps, nested/duplicate speaker
intervals, missing exclusive coverage and canonical composition. One node
compares 200 seeded, unordered variable-duration word queries against an
independent pairwise-interval reference. This is algorithmic validation, not
GPU, ASR-quality or end-to-end long-recording performance validation.

The full import-graph gate also inspects type-only and function-local imports.
It found reverse dependencies in the initial timeline and provider composition
changes. The timeline now accepts a read-only structural interval protocol;
provider observation dataclasses live in `evidence_contracts`, imported by both
execution adapters and the compositor. No gate is weakened, no dynamic import
is used to hide an edge, and the public evidence schema is unchanged.
