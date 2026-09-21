# Hermetic synthetic-process regressions

An expanded local runtime campaign exposed three pre-existing environment
assumptions, separate from the evidence changes. Two short-deadline process-tree
tests could time out during Python site initialization, before the synthetic
child or descendant wrote its PID. Those children use only stdlib. They now use
`-I -S -B`, including the nested child, so unrelated installed site hooks cannot
consume their execution budget. Deadlines, SIGTERM-ignoring behavior, SIGKILL,
repeated cancellation and descendant liveness assertions are unchanged.

The offline-before-import test pointed PYTHONPATH at the repository root instead
of `backend`; an editable installation masked the mistake in CI. It now points
at the actual source root, and passes when launched from an unrelated temporary
working directory without relying on editable installation.

The corrected 18-node process/offline campaign passed locally. The expanded
241-node deterministic broker/audio/process/assets/scoring campaign also passed.
Tests needing missing local `llama_index` / `edge_tts` dependencies were not
labelled passed or deleted; their normal full-dependency CI coverage remains.
No production runtime behavior, model weights or provider calls changed here.
