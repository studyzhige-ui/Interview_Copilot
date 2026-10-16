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
| `backend/app/career/application/` | Single owners for profile/evidence, opportunities/actions, invitations, artifacts/resumes, offers and reminders |
| `backend/app/conversation/application/` | Durable Turn/dispatch/checkpoint/interaction owners; `session_commands.py` owns session changes |
| `backend/app/interviews/application/` | Mock interview and uploaded-interview analysis, QA editing and recovery |
| `backend/app/rag/application/` | Owned knowledge commands, library queries and ingestion workflow |
| `backend/app/usage/` | Unified account resource/fee ledger, physical-call adapters, read-only projections and audited operator reconciliation |
| `backend/app/identity/`, `files/`, `media/` | Account/credential, upload/asset, and speech application owners |
| `backend/app/automation/`, `integrations/`, `capabilities/` | Persistent task lifecycle, authorized provider resources, plugin/catalog policy |
| `backend/app/memory/`, `observability/`, `providers/catalog/`, `platform/outbox/` | Memory lifecycle, diagnostic projections, model catalog, durable outbox |
| `backend/app/maintenance/` | Explicit operator-only legacy migration; runtime must not import this package |
| `backend/app/conversation/` | Chat/Agent conversation engine, strategy selection, planning, and event contracts |
| `backend/app/agent_runtime/` | Current ReAct execution, turn-local Tool catalog, MCP clients, Tool Calls, cancellation, and result storage; target Harness/Tool/Policy semantics are defined by `career-agent-os-blueprint.md` and future formal Contracts |
| `backend/app/rag/` | Parsing, cleaning, chunking, BGE embedding/reranking, canonical PostgreSQL/pgvector projections, retrieval, and hydration |
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

## Frontend page ownership

Pages show an actionable summary or own a particular object, rather than
repeating full lists and editors across the workspace.

| Page | User-facing responsibility |
|---|---|
| Today | Planned actions and confirmed Offer deadlines, upcoming interviews, all pending confirmations and unfinished work |
| Jobs and progress | Searchable opportunities, per-job facts, JD versions, interview arrangements and submitted materials |
| Calendar | Interview and action calendar, ICS export and the single action editor at `/career-calendar?view=actions` |
| Statistics and Offer | Funnel analysis and Offer comparison; notification preferences belong to `/settings/notifications` |
| Mock interview / review / ability growth | Practice, original recordings and QA review, then aggregate ability analysis with collapsible evidence and correction controls |
| Personal profile | Continuous online resume with anchored directory, inline section editing, preview and print export; attachments and draft review are supporting tools, not the main document |
| Application materials | Structured drafts, immutable published versions, two resume templates, Chinese PDF export, file upload/default/replacement, and exact submitted-version history |
| Knowledge library | Reference documents and retrieval ingestion; does not duplicate resume management |
| Activity history | Filterable audit history with expandable details, separate from Today |
| Copilot conversations | Searchable conversation titles and one active dialogue; mobile/drawer record switching preserves the mounted conversation runtime, without a duplicate career dashboard |
| Conversation search | Content excerpts first, with full-message readback and expandable source identifiers |
| Persistent tasks | Schedule, task state and dedicated result conversation first; authorization scope and deletion are secondary controls |
| Settings | Separate preferences/memory, model configuration/usage, plugins/Skills/MCP, and account/storage views; no promotional placeholders for unimplemented adapters |

Online-resume sections use the existing confirmed Profile JSON contract, including personal information, summary, certificates, organization and volunteer experience. Resume dates preserve year, month or day precision from the source; import and direct edits share the same validators. Account avatars and uploaded resume artifacts retain their existing owners.

The former `/interviews` invitation-only preparation page, its preparation-open
client action/tool and dedicated list/handoff endpoints have been removed.
Invitation confirmation remains in the current job/chat workflow, and scheduled
interviews remain owned interview records. Actual mock preparation using resume
and JD evidence remains part of the mock interview workflow. Setup exposes required
materials and answer mode before optional tuning. Review defaults to the report;
its conversation is opened deliberately and stays mounted when switching views.
Model catalog cache/seed reads reuse the vendor chat filter, so speech, video and
embedding endpoints cannot re-enter the answer-model picker through cached rows.
Today reads these
records without creating duplicate action records.

