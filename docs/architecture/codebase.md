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
| SQL/Redis/S3/Milvus infrastructure, hosting, local electricity | Deployment costs, outside per-call supplier metering |
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

`backend/tests/test_architecture/` enforces these high-level directions and an
acyclic internal import graph, including package `__init__` and deferred imports.
The scanner asserts real application files are present; an empty/wrong root cannot
pass. API, Agent Tools and scheduled task adapters cannot add/delete domain ORM
rows directly. The legacy `services` tree and runtime imports of operator-only
`maintenance` migrations are prohibited. It also prevents models from reintroducing naive
datetime columns. Cross-domain calls should use an existing shared contract or
a clearly owned service, not a second implementation.

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

The same repository has three distinct kinds of tests, not interchangeable claims:

1. Unit/service/component tests exercise contracts with controlled dependencies.
2. PostgreSQL/Redis/Celery SIGKILL and Chromium campaigns exercise real process,
   transport, transaction and UI behavior. Only heavyweight/live-model boundaries
   use labeled fixtures, and every test owns an isolated database/queue.
3. `evaluation/` live semantic/learning evaluations require explicit model/data
   configuration. Their results are not inferred from (1) or (2).

`career_agent_os_eval` binds all 15 VS-01 scenarios to fresh backend and frontend
JUnit. A static manifest or a skipped required case is not acceptance. CI runs
that full deterministic gate after the real browser campaign. The gate covers
invitation intake/confirmation/handoff only: it does not certify all future
career journeys, memory quality, real OAuth accounts or financial accounting.


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
