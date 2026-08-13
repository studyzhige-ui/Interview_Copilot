import { apiClient } from './client';
import type { HistoryRecordDetail, HistorySearchInput, HistorySearchResponse } from '@/types/history';

/**
 * Searches the user's immutable Interaction Record projection.
 *
 * URLSearchParams is intentional here: FastAPI's list query parameters use
 * repeated keys (`kind=message&kind=tool_call`), not bracket notation.
 */
export async function searchInteractionHistory(
  input: HistorySearchInput,
): Promise<HistorySearchResponse> {
  const params = new URLSearchParams();
  params.set('query', input.query.trim().replace(/\s+/g, ' '));
  if (input.conversationId?.trim()) {
    params.set('conversation_id', input.conversationId.trim());
  }
  for (const kind of input.kinds ?? ['message', 'tool_call']) {
    params.append('kind', kind);
  }
  for (const role of input.roles ?? []) {
    params.append('role', role);
  }
  params.set('limit', String(input.limit ?? 20));

  return (await apiClient.get<HistorySearchResponse>('/history/search', { params })).data;
}

export async function readInteractionHistoryRecord(
  identity: string,
): Promise<HistoryRecordDetail> {
  return (
    await apiClient.get<HistoryRecordDetail>(
      `/history/records/${encodeURIComponent(identity)}`,
    )
  ).data;
}
