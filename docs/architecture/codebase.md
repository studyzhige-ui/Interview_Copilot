# Codebase architecture

> Status: Current implementation reference; non-normative for product and target architecture.
> Product and target-architecture authority: [`career-agent-os-blueprint.md`](./career-agent-os-blueprint.md).

This document describes the repository that exists today. It is a placement
guide for maintenance work, not a proposal for extra framework layers.

## Repository boundaries

| Path | Responsibility |
|---|---|
| `backend/app/main.py` | FastAPI composition root: middleware, lifecycle checks, static mounts, and routers |
| `backend/app/api/` | HTTP/SSE transport, authentication dependencies, request validation, and response mapping |
| `backend/app/schemas/` | Pydantic request and response contracts |
| `backend/app/services/` | Business use cases grouped by auth, chat, career state, artifacts, interviews, personalization, knowledge, resume, upload, voice, integrations, and model source |
| `backend/app/conversation/` | Chat/Agent conversation engine, strategy selection, planning, and event contracts |
| `backend/app/agent_runtime/` | Current ReAct execution, turn-local Tool catalog, MCP clients, Tool Calls, cancellation, and result storage; target Harness/Tool/Policy semantics are defined by `career-agent-os-blueprint.md` and future formal Contracts |
| `backend/app/rag/` | Parsing, cleaning, chunking, embedding/reranking providers, Milvus indexing, retrieval, and hydration |
| `backend/app/prompts/` | Production prompt text and prompt builders grouped by business purpose |
| `backend/app/models/` | SQLAlchemy persistence models only |
| `backend/app/db/` | SQLAlchemy and Redis connection ownership |
| `backend/app/core/` | Cross-cutting configuration, security, edition policy, storage, model factories, rate limiting, tracing, and runtime utilities |
| `backend/app/task_queue/` | Celery configuration plus the application-facing dispatch/revoke boundary |
| `backend/app/worker/` | Thin task entry points and worker-only outbox handlers |
| `backend/tests/` | Backend unit, service, API, migration, and worker regression tests, mirroring application areas |
| `frontend/src/api/` | Typed HTTP, upload, and SSE client boundary |
| `frontend/src/pages/` | Route-level product features |
| `frontend/src/components/` | Reusable layout and UI components |
| `frontend/src/hooks/`, `store/`, `lib/` | Browser behavior, client state, and framework-independent helpers |
| `alembic/` | Ordered database schema migrations; SQLAlchemy models are the target schema |
| `evaluation/` | Optional retrieval, generation, planner, and mock-interview quality evaluation |
| `scripts/` | Public setup/start/stop commands and explicit operator utilities |
| `docs/` | Current architecture, deployment, and user documentation |
| `docker-compose.yml` | Community infrastructure plus the optional complete `full` profile |

Runtime files, model weights, logs, generated reports, and user uploads belong
under `data/` and are not source code. Python bytecode and system-style
temporary files are redirected there by the supported launchers; application
code uses `core/runtime_files.py` for temporary files and bounded JSONL output.

## Runtime flow

```text
React page
  -> frontend API client
  -> FastAPI route / SSE endpoint
  -> domain service or conversation entry point
  -> PostgreSQL / Redis / S3 / Milvus / model provider

Long-running request
  -> API persists a job or turn
  -> Celery routes it by workload class
  -> Worker calls the same domain services
  -> API exposes persisted state or reconnectable events
```

The API process does not own long Agent execution. `turns` workers execute
conversation turns; `pipeline` workers handle document/index work;
`transcription` workers isolate speech workloads; `background` workers handle
model-backed interview review; `default` workers handle short
control, cleanup, maintenance, and catalog jobs.

The full Compose profile gives these five workload classes separate worker
services. The host development launcher keeps `turns` separate but combines
`default`, `background`, `pipeline`, and `transcription` in one local solo
worker to reduce the number of developer processes; queue routing remains the
same.

