import { apiClient } from './client';
import { uploadFileAsset } from './fileAssets';
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

export async function uploadAudio(file: File): Promise<{ upload_id: string; filename: string }> {
  // Unified presigned flow (purpose='interview_audio') — no server-receives-bytes
  // direct upload. Returns the confirmed file_asset id as upload_id.
  const fileAssetId = await uploadFileAsset(file, 'interview_audio');
  return { upload_id: fileAssetId, filename: file.name };
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

/** ANA-7: re-run analysis for a failed/completed upload record. Stage gates
 *  on the backend reuse the persisted transcript + QA shells. */
export async function reanalyzeRecord(recordId: string): Promise<void> {
  await apiClient.post(`/interview-records/${encodeURIComponent(recordId)}/reanalyze`);
}

export async function cancelAnalyze(recordId: string): Promise<void> {
  await apiClient.post(`/analyze/${encodeURIComponent(recordId)}/cancel`);
}

export async function getAnalyticsReport(): Promise<unknown> {
  const res = await apiClient.get('/analytics/report');
  return res.data;
}

export async function updateInterviewRecord(
  id: string,
  patch: { title?: string; tag?: string },
): Promise<void> {
  await apiClient.patch(`/interview-records/${encodeURIComponent(id)}`, patch);
}

export async function deleteInterviewRecord(
  id: string,
  /** Also delete the knowledge documents this interview's QAs published. */
  opts: { cascadeKnowledge?: boolean } = {},
): Promise<void> {
  await apiClient.delete(`/interview-records/${encodeURIComponent(id)}`, {
    params: opts.cascadeKnowledge ? { cascade_knowledge: true } : undefined,
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

/** Publish a QA's improved answer to the knowledge base (source_kind=improved_qa). */
export async function saveQAToKnowledge(
  recordId: string,
  qaId: string,
  opts: { category?: string } = {},
): Promise<{ document_id: string; saved_document_id: string }> {
  const res = await apiClient.post(
    `/interview-records/${encodeURIComponent(recordId)}/qa/${encodeURIComponent(qaId)}/save-to-knowledge`,
    { category: opts.category },
  );
  return res.data;
}

/** Remove the knowledge document previously saved from this QA. */
export async function unsaveQAFromKnowledge(recordId: string, qaId: string): Promise<void> {
  await apiClient.delete(
    `/interview-records/${encodeURIComponent(recordId)}/qa/${encodeURIComponent(qaId)}/save-to-knowledge`,
  );
}
