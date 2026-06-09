import { apiClient } from './client';
import type {
  AnalyzeDispatchResp,
  InterviewRecordDetail,
  InterviewRecordListItem,
} from '@/types/api';

export async function listInterviewRecords(
  offset = 0,
  limit = 50,
  opts: { signal?: AbortSignal } = {},
): Promise<InterviewRecordListItem[]> {
  const res = await apiClient.get('/interview-records', {
    params: { offset, limit },
    signal: opts.signal,
  });
  return res.data;
}

export async function getInterviewRecord(
  id: string,
  opts: { signal?: AbortSignal } = {},
): Promise<InterviewRecordDetail> {
  const res = await apiClient.get(
    `/interview-records/${encodeURIComponent(id)}`,
    { signal: opts.signal },
  );
  return res.data;
}

export async function getInterviewSummary(id: string): Promise<string | null> {
  try {
    const res = await apiClient.get(`/interview-records/${encodeURIComponent(id)}/summary`);
    return res.data?.summary ?? null;
  } catch {
    return null;
  }
}

export async function uploadAudio(file: File): Promise<{ upload_id: string; filename: string }> {
  const fd = new FormData();
  fd.append('file', file);
  const res = await apiClient.post('/upload/audio/direct', fd);
  return res.data;
}

/** A personal resume the user can pick as interview context (the first-class
 *  `resumes` entity — NOT a knowledge document). */
export interface StoredResume {
  resume_id: string;
  title: string;
  is_default: boolean;
  parse_status: string;
  created_at: string;
}

export async function listStoredResumes(): Promise<StoredResume[]> {
  const res = await apiClient.get('/uploads/resumes');
  return res.data?.resumes ?? [];
}

/** Dispatch a unified analysis on an uploaded audio file. Returns the new
 *  `record_id` of the InterviewRecord — subscribe to SSE to follow progress.
 *  Resume context is optional: either a personal resume (`resume_id`) or an
 *  ad-hoc file uploaded for this interview (`resume_file_asset_id`). JD is a
 *  snapshot only — `jd_text` or `jd_file_asset_id` (never a knowledge doc). */
export async function startAnalyze(payload: {
  upload_id: string;
  resume_id?: string;
  resume_file_asset_id?: string;
  jd_text?: string;
  jd_file_asset_id?: string;
  /** WhisperX language hint. ``"zh"`` / ``"en"`` force the decoder
   *  (much more accurate on monolingual audio). ``"auto"`` lets Whisper
   *  detect per clip — only use for genuinely mixed recordings. */
  language?: 'zh' | 'en' | 'auto';
}): Promise<AnalyzeDispatchResp> {
  const res = await apiClient.post('/analyze', payload);
  return res.data;
}

export async function cancelAnalyze(recordId: string): Promise<void> {
  await apiClient.post(`/analyze/${encodeURIComponent(recordId)}/cancel`);
}

export async function getAnalyticsReport(): Promise<unknown> {
  const res = await apiClient.get('/analytics/report');
  return res.data;
}

export async function renameInterviewRecord(id: string, title: string): Promise<void> {
  await apiClient.patch(`/interview-records/${encodeURIComponent(id)}`, { title });
}

export async function updateInterviewRecord(
  id: string,
  patch: { title?: string; tag?: string },
): Promise<void> {
  await apiClient.patch(`/interview-records/${encodeURIComponent(id)}`, patch);
}

export async function deleteInterviewRecord(
  id: string,
  opts: { cascadeChats?: boolean } = {},
): Promise<void> {
  await apiClient.delete(`/interview-records/${encodeURIComponent(id)}`, {
    params: opts.cascadeChats ? { cascade_chats: true } : undefined,
  });
}

export async function editInterviewQA(
  recordId: string,
  qaId: string,
  patch: { question?: string; answer?: string; critique?: string; improved_answer?: string },
): Promise<void> {
  await apiClient.patch(
    `/interview-records/${encodeURIComponent(recordId)}/qa/${encodeURIComponent(qaId)}`,
    patch,
  );
}
