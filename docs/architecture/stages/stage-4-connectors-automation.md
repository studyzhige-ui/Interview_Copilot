# Stage 4 Spec: connectors, execution modes and PersistentTask

## 1. Connector boundary

The first connector is provider-specific Gmail read access. There is no generic
Connector/Secret/Source registry. A `GmailIntegrationAccount` stores user,
verified provider subject, masked account hint, granted scopes, status and an
opaque encrypted broker handle. Raw access/refresh tokens never enter the
application database, model Context, Tool arguments/results, History, SSE,
logs or frontend.

OAuth uses state/PKCE, exact redirect allowlisting and one-time state bound to
the authenticated user. The callback exchanges the code through the credential
broker, verifies identity/scopes, stores only the opaque handle and then
redirects with a non-secret outcome. Rebind, refresh failure, scope loss,
revoke and account mismatch update the same provider-specific row. API views
never return the handle.

The broker is a Gmail-specific port, not a generic product entity. Community
may use only the explicitly configured encrypted-file implementation: it uses
an independent recovery key, an absolute path outside the application DB,
inter-process locking, atomic replacement and owner-only file permissions. A
test-only in-memory fake is injected explicitly. Cloud must inject managed
external secret infrastructure; without it the connector and its Tools are
unavailable. Grant generations fence refresh/revoke writes, and a reconnect
rotates the handle so an old in-flight refresh cannot overwrite the new grant.

The Gmail adapter resolves a live credential from the broker for each call,
fences it to the user/provider subject, applies bounded query/result limits and
maps revoked/expired authorization to `connection_required`. Email bodies and
snippets are untrusted external data. The concrete read Tool is registered only
when the real adapter/broker configuration exists; an honest disabled state is
not counted as a connector.

The first continuous Observation source is exactly Gmail History
`message_added`; no Outlook/Calendar/generic event bus is implied. Each account
has a cursor updated by CAS. Provider message identity is deduplicated and each
Observation version keeps a bounded immutable source snapshot; a message that
disappears becomes a `content_available=false` tombstone so a bad item cannot
stall the cursor forever. Raw mail remains untrusted data and is never an
instruction.

## 2. Transport and secret safety

Remote HTTP/MCP endpoints must resolve and pin an allowed public IP for the
actual connection, disable environment proxies unless explicitly configured,
disable redirects by default and bound compressed/decompressed bytes. DNS
precheck followed by independent re-resolution is insufficient. Cloud denies
stdio MCP. Community stdio inherits only a minimal runtime environment plus
explicit validated configuration, never all parent environment variables.

Every connector result passes typed server redaction and the Stage 0 Policy
path. Provider content cannot inject Tool authorization. Unknown/community MCP
dispatch remains unavailable until it has the same concrete Policy and
transport guarantees.

## 3. Standard and Auto

Users have a default execution mode for new Conversations; each Conversation
has an editable mode and every admitted Turn freezes its own snapshot. Changing
the default does not mutate existing Conversations and changing a Conversation
does not mutate an active Turn.

Standard/Auto are Policy inputs, not Agent modes. Auto only removes routine
approval for reversible, task-scoped operations with current handler,
connection, scope and parameter authorization. It never authorizes sensitive
communications, identity/permission changes, irreversible or user-retained
decisions. Exact approval resumes only the same call. Connection and client
readiness never imply approval.

## 4. PersistentTask

`PersistentTask` owns a dedicated Conversation, definition/version, trigger
configuration, allowed concrete read Tool names, lifecycle and next schedule
cursor. Trigger ingress is durable and separate from user
`PendingSubmission`; an admitted automation run is the existing
`ConversationTurn`, not a second Run model.

Manual and scheduled triggers have stable idempotency identities. Schedule is
strict five-field cron plus IANA timezone with a minimum interval; next
occurrence is DST-aware. The only event definition accepted in this release is
the provider-specific Gmail `message_added` trigger with
`gmail:job_observations` read scope and the two concrete Observation Tools;
every other event definition fails validation rather than pretending to run. A
bounded maintenance scan repairs due cursors and unadmitted retained triggers.

