# Interview Copilot implementation Stage Specs

This directory freezes implementation details for the stages defined by
[`full-cycle-career-copilot.md`](../full-cycle-career-copilot.md). The parent
document remains the only product and target-architecture authority. These
specifications may choose physical fields, API seams, failure handling and
executable gates, but they must not create a second product meaning.

The implementation order is dependency order rather than six isolated
systems. Every stage uses the same Conversation admission, Context Assembly,
ToolDefinition/Policy/Executor/ToolResult path, ownership checks and typed
server-side redaction.

| Stage | Specification | Status |
|---|---|---|
| 0 | `stage-0-runtime.md` | implemented; release validation pending |
| 1 | `stage-1-attachments.md` | implemented; release validation pending |
| 2 | `stage-2-career-state.md` | implemented; release validation pending |
| 3 | `stage-3-artifacts-interviews.md` | implemented; release validation pending |
| 4 | `stage-4-connectors-automation.md` | implemented; live Connector/deployment validation pending |
| 5 | `stage-5-evaluation-memory.md` | canonical code implemented; automatic Memory producer remains release-gated off |

“Implemented” here means the physical contract exists in the current branch.
It is not a release claim. A stage becomes release-ready only after its listed
tests, the Alembic upgrade/downgrade checks, the complete backend suite, the
complete frontend suite and the cross-stage scenario gate all pass against the
same worktree.

The executable cross-stage gate is
`python evaluation/career_scenario_eval.py`. It deliberately runs backend and
frontend groups serially, hides CUDA from test children and owns their timeout,
so release validation cannot leave overlapping model-loading `pytest`
processes behind. A timeout or missing mandatory test is a failed gate, never a
reason to start a duplicate broad run.