| Workload | Queue | Concurrency rule | Durable source of truth |
|---|---|---|---|
| Chat and Agent turns | `turns` | Dedicated worker; cancellation and usage telemetry | conversation, turn, checkpoint, and tool-call rows |
| Parsing, embedding, and vector synchronization | `pipeline` | Serialized where local model/GPU pressure requires it | PostgreSQL document/resume facts plus outbox jobs |
| Speech recognition and diarization | `transcription` | Isolated from all text workloads | interview record, transcript, and QA rows |
| Model-backed interview review | `background` | Bounded independently from ingestion | interview state and typed outbox jobs |
| Cleanup, catalog, scheduling, and sweepers | `default` | Short control work only | database status and idempotent maintenance rules |

Redis transports work; it is not the business source of truth. Worker tasks may
be delivered more than once, so handlers must claim or status-gate work before
side effects. Cross-system changes use the typed outbox and are claimed by
`job_type`; a slow LLM review job must never block a Milvus update or object
cleanup. PostgreSQL owns lifecycle state, object storage owns file bytes, and
Milvus is a rebuildable retrieval index.

## Shared invitation ingress and primary-model accounting

The invitation domain operation remains
`career/application/interview_invitation_operations.py`. UI, Agent and source
adapters do not each implement another invitation writer:

- A manual UI request first registers its exact command with
  `invitation_submission_service.py`. Execution and the shared Operation's
  verification/receipt link commit together. The browser keeps only an opaque,
  account-scoped request key in sessionStorage, not the invitation fields.
  Reload performs a read-only receipt lookup; only an explicit resume retries
  the exact registered command. `not_received` is not proof that a delayed POST
  cannot arrive. Cancellation uses the same owner lock and can create a
  tombstone before that delayed POST arrives. A committed operation is not
  undone by cancelling its ingress request.
- Gmail interview invitations use `gmail_invitation_adapter.py` and the same
  provider-neutral source/candidate/typed fact-confirmation flow as fixture
  observations. Confidence and task scopes never auto-confirm an interview.
  Missing dates/timezones stay missing until the user corrects them. The shared
  Operation binds exact facts, object selections and versions to the saved
  decision. Legacy invitation review approval hands off to this path, rather
  than appending a second invitation ProcessEvent. Other event types keep their
  existing lifecycle. Views project terminal status from the canonical
  candidate instead of inventing another editable Gmail business state.
- `services/chat/model_budget_service.py` admits primary Chat/Agent model calls
  atomically with `AgentModelDispatch`. Account UTC-day allowances survive
  application restart and conversation deletion. Same call identity is never
  a second dispatch permit. Known refusal releases token reservation but still
  consumes a call; uncertain requests hold their reservation until an explicit
  evidenced reconciliation. A completed response without usage consumes its
  conservative reservation instead of being counted as free. Cache categories
  are not added twice to logical prompt tokens; cumulative provider usage is
  merged component by component across native stream events.

This accounting covers **primary Chat/Agent only**, not internal model work,
compaction, embedding/reranking, speech or external Tools. It is not a monetary
invoice, provider price model or complete platform billing system. These limits
are separate from task completion, per-call inactivity timeouts and total stream
deadlines. The Models page exposes used/reserved allowances and this scope; it
never treats a failed status read as zero usage. Operators set the four documented
`MODEL_DAILY_*` / `MODEL_STREAM_*` settings. A day's limits freeze at its first
admitted request; changing an environment variable does not rewrite existing
usage windows. Reconciliation is an internal, evidence-requiring service seam,
not a model-callable budget-reset tool or a completed operator UI.

Migrations `0048` and `0049` add these state tables without rewriting existing
career facts. Account deletion cascades their records; conversation deletion
must not erase account usage. Pending manual commands necessarily contain the
user-supplied invitation fields on the server. Cancel clears their payload;
committed records retain the identity/receipt relationship. Do not expose or
log these payloads as diagnostics. Automatic retention/expiry for unresolved
commands and cancellation tombstones is not claimed: dropping a tombstone while
an old request can still arrive would invalidate cancellation safety.

Apply migrations before running the new application. Back up the database and
verify restore first. Downgrading below these revisions drops their accounting
and recovery records: export/reconcile them and quiesce pending requests first.
Do not use downgrade as a quota-reset or to erase outcome-unknown receipts.

## Storage value contracts

Database values follow two explicit rules, enforced by models, migrations and
architecture tests:

