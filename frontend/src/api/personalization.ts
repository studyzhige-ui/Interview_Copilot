import { apiClient } from './client';
import type { CopilotPreference, ScopedGuidance } from '@/types/personalization';

export async function getCopilotPreference(): Promise<CopilotPreference> {
  return (await apiClient.get('/personalization/copilot-preference')).data;
}

export async function updateCopilotPreference(
  expectedVersion: number,
  instructions: string[],
): Promise<CopilotPreference> {
  return (
    await apiClient.put('/personalization/copilot-preference', {
      expected_version: expectedVersion,
      instructions,
    })
  ).data;
}
export async function getConversationGuidance(
  conversationId: string,
): Promise<ScopedGuidance> {
  return (
    await apiClient.get(
      `/personalization/conversations/${encodeURIComponent(conversationId)}/guidance`,
    )
  ).data;
}

export async function updateConversationGuidance(
  conversationId: string,
  expectedVersion: number,
  guidance: string | null,
  sourceMessageId: number | null,
): Promise<ScopedGuidance> {
  return (
    await apiClient.put(
      `/personalization/conversations/${encodeURIComponent(conversationId)}/guidance`,
      {
        expected_version: expectedVersion,
        guidance,
        source_message_id: sourceMessageId,
      },
    )
  ).data;
}

export async function getDebriefGuidance(interviewId: string): Promise<ScopedGuidance> {
  return (
    await apiClient.get(
      `/personalization/interviews/${encodeURIComponent(interviewId)}/guidance`,
    )
  ).data;
}

export async function updateDebriefGuidance(
  interviewId: string,
  expectedVersion: number,
  guidance: string | null,
  sourceMessageId: number | null = null,
): Promise<ScopedGuidance> {
  return (
    await apiClient.put(
      `/personalization/interviews/${encodeURIComponent(interviewId)}/guidance`,
      {
        expected_version: expectedVersion,
        guidance,
        source_message_id: sourceMessageId,
      },
    )
  ).data;
}
