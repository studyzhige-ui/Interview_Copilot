# Interview Copilot implementation Stage Specs

> Status: Historical Implementation Reference as of 2026-08-26.
> Historical baseline: [`full-cycle-career-copilot.md`](../full-cycle-career-copilot.md).
> Current authority: [`career-agent-os-blueprint.md`](../career-agent-os-blueprint.md).

This directory preserves the physical Stage 0–5 contracts that were implemented
under the superseded 2026-08-13 baseline. These files are no longer current
Contracts or Vertical Slice Specs in the Career Agent OS authority hierarchy.
Their tested concurrency, persistence, provenance and recovery invariants remain
implementation evidence and may be adopted into new Contracts only after they
are checked against the current Blueprint.

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
