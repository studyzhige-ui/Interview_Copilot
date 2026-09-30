# Process-exit test race (CI #143)

The downloaded Python 3.13 JUnit report for remote commit
`abca9f0bf8f524ee78905819a30daac4f2dd0432` has 2245 cases: 2241 passed,
1 failed, 3 skipped. The failure is `test_parent_death_terminates_resident_child`:
reading `/proc/<pid>/status` raised `ProcessLookupError` after the process exited.
The suite body took 321.053 seconds; workflow wall time is a different measure.

Use one Linux test-only liveness helper for IPC and isolated-process campaigns.
Treat ENOENT and ESRCH as exited, preserve zombie semantics, and propagate
permission or unrelated I/O failures. Do not widen to all OSError, remove the
parent-death test, increase deadlines, retry failures, or change production code.

Validation: 35 tests passed (IPC, process tree cleanup and deterministic /proc
race cases). Real subprocesses are used, but no GPU/model verification is claimed.
This patch is based on files unchanged between the verified source artifact
`91393260` and remote HEAD `abca9f0b`.
