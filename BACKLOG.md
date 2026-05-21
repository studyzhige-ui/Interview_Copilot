# Interview_Copilot — Engineering Backlog

Items deferred from Checkpoint 3 (v3 memory refactor). All items here are
**non-blocking** — the v3 stack is shippable without them. They are
recorded so they aren't lost.

## Memory v3 — MEDIUM

### M1. `_topics_mentioned_in_messages` is O(topics × text) per dream
**File:** `backend/app/services/memory/dreaming_worker.py:343-371`

For users with 100+ topics + a long debrief, full scan every dream.
Cheap today, becomes hot path at scale.

**Fix:** Aho-Corasick automaton OR a SQL `LIKE ANY (...)` pre-filter
against the materialised message text.

---

### M2. Single-doc `apply_patches` keeps firing the LLM with empty body
**File:** `backend/app/services/memory/_single_doc_service.py:151-155`

If all 5 patches get dropped (`match_line` missing in a brand-new
strategy doc — common for first ingestion), no row materialises and
subsequent realtime turns keep firing the LLM with `{strategy}=（空）`.

**Fix:** Detect "all-dropped against empty doc" and either (a) instruct
the prompt to use `add` (no `match_line`) for first ingestion, or (b)
add a 24h cooldown when strategy/habit remains empty across N
consecutive turns.

---

### M3. NFKC drift on migrated bodies
**File:** `backend/app/services/memory/_doc_patch_protocol.py:251-260`

Bodies written via the protocol get NFKC-normalised on read; bodies
that existed pre-fix may still carry trailing periods. A patch whose
normaliser strips the period won't find an exact match.

**Fix:** One-shot migration that NFKC-normalises every existing body,
OR apply `_normalize_line` to both sides of the `index` lookup.

---

### M4. Dream may run for longer than the realtime lock-wait budget
**File:** `backend/app/services/memory/_user_memory_lock.py:66`

Wait budget is 15s; dreams typically finish in 30-60s. If user types
a follow-up while a dream is running, realtime extraction degrades to
no-lock after 15s — i.e. frequent degradation during active sessions.

**Fix:** Either accept it (surface via the metric — F9a is in place)
or cap dream LLM budget so dreams complete in &lt;10s.

---

### M5. `dream_for_record_task` retry policy mismatch
**File:** `backend/app/worker/tasks.py:325-352`

`autoretry_for=(ConnectionError, TimeoutError, OSError)` but the task
raises `RuntimeError`. Soft failures are never Celery-retried.

**Fix:** Either include `RuntimeError` in `autoretry_for` OR rewrite
the inline comment to honestly say "no celery-level retry; relies on
next nightly scan".

---

### M6. `delete_topic` audit order
**File:** `backend/app/services/memory/knowledge_doc_service.py:417-428`

Audit row claims `topic deleted` before the DELETE actually runs. Both
land in the same transaction so it's fine in practice; cosmetic only.

**Fix:** Move `audit_record` after `db.delete(doc)` and before
`db.commit()`.

---

### M7. Selection LLM cache key is exact-string
**File:** `backend/app/services/memory/v3_context_loader.py`

Cache key is `(user_id, query.lower(), max_topics)`. A follow-up like
"and what about the eviction policy?" misses the cache because the
exact string differs from "redis ttl".

**Fix:** Either accept (current behaviour wastes a free hit on similar
queries) OR hash a normalised representation (tokenised, stopwords
dropped) — adds complexity for limited gain. Defer.

---

## Memory v3 — LOW

### L1. `recall_policy.recall_enabled_for_session` and universal pass interaction
**File:** `backend/app/qa_pipeline/agent_executor.py:127-138`

When recall is off, `load_universal_memory` still runs (cheap — just
user_profile + index + strategy + habit). Privacy-minded users may
expect strategy/habit to ALSO disappear from the LLM context.

**Fix:** Document in the UI tooltip. Code change optional.

---

### L2. `load_universal` does 4 sequential DB reads per turn
**File:** `backend/app/services/memory/v3_context_loader.py:87-102`

Each helper opens + closes its own session. Cumulative latency ~5-15ms.
F9c already addressed snapshot consistency for the WRITE path
(`realtime_extraction._load_snapshot`); the READ path can do the same.

**Fix:** Open one session at `load_universal` entry, pass through.

---

### L3. Per-user nightly dream cost uncapped
**File:** `backend/app/services/memory/dreaming_worker.py:431-477`

A pathological user with many long debriefs costs O(records × 30K)
input tokens per night.

**Fix:** Per-user nightly token budget, or per-night per-user batch cap.

---

### L4. Knowledge topic in URL path can break on `/`, `?`, `#`
**File:** `backend/app/api/chat/memory_items.py:104-150`

`_sanitize_topic` strips `[]\n\r\t` but allows `/`, `?`, `#`. A topic
containing those will route incorrectly.

**Fix:** Either restrict topic charset further OR accept topic via
query/body param.

---

### L5. Dead code in interview API
**File:** `backend/app/api/interview.py:658-` (`_delete_milvus_doc_ids`)

The function used to be called by the now-removed memory cascade in
`delete_interview_record`. A test still patches it but never exercises
it — false confidence.

**Fix:** Delete the function + the test patch.

---

### L6. `add` patch can inject a fake section header
**File:** `backend/app/services/memory/_doc_patch_protocol.py:206-248`

`_normalize_line` collapses newlines but doesn't strip `## `. An LLM
that emits `{"op":"add","new_line":"## 已掌握的认知"}` will insert a
duplicate section header. Healed by the next canonicalise pass on
read, but in the meantime adds in that section may land wrong.

**Fix:** Reject `new_line` values starting with `## ` in
`parse_patches`.

---

### L7. Stale docstring
**File:** `backend/tests/test_models/test_models.py:15`

Module docstring still lists `MemoryItem` as covered.

**Fix:** Drop the line.

---

## Memory v3 — Test coverage to add later

- `_doc_patch_protocol.apply_patches` — protocol itself has no direct
  test (bugs here corrupt every memory write).
- `_audit_log_service.record`'s "shared db propagates, own db swallows"
  contract — the subtlest audit-layer invariant.
- `dreaming_worker._format_record_messages` floor — single-message-
  over-MAX_CHARS path is not covered.
- `user_memory_lock_sync` — Celery-side variant has no direct test.

---

## Outside memory v3

(none queued at the moment)
