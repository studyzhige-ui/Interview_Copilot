import { apiClient } from './client';
import type {
  ChatSessionCreateResp,
  ChatSessionListItem,
  ChatMessageItem,
} from '@/types/api';

export async function createChatSession(payload: {
  session_type: 'general' | 'debrief' | 'mock_interview';
  interview_id?: string;
  title?: string;
}): Promise<ChatSessionCreateResp> {
  const res = await apiClient.post('/chat/sessions', payload);
  return res.data;
}

export async function listChatSessions(
  q: { offset?: number; limit?: number; session_type?: string; interview_id?: string } = {},
): Promise<ChatSessionListItem[]> {
  const res = await apiClient.get('/chat/sessions', {
    params: { offset: 0, limit: 50, ...q },
  });
  return res.data;
}

export async function getChatHistory(
  sessionId: string,
  offset = 0,
  limit = 100,
): Promise<ChatMessageItem[]> {
  const res = await apiClient.get('/chat/history', { params: { session_id: sessionId, offset, limit } });
  return res.data;
}

export async function renameChatSession(sessionId: string, title: string): Promise<void> {
  // Backend now prefers JSON body; query param kept as fallback for compat.
  await apiClient.patch(`/chat/sessions/${encodeURIComponent(sessionId)}/title`, { title });
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/chat/sessions/${encodeURIComponent(sessionId)}`);
}
