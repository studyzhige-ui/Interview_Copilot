# Stage 5 Spec: career scenarios and Long-term Agent Memory gate

## 1. Scope and authority

This specification implements Stage 5 of the authoritative architecture. It
freezes the evaluation contract and the gate that decides whether the one
user-level Long-term Agent Memory producer may be enabled. It does not redefine
CareerProfile, AbilitySignal, CopilotPreference, Artifact, Interaction Records,
Conversation compaction or Runtime recovery as Memory.

The production boundary is deliberately explicit:

- the legacy realtime extractor, Dreaming worker and `save_memory` Tool remain
  removed;
- the canonical selective Recall path is implemented and loads only relevant,
  active, user-owned low-authority items; an empty Recall remains valid;
- no legacy `user_profile`, `ability_states` or `learning_strategy` row may be
  wrapped and injected as new Memory;
- the single automatic producer is implemented and registered, but a separate
  deployment release gate defaults to off until every gate in section 6 passes
  on a representative, reviewed dataset; account or Conversation contribution
  controls cannot bypass that release gate;
- an empty Recall is a valid result and must not change Turn semantics.

This is a gated product decision, not an unfinished compatibility fallback.

## 2. One future owner and one semantic path

The product has one canonical user-level Long-term Agent Memory collection. It
has one logical automatic formation and
consolidation path and one logical Recall path; either path may be horizontally
scaled with idempotency. Direct user correction, invalidation and deletion act
on the same canonical records and are not a second automatic writer.

Conversation, InterviewRecord/Debrief and project-scoped Memory stores are
forbidden. Source Conversation/Turn identities, formation context and
applicability tags are provenance and relevance hints, not storage scope or
permission scope.

## 3. Admission contract

A candidate is eligible only when all conditions are true:

1. Its source Turn is terminal, the source Conversation has no active or
   waiting work, and the configured idle/stability delay has elapsed.
2. It has reasonable value for a future independent task or Conversation, not
   merely the remainder of the current Conversation.
3. It can improve personalized service and is sufficiently durable; copying
   all History or every repeated phrase is forbidden.
4. No existing owner already holds the content. Confirmed personal facts and
   goals route to CareerProfile; ability understanding routes to AbilitySignal;
   explicit global collaboration rules route to CopilotPreference; local
   guidance stays with its Conversation or InterviewRecord; files and durable
   deliverables route to Artifact/FileAsset; exact past interaction stays in
   History; actions route to NextAction.
5. It contains no secret, credential, authentication material, protected
   hidden prompt, permission grant, current execution state or unnecessary
   sensitive content.
6. It is phrased as a low-authority experience or pattern with source and time,
   not as a verified current fact or mandatory instruction.

Eligible content is not limited to job-search topics. Examples include a
conditioned explanation style that repeatedly helped, a comparison or review
workflow that led to better decisions, or a recurring way of presenting
options that proved ineffective. These examples do not form content enums or
separate pipelines.

## 4. Recall and authority contract

Recall is task-relevant and bounded. It never bulk-loads every record. Recalled
items are explicitly labelled as low-authority personalization data and appear
in the user-specific message area, never in the stable cross-user system
prefix. Priority is:

1. product safety, Policy and Provider scope;
2. current accepted user input;
3. current Conversation guidance;
4. applicable InterviewRecord/Debrief guidance;
5. global CopilotPreference;
6. relevant Long-term Agent Memory;
7. defaults.

Memory cannot prove current facts, exact history, product state or execution
success. Before making such a claim the runtime must read the real owner,
History, ToolResult or provider receipt/read-back. When source state is deleted,
revoked, stale or conflicts with a current owner, the item is excluded or
invalidated before prompt assembly.

## 5. User control and deletion contract

Recall and contribution are independent controls. When the feature is enabled,
account defaults and per-Conversation overrides may independently answer:

- may existing Long-term Memory affect this Conversation;
- may eligible terminal Turns from this Conversation contribute to future
  Memory.

These controls do not create scoped Memory. A Turn-level request to ignore
Memory overrides Recall for that Turn. Turning either control off does not
delete existing items.

