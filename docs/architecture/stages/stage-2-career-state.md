# Stage 2 Spec: CareerProfile and career-process state

## 1. One CareerProfile owner

`CareerProfile` is the single user-visible and editable owner for confirmed
personal details and confirmed job-search goals/constraints. It replaces the
former CandidateProfile/TargetDirection split at the product and Application
Service boundary. Physical normalization is allowed but cannot recreate a
second owner or service.

The root stores confirmed personal facts. Direction children have stable
identity so opportunities may reference one or more directions. Multiple
directions may share priority; priority and lifecycle
`active|exploring|paused|archived` are independent. A temporary search request
does not rewrite the profile, and current explicit input overrides stored
targets for that Turn.

Model/document extraction produces durable `CareerProfileCandidate` proposals,
never confirmed state. Accept/reject is explicit and versioned. Conflicting
facts require user resolution; a first resume may create clearly labelled
candidates but cannot silently become the profile.

## 2. AbilitySignal

`AbilitySignal` is a separate inferred Product Domain State, not a profile
fact and not Long-term Agent Memory. It records a bounded typed capability
judgement, uncertainty/time/applicability and direct identities of real owner
records such as InterviewRecord, InterviewQA or ConversationTurn. It can be
challenged, corrected or invalidated. Deleting all supporting live sources
forces recomputation, lower confidence or invalidation; a source-free signal
cannot continue as an unexplained fact.

User self-report may be a labelled candidate/source but cannot masquerade as
observed performance. AbilitySignal never writes back into CareerProfile or
rewrites source History/Interview records. Analytics reads this canonical
owner; legacy `memory_ability_states` must not remain a second user-visible
projection.

## 3. JobOpportunity and ProcessEvent

`JobOpportunity` owns a tracked job and its current projection. Provider/site
job identity, canonical URL and observed job snapshot support deterministic
de-duplication. A search result becomes tracked state only after a user product
command or an owned exact confirmation; browsing alone does not mutate the
funnel.

The observed JD is an append-only `JobDescriptionSnapshot` child of the owned
opportunity. It preserves canonical content/checksum, original and normalized
URL, provider, observation time, version and exact `AgentToolCall` or typed
product-UI source. A complete detail result can be captured atomically while
tracking; later `search_jobs` detail or `read_url` results are promoted only by
the explicit `capture_job_description` command. An application event freezes
the latest snapshot actually observed at that event time, and a correction
preserves the original snapshot pair. Current re-fetches never rewrite funnel
history. This child is not a generic Source Registry or a second opportunity
owner.

`ProcessEvent` is append-only history for application lifecycle facts. A
correction appends a relationship to the event it corrects rather than editing
history. The current opportunity stage/status is a deterministic projection of
live events. Client-facing APIs may accept user assertions; Tool/provider
observations and receipts are created only through their trusted handlers, not
through a caller-selectable source-kind field.

Duplicate detection returns deterministic candidate pairs and reasons; it
never merges from similarity alone. User-confirmed merge creates a versioned
relationship that preserves both opportunities, their provider/site identity,
sources and ProcessEvents. Retraction restores the independent projections
without rewriting either history. Active merge chains are rejected instead of
silently redirecting a third identity.

## 4. NextAction

`NextAction` is explicit business state, not AgentTask, SessionTask or a model
todo. It belongs to an owned opportunity or other real domain container,
records origin and lifecycle, and supports versioned update/complete/close.
Application Services may suggest one from a validated ProcessEvent in the same
transaction. A suggestion is visible state, not proof an action occurred.

Typed links connect an action to the real Interview, Offer or Artifact when
applicable. Deterministic derivation and idempotency prevent duplicate actions;
time conflicts remain multiple visible actions rather than a synthetic global
priority. A Reminder exists only for a `planned` action, uses the user's IANA
timezone/quiet hours and produces an in-app notification projection through a
bounded worker. It is not another task lifecycle. Historical funnel reads use
the direction, submitted Artifact version and application-channel snapshots
that were true at the event time and disclose sample IDs, field coverage and
confounding/missing data instead of backfilling current values.

## 5. Shared Agent/UI path

Pages and Agent Tools call the same Application Services. The current
task-shaped Tool slice is intentionally command-oriented rather than one CRUD
Tool per table:

- `read_career_context` reads relevant profile directions, opportunities and
  NextActions;
- `read_career_domain_state` performs bounded reads for pending Profile
  candidates, AbilitySignals, Interview/Debrief state, current Offers and
  PersistentTasks without creating a universal CareerState owner;
- `prepare_resume_profile_candidates` and
  `resolve_resume_profile_candidates` operate on canonical resume Artifact
  versions and explicit candidate identities;
- `confirm_career_profile_change` handles versioned fact/direction/candidate
  decisions, while `review_ability_signals` handles only challenge or
  source-owned recomputation;
- `track_search_job` accepts an exact owned completed `search_jobs` call result
  plus owned user confirmation and preserves a complete JD detail when present;
- `capture_job_description` promotes one exact owned completed `search_jobs`
  detail or `read_url` result into the existing opportunity's immutable JD
  snapshot history;
- `record_career_event` appends a confirmed event and may derive a suggested
  NextAction;
- `manage_next_action` handles the closed create/edit/plan/complete/close and
  Reminder command union against the same owner;
- `read_artifacts`/`save_artifact` bridge to the Stage 3 owner.

These are not generic CRUD Tools. Internal writes remain Policy-controlled,
cross-tenant references fail closed and Tool writes are immediately visible to
the page; page writes are immediately visible on the next Agent read.

## 6. Legacy migration

Legacy `user_profile` content is classified, not copied wholesale:

- confirmed/confirmable personal facts and targets -> CareerProfile candidates
  or confirmed fields only when provenance permits;
- ability judgements -> AbilitySignal migration with real source links or
  invalidation;
- explicit global collaboration rules -> CopilotPreference;
- Conversation/Interview-specific guidance -> its real owner when scope is
  provable;
- durable deliverables -> Artifact; actions -> NextAction;
- unclassifiable mixed prose -> migration report/archive, never new Memory.

After migration, legacy writers/Recall stay disabled and legacy rows cannot
affect Context, Analytics or UI. Migrations are idempotent and record enough
mapping to avoid duplicates without creating a compatibility owner.

## 7. Release gates

- one CareerProfile Application Service owns facts and direction children;
- candidates never affect matching/Context before acceptance;
- multiple directions, lifecycle/priority and temporary-request precedence
  pass deterministic tests;
- AbilitySignal source, uncertainty, challenge and invalidation are visible and
  cross-tenant safe;
- Analytics and Context read only canonical AbilitySignal;
- Job search -> explicit track -> event -> NextAction works through both Agent
  and UI against the same rows;
- duplicate opportunity merge/retraction preserves both identities and event
  histories and never runs from a heuristic alone;
- Reminder delivery and funnel analysis remain projections of canonical
  NextAction/ProcessEvent/submitted-version history;
- event correction preserves original history and current projection;
- legacy migration is idempotent, has no residual runtime reader/writer and
  does not route mixed content into Long-term Memory.
