import { apiClient } from './client';
import type {
  InterviewRecordListItem,
  InterviewRecordDetail,
  AnalyzeStatus,
} from '@/types/api';

export async function listInterviewRecords(
  offset = 0,
  limit = 50,
): Promise<InterviewRecordListItem[]> {
  const res = await apiClient.get('/interview-records', { params: { offset, limit } });
  return res.data;
}

export async function getInterviewRecord(id: string): Promise<InterviewRecordDetail> {
  const res = await apiClient.get(`/interview-records/${encodeURIComponent(id)}`);
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

export async function uploadResume(file: File): Promise<{ upload_id: string; filename: string }> {
  const fd = new FormData();
  fd.append('file', file);
  const res = await apiClient.post('/upload/resume/direct', fd);
  return res.data;
}

export async function startAnalyze(payload: {
  upload_id: string;
  resume_upload_id: string;
  jd_text?: string;
  jd_upload_id?: string;
}): Promise<{ interview_id: number; task_id: string }> {
  const res = await apiClient.post('/analyze', payload);
  return res.data;
}

export async function getAnalyzeStatus(interviewId: number): Promise<AnalyzeStatus> {
  const res = await apiClient.get(`/analyze/${interviewId}/status`);
  return res.data;
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
  qaIndex: number,
  patch: { question?: string; answer?: string; suggestion?: string },
): Promise<void> {
  await apiClient.patch(
    `/interview-records/${encodeURIComponent(recordId)}/qa/${qaIndex}`,
    patch,
  );
}
