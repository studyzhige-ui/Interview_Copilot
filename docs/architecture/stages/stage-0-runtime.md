# Stage 0 Spec: shared Conversation and Agent runtime

## 1. Scope

Stage 0 is the dependency root for every product flow. It freezes one durable
Conversation ingress, one Turn state machine, one Tool pipeline and one Context
assembly path shared by Chat and Agent mode. It does not create a second
Conversation kernel, a capability layer, a recovery narrative or a generic
workflow engine.

The authoritative runtime records are `PendingSubmission`, `ConversationTurn`,
`AgentToolCall`, optional `AgentTask` and optional `AgentInteraction`.
`ConversationMessage` remains exact History. Redis, SSE buffers, prompt cache,
compaction summaries and frontend reducers are projections and may be rebuilt.

## 2. Durable ingress and admission

Every user send carries a stable `submission_id`, positive `version`, input,
selected attachment-draft identities, optional closed typed product-object
identities, strategy mode, execution mode and initiating `source_client_id`.
Network retry reuses the same identity and body. Reusing an identity/version
with a different fingerprint is a conflict. A typed object reference contains
only its closed kind and stable identity; client-copied business fields are not
accepted.

The server performs admission while locking the Conversation:

1. verify owner and submission fingerprint;
2. preflight every attachment draft and reread every explicit product identity
   from its real owner under the submitting user, without writing History;
3. if there is no active `pending|running|waiting` Turn, atomically claim the
   submission, freeze its input, AttachmentRefs and typed identities, create
   one Turn and set `Conversation.active_turn_id`;
4. otherwise assign the next monotonic FIFO position and retain it outside
   History;
5. return `admitted`, `queued` or a durable `failed` projection. A queued or
   failed item is editable/retriable/withdrawable with version CAS.

Claim-before-History is forbidden. A queued item becomes a user Interaction
Record only after the same admission transaction claims it. Terminalizing a
Turn and claiming at most one next item use the same Conversation lock. The
only FIFO exception is an explicit user command that fences/cancels the active
Turn and names the retained submission to admit next.

## 3. Turn lifecycle and execution fencing

The only terminal outcomes are `completed`, `blocked`, `failed` and
`cancelled`; `waiting` is non-terminal and releases the worker and stream.
`dispatch_generation` increments before retry/resume. Tool completion and late
receipts retain their original generation and call identity; stale workers may
record a late result for audit/reconciliation but may not revive or overwrite
a newer Turn.

The shared kernel, not a model sentence or SSE handler, decides the outcome.
Before accepting `completed`, it checks unresolved Tool Calls and the optional
AgentTask completion structure. Repeated identical no-progress incidents have
a finite local repair budget and then end honestly as `blocked`, preserving
partial results. Cancellation advances the fence before worker termination.

## 4. Optional AgentTask and Interaction

Simple Turns have no AgentTask. A genuinely multi-phase Turn may have exactly
one flat ordered plan with completion conditions and at most one
`in_progress` phase. Revisions use version CAS and append minimal revision
metadata. There is no nested DAG, verifier task, model-facing checkpoint Tool
or cross-Turn task owner. `task_create` and `task_update` are typed runtime
control Tools; terminalization freezes the plan.

A Turn may have at most one pending `AgentInteraction`. The four transport
kinds are clarification, connection, approval and client readiness. Their
concrete payload remains owned by the creating Tool/client handler. Resolution
uses owner check plus `status=pending AND version=expected_version`, resumes the
same Turn and the same Tool Call, and never grants a different call.

Client actions reuse `AgentInteraction` durability. Delivery is restricted to
the initiating client unless the user performs an explicit versioned takeover.
Ack, refusal and failure are idempotent typed resolutions. Device readiness,
UI prefill, runtime creation and entered-UI acknowledgement are distinct facts
and may not substitute for one another.

## 5. One Tool pipeline

The only execution path is:

`ToolDefinition -> stable Registry/Discovery -> concrete preflight -> Policy -> Executor -> typed ToolResult`.

Concrete name/description/parameters appear once in the Provider's tool-schema
parameter, in deterministic name order. System text may contain concise usage
guidance or a discovery index but never a second schema copy. Denied Tools do
not leak guidance. Deferred schemas are used only through a Provider-native
mechanism; unsupported Providers receive the updated concrete list normally.

Preflight rechecks current handler, connection, owner/scope, typed parameters,
idempotency, concurrency and dispatch fence. Unknown effects and unvalidated
MCP calls fail closed. Standard mode allows reads and runtime control but asks
for material writes/client actions unless the exact task/call has a valid
authorization. Auto may skip ordinary task-scoped approvals only; it cannot
bypass hard denies, sensitive decisions, connection scope, user-retained
decisions or Provider constraints. Memory, Skill and prompt text never expand
Policy.