Admission shares the Conversation lock. Retained user input has priority over
an automation trigger. A provider batch first retains all matching trigger
identities and then makes one admission attempt per task so occurrences merge
into one Turn. At claim time the runner reloads the current task
definition/version, exact allowed Tool set and any explicitly selected,
version-pinned Skill references. Unattended execution disables arbitrary
Skill/MCP discovery. Its catalog contains cloud-sustainable reads plus only the
Stage-approved `review_gmail_observation` internal write; that command remains
bound to the exact task/Turn Observation identities, action scope and Policy.
Unknown or other mutable Tools stay unavailable. Waiting retains the same Turn
and is handled in the dedicated Conversation. Terminal settlement re-evaluates
queued user input and retained triggers through the same admission seam.

Observation analysis never writes ambiguous content directly into career
state. It creates a task-local confirmation card that can be approved,
rejected, skipped or corrected by version CAS. Automatic application requires
the exact task action scope, a unique live opportunity, a non-archived and
non-late fact, a reversible append operation and the Stage threshold (currently
at least `0.95`). Creating a new JobOpportunity and a repeated
`application_submitted` fact always require confirmation because their
admission fact cannot be safely undone. Every automatic application remains
visible and has an append-only retraction/correction ProcessEvent.

Pause blocks future triggers but does not falsify a running result. Stop-this-
run, pause-future and delete-task are distinct. Delete uses task version CAS
plus an aggregate impact preview/strong confirmation, fences future triggers
and delegates the Dedicated Conversation to the shared safe-deletion command.
That command closes pending/running/waiting model and dispatch gates, removes
queued user ingress and drafts, and preserves domain state/Artifacts already
promoted. A genuinely running external action is never reported as cancelled
or rolled back: deletion retains only its bounded redacted receipt correlation
as `unknown` for later reconciliation, then owner-specific maintenance removes
the tombstone after terminal settlement or expiry.

## 5. Product surface

Users can list/create/read/edit/pause/resume/delete PersistentTasks, manually
trigger them, inspect trigger/Turn admission history and open the dedicated
Conversation to resolve an Interaction. The UI uses only concrete currently
registered eligible Tools, version-pinned eligible Skills and server versions;
it does not create an Automation Workspace or local trigger store. Gmail event
tasks display their source connection and task-local Observation cards rather
than polluting the ordinary Copilot workspace.

Integration settings expose Gmail connect/status/test/revoke with masked
identity and granted scopes. The connect button is enabled only when the real
OAuth/broker adapter exists. Provider errors are safe typed states rather than
raw exception text.

## 6. Release gates

- OAuth state/PKCE replay, cross-user callback, account mismatch and redirect
  validation fail closed;
- raw/opaque credentials are absent from every DB/API/Tool/model/log surface;
- real adapter tests cover connect, refresh, bounded read, scope loss and
  revoke; deployment smoke uses noncommitted credentials;
- Standard/Auto defaults, Conversation override, Turn snapshot and exact-call
  approval precedence pass API/UI/runtime tests;
- scheduler handles DST, minimum interval, idempotent duplicate tick and repair;
- Gmail cursor CAS, message dedupe/deletion tombstone, bounded batch merge and
  reconnect/rebaseline failure paths preserve source identity;
- ambiguous/late/archived/non-unique observations never auto-write; every
  allowed automatic ProcessEvent is scoped, reversible and visibly retractable;
- user PendingSubmission wins admission over retained automation;
- unattended catalog contains only exact current cloud-sustainable Tools and
  explicitly pinned Skill revisions; arbitrary Skill/MCP discovery is absent;
- trigger history, waiting/resume, pause, stop and delete rebuild across
  process/Redis/browser restart;
- task deletion requires a fresh aggregate impact token and proves scheduler
  fence, queue/draft cleanup, Dedicated Conversation teardown and bounded
  unknown-receipt retention;
- external/late outcomes keep call/trigger identity and never report fabricated
  success.