- Every lifecycle timestamp is timezone-aware UTC. `UTCDateTime` accepts an
  old naive value only at the compatibility boundary, interprets it as UTC,
  and always returns an aware UTC value. Migration `0004` converts PostgreSQL
  columns from `timestamp without time zone` to `timestamp with time zone`
  without shifting historical instants.
- Values the application reads and writes as dictionaries/lists use
  `JSONValue`: JSONB on PostgreSQL and JSON on SQLite. Opaque snapshots that
  are replaced or forwarded as a whole remain `Text`, including transcript
  segments, analysis/model snapshots, resume snapshots and provider wire
  configuration. They should move to JSONB only when a concrete containment,
  validation or indexing use case exists.

This is deliberately not a blanket “make every field JSONB” rule. Native
structured state such as turn budgets, MCP arguments, Outbox payloads and
ability evidence gets typed storage; large versioned artifacts retain their
document boundary.

Derived product scores have the same compatibility rule. Ability reports name
their continuous evidence scale (`evidence-v2`), publish its 0–100 bands,
aggregation and missing-data meaning, and accept an explicit scale version when
recomputing a report. Legacy label-only rows remain unscored instead of being
converted through invented anchor values. A future calibration adds a new
registry entry; it must not mutate an existing version.

The API uses synchronous SQLAlchemy. Synchronous routes are intentionally
declared with normal `def` so FastAPI runs blocking database and storage work in
its thread pool. `async def` is reserved for actual async I/O such as SSE or
streaming. CPU/model-heavy work does not run in either API execution path.

## Dependency direction

The codebase is layered by responsibility rather than by a mechanically
enforced import rule. New code should follow these directions:

1. API routes depend on schemas, services, conversation entry points, and
   shared core dependencies. Routes should not contain reusable business logic.
2. Services dispatch durable work through `task_queue/`; Celery task functions
   validate task inputs and delegate back to services. Business behavior must
   remain callable without importing task implementations.
3. Conversation and Agent runtime may use services, RAG, prompts, models, and
   core utilities; they must not import HTTP route modules.
4. Services own transactions and use models, database connections, prompts,
   RAG adapters, and core utilities as needed.
5. RAG code owns retrieval/index implementation and may use core configuration,
   database facts, and persistence models. Routes must not bypass it with a
   second vector-store implementation.
6. Models depend only on the database base and other persistence models.
   Pydantic schemas do not own database behavior.
7. Core is for genuinely shared technical policy. Existing model factories use
   a few lazy service imports to resolve per-user settings; this is a narrow
   integration seam, not permission to move domain workflows into `core`.
8. The frontend reaches backend behavior only through `frontend/src/api/`.
   Pages should not construct service URLs or duplicate edition policy.

`backend/tests/test_architecture/` enforces these high-level directions and an
acyclic internal import graph. It also prevents models from reintroducing naive
datetime columns. Cross-domain calls should use an existing shared contract or
a clearly owned service, not a second implementation.

## Placement rules

- Add a route contract to `schemas/`, transport handling to `api/`, and the
  reusable operation to the matching `services/<domain>/` package.
- Add a durable background entry point to `worker/tasks/`; keep its real work in
  a service.
- Add product prompt text only to `prompts/`; call sites provide structured
  variables rather than duplicate instructions.
- Add a parser, embedding, reranker, or retrieval implementation to `rag/` and
  register it through the existing provider/registry boundary.
- Add generic buttons, fields, dialogs, and rendering primitives to
  `frontend/src/components/ui/`; keep feature-specific components with their
  page.
- Put generated artifacts in `data/`, never beside source modules.
- Keep `scripts/` for commands a developer or operator intentionally runs. A
  one-time private cleanup is not a permanent product script.

## Two supported Community launch topologies

- Host development: Compose runs infrastructure; `scripts/start.*` runs API,
  workers, scheduler, and Vite on the host.
- Full containers: `docker compose --profile full up -d --wait` runs migration,
  application processes, frontend, and infrastructure.

Both modes use the same schema and configuration contract. New third startup
paths should not be added without removing or deliberately superseding one of
these two.

Model placement is a separate choice. Either launch topology can use remote
providers, local models, or a per-capability hybrid; do not describe these as
additional launch modes. `scripts/init_models.py` owns interactive local model
selection and persists the resulting provider/model settings in `.env`.