Handlers receive typed original inputs. The canonical `AgentToolCall` stores
the complete typed server-redacted result; History, model input, SSE, logs,
inline UI and deep audit receive independently bounded/redacted projections of
that same row. Oversized model input is paged back by exact `tool_call_id`; it
does not create a worker-local file or second result owner. Tool results remain
untrusted model data. Timeout/cancellation of a possible external side effect
is not success; the durable call retains enough identity for
receipt/read-back/reconciliation without inventing a public Evidence entity.

## 6. Context, compaction and Provider payload

The provider-neutral request has three separate partitions:

1. deterministic concrete ToolDefinitions;
2. stable system rules followed by user/session-specific instruction sections;
3. chronological messages.

User/product state, attachment/RAG slices, History recall and future Memory
Recall are labelled data messages, not a cross-user system prefix. Current
accepted user input remains the final task anchor. Global CopilotPreference,
InterviewRecord guidance and Conversation guidance are read from their real
owners, resolved broad-to-specific, and injected once. Runtime checkpoint JSON
never enters a model request.

An explicitly submitted product identity is reread again immediately before
execution. Its bounded server projection is a low-authority data section next
to the current user message and never replaces that message. Deleted,
cross-tenant or unreadable identities fail closed. Exact History preserves the
past kind/identity and server-resolved display label, but future turns must
reread the current owner rather than treating that label as current business
state. Page route, selection, form values and DOM never become implicit input;
the frontend supplies the identity only through a visible “询问 Copilot”
handoff and retains it across refresh until the server durably admits, queues or
rejects the submission.

Anthropic adapters may apply the physical cache order `tools -> system ->
messages`; other adapters use their native facility. Cache is optional and
cannot change semantics. Read/create and available miss metrics are normalized
when the Provider reports them.

Anthropic cache storage is workspace-scoped rather than product-user-scoped.
In a shared deployment the adapter therefore marks only deterministic
ToolDefinitions and the non-private stable system prefix. User History,
guidance, retrieved data and current input remain in the messages partition
without cache markers. This preserves the physical request order without
allowing a private prefix to be reused across product users.

One canonical writer maintains `Conversation.summary + compaction_cursor`.
It merges the prior summary, advances by exact message sequence and commits
summary/cursor atomically. Tool use/result blocks included in the summarizer
remain paired by call id and original model-call ordering. Complete History is
never overwritten. Loop-local pressure relief may use a temporary projection
but cannot overwrite the canonical summary. Token pressure uses recent real
Provider usage plus delta when available; otherwise it conservatively estimates
the final tools/system/messages request. Runtime recovery is independent and
is not a compaction commit condition.

## 7. Read projections

The active UI has one ordered activity column: optional AgentTask, then active
Interaction, while messages retain inline Tool cards. Live SSE, replayed
History and deep Tool audit use the same `call_id`. Parallel Tool results are
paired by identity rather than adjacency. The deep read model is owner scoped,
redacted again at presentation, and reads `AgentToolCall`; it is not a second
log. Refresh and Redis expiry rebuild from Postgres.

## 8. Migration and deletion

Stage 0 removes the legacy SessionTask/DAG/checkpoint Tool path,
ConversationCapabilityState, permissive unknown-tool behavior, arbitrary
`save_memory`/`recall_memory` Tools and runtime injection of the mixed Memory
store. Legacy Memory rows may remain only as isolated Stage 2 migration input.
No compatibility facade may keep an old writer or Recall path active.

Deleting a normal Conversation is a two-step owner command: the server first
returns a versioned impact preview and confirmation token, then a strong
confirmation fences new admission/model/Tool dispatch and safely terminalizes
any active Turn before cleanup. It withdraws PendingSubmissions, releases draft
attachments and deletes Conversation-local History. Running external/client or
unknown-effect calls become `unknown` rather than fabricated cancellation; only
bounded redacted receipt-correlation tombstones survive for reconciliation and
are purged after their owner-specific deadline. A PersistentTask-owned
Conversation is deleted only through the task lifecycle, which calls this same
Conversation command after fencing its scheduler owner. Already promoted
domain state, Debrief sources and Artifact versions follow their own owner and
do not cascade.

## 9. Release gates

- submission retry/fingerprint, FIFO, edit/retry/withdraw and explicit
  interrupt pass under multi-tab contention;
- claim failure creates no History or frozen AttachmentRef;
- every outcome has one kernel decision and durable SSE/replay projection;
- waiting releases resources and resumes the same Turn/call after restart;
- late/stale generations never revive a terminal/newer Turn;
- Tool schemas occur once and in stable order; denied guidance is absent;
- Standard/Auto and parameter-level approval tests cover allow/ask/deny;
- secrets are absent from every persisted/presented Tool surface;
- consecutive compactions preserve earliest summary meaning, current anchor
  and Tool pairing with one writer;
- Provider payload tests prove no Recovery prompt and no dynamic data in the
  stable cross-user prefix;
- live, History and audit Tool projections share call identity.
- deletion preview/strong confirmation, active-Turn fence, queue/draft cleanup,
  late-receipt reconciliation and bounded tombstone purge rebuild from durable
  state without retaining Conversation content.