Explicit deletion removes the recallable body and every FTS/vector/cache
projection. A minimal content-free suppression marker may retain source
identity, deletion boundary and hash solely to prevent automatic resurrection.
The automatic producer uses the canonical semantic identity plus exact
source-Turn idempotency and never periodically rescans old History. Material
from a previously processed source cannot recreate the deleted item; this
release has no automatic or generic create path that removes suppression.
Deleting a source Conversation makes
that History immediately ineligible; an item supported only by that source is
invalidated or deleted, while independently supported content is recomputed
from remaining live sources.

No body snapshot may remain in an audit row after a user forgets it. The UI
shows the canonical records and source identities and lets the user revise,
invalidate, delete or promote an experience into CopilotPreference. It must
show that automatic contribution is deployment-gated when the representative
evaluation has not passed; it may never present a toggle as effective when the
release gate is closed.

## 6. Automatic producer release gates

All gates are required; a partial pass keeps the automatic producer disabled.
Recall remains available only for already canonical, user-owned records and is
validly empty when none exist; it never reads legacy mixed stores. The
evaluation report records denominator, numerator, dataset revision,
model/provider configuration and exact code revision.

| Gate | Required result |
|---|---|
| Owner routing | 100% of CareerProfile, AbilitySignal, guidance, Artifact, History, ToolResult, Policy, secret, compaction and recovery examples rejected or routed to their real owner |
| Sensitive-content exclusion | 100% of seeded credentials, authentication data and hidden-policy examples excluded before durable write and before prompt assembly |
| Cross-task value | reviewed eligible items improve the target future task at an agreed threshold without relying on exact source transcript |
| Irrelevant recall | 0 high-severity unrelated items; bounded low-severity rate defined by the reviewed release dataset |
| Current-owner conflict | 0 stale/conflicting item stated as current fact; 100% of factual uses perform owner/History/receipt read-back |
| Scope isolation | 0 cross-user leaks and 0 Conversation/Debrief/Project Memory stores or implicit scope expansion |
| Recall disabled | 0 explicit or implicit influence on prompts, Tool selection, Policy, state writes or answers |
| Contribution disabled | 0 new/updated records from disabled Conversations |
| Forget and source deletion | 0 recall after deletion and 0 resurrection from old source ranges across retry, compaction, replay and worker restart |
| Promotion de-duplication | 0 duplicate effect after an experience is confirmed into CareerProfile or CopilotPreference |
| Logical path uniqueness | exactly one automatic formation/consolidation path and one Recall semantic path; indexes remain rebuildable projections |

## 7. Career-product scenario suite

Stage 5 also owns a deterministic regression matrix spanning the real product,
not only RAG quality. The executable matrix must cover at least:

- CareerProfile direction -> real `search_jobs` result -> explicit user
  inclusion -> JobOpportunity -> ProcessEvent -> NextAction;
- Artifact creation, versioning, related/submitted distinction and exact
  submitted-version freeze;
- real or Mock Interview optionally linked to an owned JobOpportunity, with
  Debrief sources and guidance isolated to the correct InterviewRecord;
- Offer term replacement/supplement conflict and typed product-UI confirmation;
- PendingSubmission FIFO/idempotency, attachment claim, waiting Interaction,
  interrupt fence, late Tool receipt and durable replay;
- AgentTask simple/complex thresholds and terminal completion gate;
- Mock Client Action prefill/readiness/runtime/entered-UI phases with initiating
  client affinity, takeover, refusal and replay;
- Standard/Auto parameter-level Policy with connection and Provider scope
  limits;
- PersistentTask scheduled/manual admission, user-input priority, trigger
  history, waiting, pause, cancellation and deletion;
- Gmail OAuth connect, refresh, bounded read, revoke and secret non-disclosure;
- the canonical-Memory gates above.

The matrix references executable backend and frontend tests. A missing test,
unknown selector, skipped mandatory scenario or non-zero test command is a gate
failure. Network-dependent provider tests use a protocol-faithful fake at the
HTTP boundary; a separate deployment smoke test proves the configured live
connector without committing credentials or provider data.

## 8. Current release decision

The canonical store, selective Recall, user management and the one automatic
producer path are implemented. No representative automatic-memory benefit/error
dataset has yet passed section 6, so the conforming release configuration is:

```
automatic_memory_producer = implemented_but_release_gate_disabled
memory_recall = selective_canonical_low_authority_items_or_empty
legacy_memory_runtime_read = forbidden
```

Enabling any of these without a versioned evaluation report and all gates is a
release-blocking defect.
