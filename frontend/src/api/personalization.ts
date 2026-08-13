import { apiClient } from './client';
import type {
  AgentMemory,
  AgentMemoryPromotion,
  AgentMemorySettings,
  ConversationMemoryControls,
  CopilotPreference,
  ScopedGuidance,
} from '@/types/personalization';

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

export async function getAgentMemorySettings(): Promise<AgentMemorySettings> {
  return (await apiClient.get('/personalization/memory-settings')).data;
}

export async function updateAgentMemorySettings(
  expectedVersion: number,
  recallEnabled: boolean,
  contributionEnabled: boolean,
): Promise<AgentMemorySettings> {
  return (
    await apiClient.put('/personalization/memory-settings', {
      expected_version: expectedVersion,
      recall_enabled: recallEnabled,
      contribution_enabled: contributionEnabled,
    })
  ).data;
}

export async function getConversationMemoryControls(
  conversationId: string,
): Promise<ConversationMemoryControls> {
  return (
    await apiClient.get(
      `/personalization/conversations/${encodeURIComponent(conversationId)}/memory-controls`,
    )
  ).data;
}

export async function updateConversationMemoryControls(
  conversationId: string,
  expectedVersion: number,
  recallOverride: boolean | null,
  contributionOverride: boolean | null,
): Promise<ConversationMemoryControls> {
  return (
    await apiClient.put(
      `/personalization/conversations/${encodeURIComponent(conversationId)}/memory-controls`,
      {
        expected_version: expectedVersion,
        recall_override: recallOverride,
        contribution_override: contributionOverride,
      },
    )
  ).data;
}

export async function getAgentMemories(
  includeInactive = true,
  limit = 100,
): Promise<AgentMemory[]> {
  return (
    await apiClient.get('/personalization/memories', {
      params: { include_inactive: includeInactive, limit },
    })
  ).data;
}

export async function updateAgentMemory(
  memoryId: string,
  expectedVersion: number,
  content: string,
  applicability: string,
  tags: string[],
): Promise<AgentMemory> {
  return (
    await apiClient.patch(`/personalization/memories/${encodeURIComponent(memoryId)}`, {
      expected_version: expectedVersion,
      content,
      applicability,
      tags,
    })
  ).data;
}

export async function invalidateAgentMemory(
  memoryId: string,
  expectedVersion: number,
  reason: string,
): Promise<AgentMemory> {
  return (
    await apiClient.post(
      `/personalization/memories/${encodeURIComponent(memoryId)}/invalidate`,
      { expected_version: expectedVersion, reason },
    )
  ).data;
}

export async function deleteAgentMemory(
  memoryId: string,
  expectedVersion: number,
  reason: string,
): Promise<AgentMemory> {
  return (
    await apiClient.delete(`/personalization/memories/${encodeURIComponent(memoryId)}`, {
      data: { expected_version: expectedVersion, reason },
    })
  ).data;
}

export async function promoteAgentMemoryToPreference(
  memoryId: string,
  expectedMemoryVersion: number,
  expectedPreferenceVersion: number,
  instruction: string,
): Promise<AgentMemoryPromotion> {
  return (
    await apiClient.post(
      `/personalization/memories/${encodeURIComponent(memoryId)}/promote-to-preference`,
      {
        expected_memory_version: expectedMemoryVersion,
        expected_preference_version: expectedPreferenceVersion,
        instruction,
      },
    )
  ).data;
}
