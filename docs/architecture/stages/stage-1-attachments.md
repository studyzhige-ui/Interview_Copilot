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
`source_ref_id`, or an already persisted allowed path. It validates owner,
Conversation/InterviewRecord, frozen asset version and current source status.
Legacy `document_id`, upload-purpose and owner-wide raw-asset selectors are
forbidden.

## 5. Debrief promotion and lifecycle

Promotion is an explicit user product command from a valid ready Conversation
ref into the current owned InterviewRecord. `InterviewSourceRef` is only that
real relationship; it is not a Project/Memory/Source supertype. Sibling
Debrief Conversations bound to the same InterviewRecord may then retrieve it.
Removal revokes the Debrief relationship without rewriting the original
Conversation History/ref.

Conversation deletion removes its local grants and revokes no longer needed
ingestion tasks after commit. InterviewRecord deletion removes its promoted
relationships. File bytes are retained or deleted only by the FileAsset
retention contract; historical messages continue to show frozen identity or a
tombstone, never silently bind a newer version.

## 6. UI contract

Composer chips represent drafts, retained queued submissions show their frozen
draft selection, and Conversation/Debrief source lists read server projections.
States are processing, ready, failed and removed. Failed drafts/refs expose the
real retry endpoint; a failed claimed ref additionally exposes remove and
continue. Promotion and Debrief removal are explicit. Client-side filtering or
chip deletion never pretends server scope changed.

## 7. Release gates

- draft preflight is zero-write and claim-before-History is impossible;
- claim retry preserves one ref/order/version under concurrent submission;
- parse completion, failure, retry, callback race and maintenance repair all
  resume at most once with the expected waiting reason;
- remove-and-continue preserves frozen identity and never hides another source;
- Context selection is owner/scope/relevance bounded with explicit refs first;
- cross-Conversation and cross-InterviewRecord reads fail closed;
- `read_file` has no owner-wide bypass;
- deletion/replacement tests prove historical identity and promotion isolation;
- frontend refresh/multi-tab projections match the server.
