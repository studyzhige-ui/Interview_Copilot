# Stage 3 Spec: Artifacts, Interviews, Offers and Client Actions

## 1. Artifact and versions

An `Artifact` exists only after explicit save/promotion or a product Flow whose
contract is a durable deliverable. Ordinary assistant answers remain History.
Every edit appends an immutable `ArtifactVersion`; the current version is the
highest version number. Archive hides the Artifact from default lists but does
not delete versions or their provenance.

Provenance directly references the real message, Turn, FileAsset or domain
owner. Saving a version proves that content exists, not that every claim is
current truth. There is no generic Evidence/Source ledger.

`related` is a weak reusable relationship. `submitted` freezes an exact
ArtifactVersion against an owned JobOpportunity after explicit product-UI/user
confirmation or a validated provider receipt. Creating v2 after v1 was
submitted never changes the submitted snapshot. APIs expose the Artifact list,
current version, version history, relationships and submission history with
the nested frozen version. All are tenant scoped and remain readable after
archive.

The Agent command `record_artifact_submission` uses the same exact-version
Application Service and an owned current user assertion. It records what the
user says was already submitted and returns
`external_action_performed=false`; it never claims that the Agent uploaded or
sent the material. Attachment promotion reuses the frozen FileAsset identity
and byte-version rather than copying parsed text into a new provenance owner.

## 2. Interview and Debrief

Real and Mock `InterviewRecord` may optionally reference an owned
JobOpportunity through a real nullable FK; clearing the relation is explicit.
Mock remains valid without a job. Owner validation occurs before LLM planning
or Client Action creation.

Debrief Conversations bind to the InterviewRecord. Explicit promoted sources
use Stage 1 relationships. If Debrief guidance is enabled, it is a visible,
editable, versioned field on that InterviewRecord with set/modify/clear and
record deletion semantics; it is not CopilotPreference or Project Memory.
Conversation guidance and global CopilotPreference retain their own owners.

Interview analysis may create canonical AbilitySignals through the Stage 2
service, but cannot rewrite profile facts or hide the underlying QA/transcript.
The Agent's `start_interview_debrief` accepts only an owned, validated audio
FileAsset, creates the real InterviewRecord and dispatches the bounded analysis
job; its immediate result is `processing`, not a fabricated completed report.

## 3. Offer aggregate

At most one current Offer aggregate belongs to an opportunity. Each observed
source excerpt retains its real source identity and formality (for example
written or verbal); current normalized terms do not overwrite source wording.
A non-conflicting supplement uses version CAS. Replacement or conflict returns
a typed diff and requires exactly one explicit confirmation mode: a real owned
user message or a product-UI command with a stable operation key. Idempotent
replay returns the same result; stale CAS fails.

The product does not implement accept/decline as a fake local button unless the
corresponding real external/internal action and result contract exists.

Multi-Offer analysis keeps observed term sources separate from user-supplied
exchange-rate, tax and equity assumptions and their observation time. It may
derive a deadline NextAction or explicitly save a versioned analysis Artifact.
Negotiation assistance produces an Artifact draft labelled `not_sent`; there
is no hidden email/message dispatch, acceptance, rejection, signature or
onboarding confirmation. The Agent's `analyze_offers` follows the same
read/compare/save boundary.

## 4. Client Action and Mock handoff

Agent requests for browser/device behavior use the Stage 0 durable Client
Action protocol. Mock handoff has distinct actions:

1. prefill acknowledged;
2. device/UI readiness confirmed;
3. server runtime start returns real InterviewRecord/runtime identities;
4. entered-UI acknowledgement.

Only the initiating client receives the action by default. Disconnect replay,
explicit takeover, refusal and failure use the same Interaction/action/call
identity and version checks. A missing client or unsaved form is `waiting` or
an honest failure, never fabricated success.

## 5. UI contract

The asset workspace reads the server list and histories, uses real opportunity
selectors and displays exact submitted versions. The career/interview UIs
offer an optional owned opportunity selector. Offer conflict UI renders the
typed diff and sends the product-UI confirmation contract rather than asking
the user to manufacture a ConversationMessage id.

Client Action handling lives once at the app shell so route changes do not
duplicate delivery. The active execution column still follows Stage 0.

## 6. Release gates

- ordinary answer creates zero Artifact; explicit promotion preserves source;
- edit is append-only and archive keeps every version/history;
- related and submitted never alias; v1 submission remains v1 after v2;
- product UI and Agent exact-version submission commands remain idempotent and
  never claim an external send without a receipt;
- Artifact/Offer/Interview reads and commands reject cross-tenant identities;
- Offer mixed source excerpts, conflict diff, CAS and idempotent confirmation
  pass through API and UI;
- real and Mock Interviews support valid optional opportunity linkage;
- audio Debrief intake returns a real record/job identity and honest
  processing/failure state;
- Offer comparison exposes assumptions/source times, deadline actions and
  `not_sent` negotiation Artifacts without implementing retained decisions;
- Mock Client Action proves all four distinct phases, affinity, replay,
  takeover, refusal and failure against the same call;
- Debrief sources/guidance stay within their InterviewRecord owner.
