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
  KnowledgeTopicDetail,
  KnowledgeTopicSummary,
  MasteryLevel,
  MemoryAuditDetail,
  MemoryAuditListResp,
  MemoryChangeType,
  MemoryDocType,
  MemoryOverviewResp,
} from '@/types/api';

// ── Overview ───────────────────────────────────────────────────────────

export async function getMemoryOverview(): Promise<MemoryOverviewResp> {
  const res = await apiClient.get('/memory/overview');
  return res.data;
}

// ── knowledge_doc ──────────────────────────────────────────────────────

export async function listKnowledgeTopics(): Promise<KnowledgeTopicSummary[]> {
  const res = await apiClient.get('/memory/knowledge/topics');
  return res.data?.topics ?? [];
}

export async function getKnowledgeTopic(
  topic: string,
  opts: { signal?: AbortSignal } = {},
): Promise<KnowledgeTopicDetail> {
  const res = await apiClient.get(
    `/memory/knowledge/topics/${encodeURIComponent(topic)}`,
    { signal: opts.signal },
  );
  return res.data;
}

export interface KnowledgeTopicPatch {
  body?: string;
  one_liner?: string | null;
  mastery_level?: MasteryLevel | null;
}

export async function editKnowledgeTopic(
  topic: string,
  patch: KnowledgeTopicPatch,
): Promise<void> {
  await apiClient.put(
    `/memory/knowledge/topics/${encodeURIComponent(topic)}`,
    patch,
  );
}

export async function deleteKnowledgeTopic(topic: string): Promise<void> {
  await apiClient.delete(
    `/memory/knowledge/topics/${encodeURIComponent(topic)}`,
  );
}

// ── strategy_doc + habit_doc ───────────────────────────────────────────

export async function getStrategyDoc(
  opts: { signal?: AbortSignal } = {},
): Promise<string> {
  const res = await apiClient.get('/memory/strategy', { signal: opts.signal });
  return String(res.data?.body ?? '');
}

export async function editStrategyDoc(body: string): Promise<void> {
  await apiClient.put('/memory/strategy', { body });
}

export async function getHabitDoc(
  opts: { signal?: AbortSignal } = {},
): Promise<string> {
  const res = await apiClient.get('/memory/habit', { signal: opts.signal });
  return String(res.data?.body ?? '');
}

export async function editHabitDoc(body: string): Promise<void> {
  await apiClient.put('/memory/habit', { body });
}

// ── user_profile_doc (read-only) ───────────────────────────────────────

export async function getUserProfileDoc(): Promise<string> {
  const res = await apiClient.get('/memory/user-profile');
  return String(res.data?.body ?? '');
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
