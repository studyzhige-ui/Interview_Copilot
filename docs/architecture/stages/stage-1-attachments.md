# Stage 1 Spec: files, attachment claims and scoped retrieval

## 1. Ownership boundary

`FileAsset` owns uploaded bytes and immutable asset versions.
`KnowledgeDocument`/chunks/vector entries are parsing and retrieval
projections. A Composer upload creates a durable `ConversationAttachmentDraft`
but grants no Conversation, History or RAG scope. Scope begins only when an
admitted submission atomically creates an immutable `ConversationAttachmentRef`
containing asset/version, source projection, Conversation, Turn, submission
and display order.

There is no generic Source Registry and no owner-wide `read_file` bypass.
Ordinary assistant analysis remains History unless a later explicit Artifact
command promotes it.

## 2. Draft and claim protocol

Draft creation verifies authenticated owner, `FileAsset`, matching
`KnowledgeDocument` projection and raw-byte availability. Draft removal before
claim is a soft revoke of the draft; it does not delete the asset. Submission
preflight locks and verifies every selected draft before any User message or
Turn exists. Claim is flush-only within the admission transaction and is
idempotent for the same submission/order. A draft already removed, rebound or
claimed by a different submission fails admission.

The ref freezes exact identity even while parsing is `processing` or `failed`.
Later replacement/reparse never silently changes a historical ref. Explicit
snapshot identity/version drift is a hard source error, not a fallback to the
newest file.

## 3. Parsing and waiting

`processing` causes the admitted Turn to become `waiting` with reason
`attachment_parsing`; it is not a generic failure. Ingestion completion checks
all nonremoved refs for that Turn. All ready resumes the same Turn with a new
dispatch generation. A failed projection keeps the Turn waiting and exposes
retry or remove-and-continue. Removing a failed claimed ref revokes only its
Conversation scope, preserves the immutable ref for audit, and resumes only
when every remaining ref is terminal/ready. Cancel remains a distinct user
choice.

Callbacks are best effort. A bounded maintenance scan repairs terminal
attachment waits after process/queue failure. The post-wait recheck closes the
race where ingestion finishes immediately before the waiting commit.

## 4. Retrieval scopes

Context Assembly selects sources at Turn time:

- explicit current-Turn refs are first, preserve user order and fail fast on
  owner/version/status mismatch;
- historical candidates are limited to the current Conversation;
- a Debrief Conversation may additionally read explicit `InterviewSourceRef`
  promotions belonging to the same owned InterviewRecord;
- query relevance/title/content chooses a bounded slice; generic file
  references may use a bounded recent fallback, but no query bulk-loads every
  ready document;
- removed, stale, pending or failed historical sources are excluded;
- chunk and source limits are fixed in code and measured in evaluation.

`read_file` accepts only an exact `attachment_ref_id`, an exact promoted
`source_ref_id`, or the `tool_call_id` of a completed Tool result belonging to
the current owned Turn. It validates owner, Conversation/InterviewRecord,
frozen asset version and current source status. Large Tool results are read
back from the canonical redacted `AgentToolCall.result_json`; a worker-local
path is never the durable or only copy. Legacy `path`, `document_id`,
upload-purpose and owner-wide raw-asset selectors are forbidden.

## 5. Debrief promotion and lifecycle

Promotion is an explicit user product command from a valid ready Conversation
ref into the current owned InterviewRecord. `InterviewSourceRef` is only that
real relationship; it is not a Project/Memory/Source supertype. Sibling
Debrief Conversations bound to the same InterviewRecord may then retrieve it.
Removal revokes the Debrief relationship without rewriting the original
Conversation History/ref. A ready Conversation ref may likewise be explicitly
revoked from its current Conversation scope; the immutable historical ref is
retained as a removed/tombstone projection and cannot be selected by later
Turns.

Promotion into a formal Artifact is a separate explicit command. It rereads an
owned ready `ConversationAttachmentRef` and freezes the same `file_asset_id`
and `file_asset_version` on the new `ArtifactVersion`; it does not copy parsed
text through the model. Promotion to `kind=resume` enters the canonical resume
Artifact parse/candidate workflow and never silently confirms CareerProfile
facts or directions.

Conversation deletion first blocks new admission, fences or safely terminates
the active Turn, withdraws queued submissions and releases their draft refs,
then removes its local grants and revokes no longer needed ingestion tasks.
InterviewRecord deletion removes its promoted relationships. An unresolved
external call may retain only a bounded receipt-correlation tombstone; a daily
bounded purge removes it after its owner-specific retention deadline.

Permanent FileAsset deletion is a distinct strongly confirmed command. Its
preflight lists current Conversation, Debrief and formal Artifact references,
plus known external transmissions. The command revokes Copilot-controlled
scope and deletes the controlled blob only after the exact filename is
confirmed; formal and historical references become tombstones instead of
silently binding a newer file. It truthfully states that copies already sent to
an external Provider remain governed by that Provider. Controlled download is
owner-scoped and streams bytes through the backend without exposing an object
key, bucket or storage URI.

## 6. Initial format, quality and page-vision contract

The first visual-layout path supports PDF, PNG and JPEG sources after the same
owner/scope/version checks as text retrieval. The initial bounded limits are:

- source bytes: 25 MiB;
- PDF pages: 100 per document;
- consecutive pages inspected by one Tool call: 4;
- rendered page: 1,600-pixel long edge, 2.5 million pixels and 2 MiB;
- rendered payload: 7 MiB per Tool call;
- provider observation text retained in the typed result: 20,000 characters.

`inspect_attachment_pages` is exposed only when the selected primary model and
Provider transport both support image content. Unsupported model, storage,
format, rendering or transport returns a typed blocked result; Chat does not
substitute OCR/text for a visual-layout claim and directs the user to an
eligible Agent path. Completion of a full visual review requires completed
receipts covering one exact FileAsset version and a contiguous range of every
page. These values are the initial Stage 1 resource contract, are versioned by
tests/telemetry, and may be changed only by a later Stage Spec decision rather
than silently widened in a handler.

## 7. UI contract

Composer chips represent drafts, retained queued submissions show their frozen
draft selection, and Conversation/Debrief source lists read server projections.
States are processing, ready, failed and removed. Source projections expose
typed parser/OCR/layout warnings and the coverage actually obtained. Failed
drafts/refs expose the real retry endpoint; a failed claimed ref additionally
exposes remove and continue. Ready-scope revoke, Debrief promotion/removal,
Artifact/resume promotion, controlled download and permanent deletion are
separate explicit controls with distinct impact text. Client-side filtering or
chip deletion never pretends server scope changed.

## 8. Release gates

- draft preflight is zero-write and claim-before-History is impossible;
- claim retry preserves one ref/order/version under concurrent submission;
- parse completion, failure, retry, callback race and maintenance repair all
  resume at most once with the expected waiting reason;
- remove-and-continue preserves frozen identity and never hides another source;
- Context selection is owner/scope/relevance bounded with explicit refs first;
- cross-Conversation and cross-InterviewRecord reads fail closed;
- `read_file` has no owner-wide or worker-local-path bypass, and oversized
  Tool-result paging rereads the canonical call row;
- text and page-vision coverage prove the exact frozen source version, with
  unsupported vision failing closed;
- scope revoke, permanent delete, replacement and whole-Conversation delete
  tests prove historical identity, impact disclosure and promotion isolation;
- Attachment-to-Artifact/resume promotion preserves exact byte-version
  provenance and never confirms CareerProfile implicitly;
- frontend refresh/multi-tab projections match the server.