### Career workspace owners and recovery

`career/application/workspace.py` composes the existing JobOpportunity,
ProcessEvent, NextAction, InterviewRecord and Artifact owners. Its shared
`job_query` excludes active merge duplicates and user-hidden jobs for both the
board and home counts. Home resolves interviews retained on a merged source to
their canonical opportunity. OpportunityDetails owns notes, contacts and user
visibility; hiding a job does not assert a hiring outcome.

`documents.py` owns editable drafts and publishes through the existing immutable
ArtifactVersion owner. Application submission records exact published versions.
Profile facts and resume documents remain separate because imported statements
need confirmation before entering the profile. `/resumes` and raw process APIs
retain required identity/history compatibility; the replaced frontend write
wrappers have been removed.

Manual invitation forms retain only an owner-scoped opaque submission key in
local storage. Durable server receipts distinguish pending, committed,
rejected and cancelled commands. A missing receipt requires cancellation before
new input, so a delayed original request cannot create a second arrangement.
Agent writes, direct forms, Gmail review and interview association share career
query invalidation. Visible schedule/job projections also refresh every 30 seconds
to observe asynchronous changes and advancing deadlines.

`rag/application/document_commands.enqueue_ingestion` commits a task identity
before publishing it to Celery. Creation, attachment retry and stale-work recovery
use this same boundary; source snapshots include that identity. Publish failure
records an explicit failure without replacing newer work or a finished result.
The stale pipeline sweeper recovers a process exit between commit and publish;
parsing dispatch does not claim an atomic transaction with the message broker.

## Shared wire schemas and compatibility gate

`backend/app/schemas/` owns versioned Operation, Verification, Interaction,
Client Action, Context Package and Activity contracts. Do not independently
change a frontend mirror. The schema export imports only these DTOs, not the
application, database, model clients or user configuration. Validation and
serialization schemas are separate: clients may omit defaults while the current
response serializers include them. Validation-only ORM aliases such as
`request_json` must not leak into the response contract.

```sh
python scripts/export_shared_contracts.py
npm ci --prefix scripts/contract_codegen --ignore-scripts
npm run --prefix scripts/contract_codegen generate
# CI checks both snapshots and TypeScript consumer compatibility:
python scripts/export_shared_contracts.py --check
npm run --prefix scripts/contract_codegen check
npm run --prefix frontend typecheck
```

The committed OpenAPI 3.1 snapshot has local component references only. The
pinned official `openapi-typescript` generator is a development tool, not a
runtime HTTP client replacement. Its 7.13.0 TypeScript-5 peer is isolated in its
own lockfile (5.9.3); the frontend keeps its existing TypeScript 6.0.3. Generated
source is checked, not silently regenerated during CI. Compile-time directional
checks ensure requests fit server inputs and responses fit UI projections;
negative controls prevent an empty check from appearing successful. The UI can
omit unused response fields, but cannot invent non-nullability or a supported
action enum. Nullable candidate fields remain unknown; only a new manual form
suggests the browser timezone.

