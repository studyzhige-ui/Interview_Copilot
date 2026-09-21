import type { components } from '@/types/generated/shared-protocols';
import { apiClient } from './client';

export type TranscriptPage = components['schemas']['TranscriptPage'];
export type TranscriptWord = components['schemas']['TranscriptWordView'];
export type TranscriptCommand = components['schemas']['TranscriptCorrectionRequest'];
export type TranscriptReceipt = components['schemas']['TranscriptCorrectionReceipt'];
export type TranscriptHistoryPage = components['schemas']['TranscriptHistoryPage'];
export type PlaybackRequest = components['schemas']['TranscriptPlaybackRequest'];
export type SpeakerRole = NonNullable<TranscriptCommand['speaker_roles']>[string];

const root = (recordId: string) => `/interview-records/${encodeURIComponent(recordId)}/transcript`;

export async function getTranscript(recordId: string, options: {
  transcriptId?: string; offset?: number; signal?: AbortSignal;
} = {}): Promise<TranscriptPage> {
  const response = await apiClient.get<TranscriptPage>(root(recordId), {
    params: { transcript_id: options.transcriptId, offset: options.offset ?? 0, limit: 100 },
    signal: options.signal,
  });
  return response.data;
}

export async function correctTranscript(recordId: string, command: TranscriptCommand): Promise<TranscriptReceipt> {
  const response = await apiClient.post<TranscriptReceipt>(`${root(recordId)}/corrections`, command);
  return response.data;
}

export async function getTranscriptReceipt(recordId: string, requestId: string): Promise<TranscriptReceipt> {
  const response = await apiClient.get<TranscriptReceipt>(`${root(recordId)}/corrections/${encodeURIComponent(requestId)}`);
  return response.data;
}

export async function getTranscriptHistory(recordId: string, before?: string, signal?: AbortSignal): Promise<TranscriptHistoryPage> {
  const response = await apiClient.get<TranscriptHistoryPage>(`${root(recordId)}/corrections`, {
    params: { before, limit: 20 }, signal,
  });
  return response.data;
}

export async function getTranscriptAudio(recordId: string, selection: PlaybackRequest,
  sha256: string, signal: AbortSignal): Promise<Blob> {
  const response = await apiClient.post<Blob>(`${root(recordId)}/playback`, selection, {
    responseType: 'blob', signal, timeout: 125_000,
  });
  if (response.headers['x-transcript-id'] !== selection.transcript_id
      || response.headers['x-audio-source-sha256'] !== sha256
      || !response.data.type.startsWith('audio/wav') || response.data.size > 960_044) {
    throw new Error('回放响应与所选转写来源不一致');
  }
  return response.data;
}
