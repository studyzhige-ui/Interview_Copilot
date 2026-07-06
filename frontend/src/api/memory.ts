/**
 * v3 memory inspection + edit client.
 *
 * Mirrors ``backend/app/api/memory.py``. Four doc types:
 *
 *   user_profile  — single doc, identity / preferences (read-only here;
 *                   no PUT endpoint on the backend).
 *   knowledge     — N topic-keyed docs, technical understanding per topic.
 *   strategy      — single doc, answering methodology.
 *   habit         — single doc, practice routine / mindset.
 *
 * The audit log endpoints are also wired here — they back the "browse
 * memory history" UI and the "why does my profile look weird?" debug
 * flow.
 */
import { apiClient } from './client';
import type {
  MemoryAuditDetail,
  MemoryAuditListResp,
  MemoryChangeType,
  MemoryDocType,
  MemoryOverviewResp,
} from '@/types/api';

// ── Overview ───────────────────────────────────────────────────────────

export async function getMemoryOverview(
  opts: { signal?: AbortSignal } = {},
): Promise<MemoryOverviewResp> {
  const res = await apiClient.get('/memory/overview', { signal: opts.signal });
  return res.data;
}

// ── v3 memory docs: user_profile / learning_strategy (RW) ─────────────
// Both PUTs carry the optimistic-concurrency token (MEM-3): the updated_at
// from the GET this edit was based on. A 409 means realtime extraction (or
// another tab) wrote in between — refetch and re-edit.

export interface MemoryDocMeta {
  body: string;
  updated_at: string | null;
}

export async function getUserProfileDoc(
  opts: { signal?: AbortSignal } = {},
): Promise<MemoryDocMeta> {
  const res = await apiClient.get('/memory/user-profile', { signal: opts.signal });
  return { body: String(res.data?.body ?? ''), updated_at: res.data?.updated_at ?? null };
}

export async function editUserProfileDoc(
  body: string,
  baseUpdatedAt: string | null,
): Promise<void> {
  await apiClient.put('/memory/user-profile', {
    body,
    base_updated_at: baseUpdatedAt,
  });
}

export async function getLearningStrategyDoc(
  opts: { signal?: AbortSignal } = {},
): Promise<MemoryDocMeta> {
  const res = await apiClient.get('/memory/learning-strategy', { signal: opts.signal });
  return { body: String(res.data?.body ?? ''), updated_at: res.data?.updated_at ?? null };
}

export async function editLearningStrategyDoc(
  body: string,
  baseUpdatedAt: string | null,
): Promise<void> {
  await apiClient.put('/memory/learning-strategy', {
    body,
    base_updated_at: baseUpdatedAt,
  });
}

// ── ability states ─────────────────────────────────────────────────────

export interface AbilityState {
  id: string;
  topic: string;
  skill_type: string;
  mastery_level: 'weak' | 'improving' | 'stable' | 'strong';
  summary: string;
  last_evidence_at: string | null;
  updated_at: string | null;
}

export async function listAbilityStates(
  opts: { signal?: AbortSignal } = {},
): Promise<AbilityState[]> {
  const res = await apiClient.get('/memory/ability-states', { signal: opts.signal });
  return res.data?.ability_states ?? [];
}

/** Archive (user veto) — automatic extraction won't recreate the pair for
 *  30 days (backend tombstone, MEM-2). */
export async function archiveAbilityState(id: string): Promise<void> {
  await apiClient.delete(`/memory/ability-states/${encodeURIComponent(id)}`);
}

// ── audit log ──────────────────────────────────────────────────────────

export interface MemoryAuditQuery {
  doc_type?: MemoryDocType;
  topic?: string;
  change_type?: MemoryChangeType;
  /** ISO-8601 timestamp; entries created at-or-after this point. */
  since?: string;
  limit?: number;
  offset?: number;
}

export async function listMemoryAudit(
  q: MemoryAuditQuery = {},
  opts: { signal?: AbortSignal } = {},
): Promise<MemoryAuditListResp> {
  const res = await apiClient.get('/memory/audit', {
    params: q,
    signal: opts.signal,
  });
  return res.data;
}

export async function getMemoryAuditEntry(
  entryId: string,
  opts: { signal?: AbortSignal } = {},
): Promise<MemoryAuditDetail> {
  const res = await apiClient.get(
    `/memory/audit/${encodeURIComponent(entryId)}`,
    { signal: opts.signal },
  );
  return res.data;
}