These checks do not implement semantic validators in TypeScript: permissions,
aware dates, field dependencies, exact decisions and unknown schema versions
still require runtime validation and behavior tests. Official generation APIs:
[Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/) and
[openapi-typescript CLI](https://openapi-ts.dev/cli), checked 2026-09-19.

## Runtime flow

### Maintained conversation owners

`conversation/engine.py` owns the conversation lifecycle; `agent_strategy.py`
owns the model/tool loop. `tool_batch.py` preflights and schedules a whole
model-issued batch, and `agent_runtime/tool_call_executor.py` owns each durable
tool call. `agent_turn_state.py` reads task/replay state for resumption.

Within `conversation/application`, `turn_admission.py` owns locked FIFO claims,
`turn_store.py` owns durable transitions, leases and queue handoffs, and
`turn_executor.py` supervises the asynchronous engine, cancellation and event
delivery. Consumers import the responsible owner directly. Engine outcomes are
explicit; an error event alone never changes the terminal status.

### Maintained RAG path

Knowledge commands and the ingestion worker share `rag/application` owners.
Parsing, cleaning and chunking produce canonical document facts; index writes
use `rag/index/knowledge.py` and `rag/hybrid_index.py` to update
`retrieval_entries`. Source identity and generation checks prevent stale writes.
Deletion and publication use the same canonical document/projection lifecycle.

Chat, Agent knowledge tools, diagnostic HTTP and production-path evaluation
call `rag/application/service.py`: BGE dense + scoped BM25, RRF, BGE reranking,
evidence selection, fact hydration and citations. Private attachments retain
their explicit conversation/document scope. Exact and HNSW share the same
projection, authorization and retrieval pipeline; HNSW provisioning belongs
to `scripts/prepare_rag_hnsw.py`, never an HTTP request.

Offline MTRAG ranking baselines preserve official passage IDs and benchmark
semantics; they are evaluation tools, not selectable application backends.
They cannot stand in for `evaluation.rag_release` production-path acceptance.
Historical reports are evidence for their recorded source versions, not current
deployment instructions. See the [convergence audit](../implementation/mainline-convergence-20261011.md)
for checkpoints, preserved capabilities and verification scope.

```text
React page
  -> frontend API client
  -> FastAPI route / SSE endpoint
  -> domain service or conversation entry point
  -> PostgreSQL (including pgvector) / Redis / object storage / model provider

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

The full Compose profile uses four worker services for these five queues:
`turns`, `transcription`, and `pipeline` are isolated; `worker-jobs` consumes
`background` and `default`. The host development launcher keeps `turns` separate but combines
`default`, `background`, `pipeline`, and `transcription` in one local solo
worker to reduce the number of developer processes; queue routing remains the
same.

| Workload | Queue | Concurrency rule | Durable source of truth |
|---|---|---|---|
| Chat and Agent turns | `turns` | Dedicated worker; cancellation and usage telemetry | conversation, turn, checkpoint, and tool-call rows |
| Parsing, embedding, and vector synchronization | `pipeline` | Serialized where local model/GPU pressure requires it | PostgreSQL document/resume facts plus outbox jobs |
| Speech recognition and diarization | `transcription` | One resident WhisperX model, serialized across mock clips, live windows and uploaded recordings | interview record, recording draft, transcript, and QA rows |
| Model-backed interview review | `background` | Bounded independently from ingestion | interview state and typed outbox jobs |
| Cleanup, catalog, scheduling, and sweepers | `default` | Short control work only | database status and idempotent maintenance rules |

Mock recording admission stores the original FileAsset and a `mock_audio_transcriptions`
row before dispatch. The API never loads WhisperX. Worker startup preloads the model;
successive answers reuse that instance until the process exits. A 10-second heartbeat
and 60-second lease let reads terminate an interrupted recording without redispatching
it. An explicit retry reuses the original asset under a new request identity. Media
document ingestion also routes to the transcription worker; document-only ingestion
continues on the pipeline queue. Interactive requests take precedence over queued
long recordings, but cannot preempt an already-running task.

Redis transports work; it is not the business source of truth. Live PCM windows alone
use expiring Celery results (60 seconds, deleted after retrieval); they do not create
interview records or authorize answering. Worker tasks may
be delivered more than once, so handlers must claim or status-gate work before
side effects. Cross-system changes use the typed outbox and are claimed by
`job_type`; a slow LLM review job must never block a retrieval projection update or object
cleanup. PostgreSQL owns lifecycle state, object storage owns file bytes, and
`retrieval_entries` is a rebuildable projection of canonical document chunks.

## Shared invitation ingress and unified consumption accounting

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
- `usage/service.py` is the only account-consumption owner. The old
  `services/chat/model_budget_service.py` implementation is retired. Primary
  dispatch still reserves in the same transaction as `AgentModelDispatch`;
  every other owned physical provider boundary also reserves before execution
  and settles in a short, independently owned transaction.

### One account envelope, not one quota per feature

The historical `MODEL_DAILY_CALL_LIMIT` and `MODEL_DAILY_TOKEN_LIMIT` environment
names remain supported, but now cover all registered production categories:
primary Chat/Agent, internal router/worker, model completion/ping, compaction,
vision, embedding, reranking, transcription, diarization, speech synthesis,
cloud document parsing, external connector resource requests and opaque MCP
invocations. Logical tokens, bytes, audio milliseconds, characters, pages,
documents and request/invocation counts share a UTC-day window. A local model is
still resource work, not an implicit free bypass. Empty/cache-only work that
never executes does not create a provider call.

Authentication and canonical Worker records establish the stable numeric owner.
`ContextVar` carries only identity plus synchronized per-request ordinals, never
a Session. Thread workers copy the context; independent task entry points restore
it. Missing or conflicting owners stop consumption. Standalone operator ingestion
uses the same owned boundary. The independent optional benchmark generator/judge
has separate credentials and evaluation cost records; it is not a hidden product
endpoint. The memory benchmark uses a retained local synthetic-account ledger.

`usage_accounts` is an independent lock root. `0052` seeds existing users and
preserves their windows, old dispatch identities and used/reserved tokens;
creating a user creates its accounting root. Consumption windows and reservations
reference that root, not a locked career User row. Lock order is account, receipt,
window. No provider request runs inside the accounting transaction. Deleting a
conversation cannot reset usage. An unresolved call retains its allowance across
restart/day boundaries; an account-wide unresolved-count cap prevents unlimited
accumulation. Replaying an existing dispatch is not a second admission.

### Settlement and upgrade closeout

The application must not infer another network-send permission from a failed
accounting COMMIT. `ConsumptionSettlementUnconfirmedError` is non-retryable and
explicitly distinguishes unconfirmed **local settlement** from an unknown
**provider result**. The original receipt remains the recovery anchor, whether
COMMIT rolled back or committed but its acknowledgement was lost. No automatic
second settlement or provider resend is performed. Usage validation cannot
rewrite admission attempt counts or provide inconsistent logical/disjoint token
buckets. Operator quiescence is a real boolean attestation, not a truthy string.

The same rule is enforced outside the ledger, at each transport and fallback
boundary. HTTP stream success settles after the stream's cleanup scope; MCP
success settles outside its transport-error handler, without discarding the
healthy session. Cloud parsing propagates the settlement error rather than
calling settlement a second time. Web/job search and parser-selection fallbacks
propagate non-retryable consumption errors. The optional conversation planner,
parallel candidate fusion and retrieval/reranking orchestrator preserve that
same stop signal rather than recasting it as degraded evidence. Already-started
parallel channels still complete their accounting; success in another channel
cannot hide an unconfirmed paid result. An ordinary read timeout or local parser
failure still follows its documented fallback. Tests inject failure both
before COMMIT and after a successful COMMIT with a lost acknowledgement, checking
one provider completion, one settlement attempt, unchanged receipt identity,
resource cleanup and the actual persisted balance. A green ledger-unit test
alone is not evidence that outer adapters preserve its contract.

`0052` uses `jsonb_build_object`, not colon-containing JSON SQL literals. Its
PostgreSQL campaign checks every old status (`reserved`, `unknown`, `settled`,
`estimated`, `rejected`) across owners and UTC days, a user with no past calls,
original timestamps/evidence/identities/balances, later reconciliation against the
same old receipt, and safe refusal of destructive rollback. Logical token totals
are preserved without inventing an input/output/cache split for historical rows.

An additional shared-command call-site guard inspects actual API and Agent calls
for the current profile, opportunity, action, artifact, JD, interview and RAG
owners. Import and timestamp guards both assert a non-empty application scan.
Static wiring is not a substitute for the behavioral ownership, CAS and recovery
suites; it prevents a second independent implementation from replacing only one
entry point unnoticed. Historical test directory names and append-only migration
history are not executable compatibility service owners.

Official semantics checked on 2026-09-19 (dependencies remain pinned and tested;
reading a newer patch's documentation does not silently upgrade production):

- [SQLAlchemy 2.0 text/bind parameters](https://docs.sqlalchemy.org/en/20/core/sqlelement.html#sqlalchemy.sql.expression.text)
  and [Alembic execute](https://alembic.sqlalchemy.org/en/latest/ops.html#alembic.operations.Operations.execute):
  SQL string execution uses TextClause bind parsing, including literal colons.
- [PostgreSQL 15 JSON construction](https://www.postgresql.org/docs/15/functions-json.html)
  and [row locking](https://www.postgresql.org/docs/15/explicit-locking.html):
  JSON constructors and transactional row locks, tested against the actual CI database.
- [Python context-manager exception propagation](https://docs.python.org/3.13/library/contextlib.html)
  and [HTTPX async streaming](https://www.python-httpx.org/async/):
  exceptions from a caller's block return at `yield`; response cleanup must
  complete, but a later accounting failure must not re-enter transport recovery.
- [Python 3.13 cancellation shielding](https://docs.python.org/3.13/library/asyncio-task.html#shielding-from-cancellation):
  protecting the short accounting task is not cancellation of an already-sent
  remote operation or an already-running thread.

### Rated costs and supplier evidence are different

`USAGE_RATE_CARD_JSON` uses exact `meter:provider:model` identities and decimal
**strings of currency per unit**. Each admitted call freezes its currency, rates
and version. Amounts are integer millionths of that currency; public JSON uses
strings for monetary amounts to avoid JavaScript integer rounding. There are no
bundled guessed prices, implicit exchange rates or conversions from vendor
credits. A missing rate remains *unpriced*, not zero. Explicit zero is an
operator policy (for example a local resource), not a supplier pricing claim.

`USAGE_DAILY_COST_LIMIT_MICROS` is optional. When configured, an unpriced request
or unreconciled unpriced historical usage in the same day blocks admission.
`USAGE_DAILY_UNITS_JSON` independently caps resources. An admitted stricter policy
is persisted; later environment changes cannot silently relax that day's cap.
Rates on past receipts are never revalued in place. Estimates are conservative
reservations, not a guarantee that an opaque remote server's eventual invoice
matches an application tariff; higher observed usage is recorded and prevents
further over-budget admission rather than hiding the overrun.

Provider success with missing usage settles as **estimated** using the admitted
allowance. Unknown transport outcomes retain the allowance. Explicit refusals
release consumable units but keep attempt counts. Parsing a completed response
incorrectly cannot erase a paid request. OpenAI and Anthropic cache buckets are
normalized without double-counting; native Anthropic completion uses Messages,
not an OpenAI-compatible URL assumption. Structured output uses the configured
native format; unsupported capabilities fail rather than silently becoming a
different provider/model.

Models shows `/usage` and an account-scoped keyset-paginated receipt history.
`GET /usage/receipts/{id}/corrections` exposes sanitized adjustment history;
there is no browser/Agent refund, price-edit or quota-reset action. No prompts,
raw audio, document text, filenames, credentials or evidence-file contents enter
the consumption ledger. Provider request IDs, HMAC input identity, frozen prices,
measured/estimated units and statuses remain auditable.

Operator correction is `python scripts/reconcile_usage.py request.json
--evidence supplier-evidence.json`, dry-run by default. Applying also requires
`--apply --acknowledge-external-evidence`. The JSON names `user_id`, `receipt_id`,
`expected_revision`, `request_id`, `operator`, `outcome`, all `observed_units`,
`observed_tokens` and `currency`; it may supply `invoice_cost_micros` and/or
explicit `rates`. Active/unknown receipts additionally require `quiesced=true`.
Verify the remote result and quiesce its Worker first: a local timeout is not
proof. A supplier aggregate cannot be assigned to one call without verifiable
allocation. Corrections use CAS, stable request identity and an append-only
before/after journal; original price snapshots remain intact. Keep evidence
outside Git. This CLI does not contact suppliers or charge/refund money.

### Boundary inventory and intentional exclusions

| Boundary | Accounting / authority |
|---|---|
| Native primary streaming | Existing dispatch receipt, no nested second charge |
| Internal/analysis/mock/resume completion | `MeteredLLM.complete/acomplete`; other unmetered methods rejected |
| Compaction/vision native stream | Receipt spans connection, iteration and close |
| Remote embedding | Actual SDK embeddings request, before wrappers discard usage |
| Local embedding / local or remote rerank | Bounded work owns permit until actual completion; measured units or explicit estimate |
| ASR / diarization | Bounded local size/duration check; streamed multipart; known refusals/unknown tracked |
| Speech | One logical synthesis, character allowance and bounded output; third-party edge-tts is not Azure service/SLA |
| LlamaParse | Official v2 multipart upload, one paid POST, saved job ID, bounded status reads/output/pages; no silent resubmit |
| Gmail/plugin/web/search resources | Authorized external resource request tariff; control-plane reads are not resource results |
| Opaque MCP tool | Invocation tariff, not a claim to observe the remote server's private model/tool calls |
| OAuth bootstrap/refresh/revoke, provider catalog, parser status polls | Explicit control plane; not a second billable resource request |
| SQL/pgvector/Redis/object-storage infrastructure, hosting, local electricity | Deployment costs, outside per-call supplier metering |
| Optional independent benchmark generator/judge | Separate benchmark keys/checkpoint accounting; production provider calls still require an owned scope |

The cloud parser no longer uses the retired LlamaParse SDK. `fast` returns the
v2 text expansion; other tiers use Markdown. A known PDF page count is checked;
failed/missing pages or an ambiguous cap produce incomplete/failed parsing rather
than claiming whole-file coverage. Version `latest` is a visible configuration
choice, not an immutable model identity: pin a dated available version for
repeatable evaluation. OCR languages use provider defaults unless explicitly
configured in a future validated contract; no invented language code is sent.

`0052` refuses downgrade when it would discard new-category or priced receipts
or adjustments. Back up/restore-test before upgrade. Old primary-only balances
are not reset or assigned fictitious historical prices. A completed rollout does
not prove every supplier has correct prices configured or every invoice reconciled.

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

The codebase is layered by ownership and checked against actual source imports.
New code must follow these directions:

1. API routes depend on schemas, application commands, conversation entry points, and
   shared core dependencies. Routes should not contain reusable business logic.
2. Application owners dispatch durable work through `task_queue/`; Celery task functions
   validate task inputs and delegate back to application owners. Business behavior must
   remain callable without importing task implementations.
3. Conversation and Agent runtime may use application owners, RAG, prompts, models, and
   core utilities; they must not import HTTP route modules.
4. Application owners own transactions and use models, database connections, prompts,
   RAG adapters, and core utilities as needed.
5. RAG code owns retrieval/index implementation and may use core configuration,
   database facts, and persistence models. Routes must not bypass it with a
   second vector-store implementation.
6. Models depend only on the database base and other persistence models.
   Pydantic schemas do not own database behavior.
7. Core is for genuinely shared technical policy. Existing model factories use
   a few lazy owner imports to resolve per-user settings; this is a narrow
   integration seam, not permission to move domain workflows into `core`.
8. The frontend reaches backend behavior only through `frontend/src/api/`.
   Pages should not construct service URLs or duplicate edition policy.

`backend/tests/test_current_architecture.py` checks source parsing and selected
ownership boundaries (broker imports, retired modules, and memory defaults).
It does not prove the full import graph is acyclic or that every cross-domain
access obeys these rules. Service/API tests cover individual behavior contracts;
changes still require review against the placement rules below.

## Placement rules

- Add a route contract to `schemas/`, transport handling to `api/`, and the
  reusable operation to its existing domain `application/` owner.
  The generic `services/` tree is retired; do not add compatibility implementations.
- Add a durable background entry point to `worker/tasks/`; keep its real work in
  its application owner; pass scheduler/transport ports from the composition root.
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


## Retrieval admission and model-connection authority

`core/bounded_work.py` is a small synchronous-work admission primitive, not a
new scheduler framework. `rag/retrieval/workers.py` owns four process-local
pools for canonical storage, vector search, embedding and reranking. A permit
belongs to the actual concurrent Future: cancellation of an async waiter does
not free a slot while its Python thread still runs. Pending jobs can be cancelled;
running jobs drain. The default single reranker worker avoids assuming that a
local model instance is thread-safe. Prefork children create their own pools;
API/Celery shutdown closes admission and pending work. No live Session is passed
into these pools: storage functions create and close their own sessions.

The limits multiply by the number of API/worker processes. They are not a
fleet-wide quota, a CPU sandbox or a way to kill hung native code. SDK/network/DB
deadlines and operator process supervision remain necessary. A closed pool
cannot be reopened until its previous work has drained.

Retrieval preserves `capacity_exhausted`, `retrieval_incomplete` and
`canonical_unavailable` instead of misreporting `no_candidates`. Partial results
keep `degraded=true`; the Agent tool receives that flag and the exact outcome.
Canonical ownership checks never fall back to index text when PostgreSQL is
unavailable. These operational limits do not alter the ranking threshold or
pretend to improve factual recall without an evaluation.

Model connection resolution distinguishes verified absence from lookup failure.
No stored override/key/selection may still use the existing documented deployment
fallback; a database/decryption error stops construction with
`ModelConnectionUnavailable` instead of changing the destination or credential.
The user-facing error is stable and does not contain the underlying storage error.
The plaintext LRU is only a decryption optimization: every lookup rechecks the
current encrypted row. Cross-worker rotation/deletion invalidates reuse on the
next lookup; lazy re-encryption uses a ciphertext compare-and-swap. Already-sent
provider requests cannot be retrospectively revoked by this mechanism.

## Evidence levels used by CI

The current tests distinguish deterministic contracts, explicit real-service
acceptance, and model-quality evaluation. `backend/tests` exercises current
ownership, lifecycle and protocol behavior. PostgreSQL, S3, browser and original
recording tests require their documented opt-ins; skipped cases are not evidence.

`evaluation/career_agent_os_eval.py` binds current test files to fresh JUnit
results. It does not certify the historical VS-01 fifteen-scenario campaign,
SIGKILL recovery, real OAuth accounts, production load or model quality.
See `docs/implementation/current-test-baseline.md` and the dated acceptance
records for the actual executed scope.

## Official references checked for the 2026-09-19 implementation

Pinned dependency versions in `pyproject.toml` remain the tested environment;
consult matching release families, not an unrelated latest-major example.
These links explain protocol/ownership choices, not product quality guarantees.

| Primary documentation | Implementation implication |
|---|---|
| [SQLAlchemy 2.0 Session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) | Session per thread/task; short owned units of work, not ContextVar Session sharing |
| [PostgreSQL 15 explicit locks](https://www.postgresql.org/docs/15/explicit-locking.html) | Independent accounting lock root, fixed lock order, bounded row-lock recovery |
| [Python 3.13 contextvars](https://docs.python.org/3.13/library/contextvars.html) | Copy trusted identities across threads; Context propagation is not shared-Session safety |
| [Python Decimal](https://docs.python.org/3.13/library/decimal.html) | Explicit decimal rates and rounding; no binary-float currency math |
| [HTTPX timeout semantics](https://www.python-httpx.org/advanced/timeouts/) | Network inactivity and end-to-end deadline are separate controls |
| [OpenAI embeddings API](https://platform.openai.com/docs/api-reference/embeddings/create) | Capture prompt-token usage at the SDK response before higher wrappers discard it |
| [OpenAI speech-to-text](https://platform.openai.com/docs/guides/speech-to-text) | Enforce this provider's upload limit, separate from other providers' limits |
| [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create) and [structured output](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) | Native Messages/usage and output configuration, not an assumed OpenAI wire format |
| [LlamaParse v2 REST](https://developers.llamaindex.ai/llamaparse/parse/guides/api-reference/) and [configuration](https://developers.llamaindex.ai/llamaparse/parse/guides/configuring-parse/) | Multipart configuration, job identity, tier-appropriate expansions, bounded/incomplete pages |
| [Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html) | Delivery/retry settings do not replace application idempotency or verified external outcomes |

### Migration scope

This migration covers the *currently shipped* Python application: all active
imports, entry points and package assets move to one owner per responsibility;
shared public operation semantics and Celery task names are preserved. Historical
DB tables/columns remain for migration or readback, not as a second runtime
writer. Operator migration tools are isolated rather than silently deleting user
history. It is not a claim to have implemented every future feature in the target
Blueprint (for example a future external calendar branch), nor a new semantic
quality or production load score. Existing quality/memory gates remain active.

## Local-first refactor: evaluator and model boundary (2026-09-19)

This is the first implementation batch of the approved functional refactor, not
completion of pgvector migration, real-time voice, or the complete product review.
The prior unified-accounting/owner migration remains intact. Current work status
is tracked in the existing implementation ledger.

`evaluation/mock_contracts.py` validates dataset and judge contracts;
`mock_run.py` owns the finite campaign journal and judge client; the mock evaluator
reuses the production interview generator through an injected resolved model.
It does not implement another interview business engine. Its synthetic turn
markers do not claim actual recovery. Existing DB/worker/browser tests retain that
responsibility.

`core/model_assets.py` is a read-only structural inspector. The runtime facade
`core/hf_runtime.py`, setup command and local doctor all use it; there are no
competing "directory nonempty" and "total size >10MB" definitions of readiness.
Recognized Transformer/CT2 assets require config, weights and tokenizer/vocabulary;
indexed weights require every declared shard. Safetensors checks bound the header
and validate extents without loading tensors. LFS pointers, zero-length assets,
unsafe shard paths and incomplete active revisions are rejected. HF refs resolve
the selected snapshot: commit hashes are NOT ordered by recency. Multiple cached
snapshots without a ref require an explicit choice.

Existing `org--model` flat exports remain supported without inventing their
revision provenance. Explicit `MODEL_REVISIONS_JSON` pins require an exact SHA and
an exact cached or managed revision; no fall back to an unversioned export.
Completed setup downloads produce size/hash manifests and activate a version
under `org--model/.revisions/<sha>` with one atomic pointer. An interrupted setup
cannot overwrite the old flat export or change the active pointer. These are
operator-owned local receipts, not vendor signatures. Runtime checks size and
structure; an explicit doctor `--verify-hashes` reads full files when a receipt is
available. Legacy exports without a receipt remain clearly unverified by hash.

Custom pyannote/Docling bundles are reported as `bundle_requires_loader`, not
certified complete: component resolution, licenses, GPU compatibility and actual
inference require their offline loader and hardware tests. No pickle/model code
is deserialized by the doctor. This change does not claim to validate the user's
actual local weights from GitHub.

`MODEL_ROOT_DIR` can reference read-only weights independently of writable
`CACHE_DIR` (HF metadata and Torch caches). Windows drive paths passed to Linux
are diagnosed, never interpreted as a local folder named `D:`. The optional
`AUXILIARY_MODEL_POLICY=local_only` rejects online embedding, reranking, ASR,
cloud parsing and current online edge-tts at their entry points, irrespective of
whether a credential exists. It also activates HF offline mode before optional
model imports. Ordinary parser fallback cannot swallow this policy error.
This is an application policy, not an OS-level network sandbox or permission to
load unaudited remote model code. DeepSeek remains an online language model.
The legacy `configured` policy remains the default for existing deployments.

`init_models.py --dry-run` no longer contacts HF or creates runtime directories.
Remote size lookup requires `--check-remote`. Actual setup explicitly enables
network access in its own process, freezes the resolved revision, checks expected
file sizes, records hashes, then activates. It must not run concurrently from
Windows and WSL against the same writable model tree. Do not turn offline mode
off in a live inference process to install models.

Official references:
- [HF cache refs, snapshots and blobs](https://huggingface.co/docs/huggingface_hub/guides/manage-cache).
- [Transformers offline loading](https://huggingface.co/docs/transformers/installation).
- [Safetensors format](https://github.com/huggingface/safetensors#format).
- [Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/).
