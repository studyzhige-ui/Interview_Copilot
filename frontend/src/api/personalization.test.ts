import { beforeEach, describe, expect, it, vi } from 'vitest';

const client = vi.hoisted(() => ({
  get: vi.fn(), put: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn(),
}));
vi.mock('./client', () => ({ apiClient: client }));

import {
  getConversationGuidance,
  getConversationMemoryControls,
  getCopilotPreference,
  getDebriefGuidance,
  getAgentMemories,
  getAgentMemorySettings,
  deleteAgentMemory,
  invalidateAgentMemory,
  promoteAgentMemoryToPreference,
  updateAgentMemory,
  updateAgentMemorySettings,
  updateConversationGuidance,
  updateConversationMemoryControls,
  updateCopilotPreference,
  updateDebriefGuidance,
} from './personalization';

describe('personalization API owners', () => {
  beforeEach(() => Object.values(client).forEach((mock) => mock.mockReset().mockResolvedValue({ data: {} })));

  it('keeps global preference on its explicit endpoint', async () => {
    await getCopilotPreference();
    await updateCopilotPreference(3, ['先给结论']);
    expect(client.get).toHaveBeenCalledWith('/personalization/copilot-preference');
    expect(client.put).toHaveBeenCalledWith('/personalization/copilot-preference', {
      expected_version: 3,
      instructions: ['先给结论'],
    });
  });

  it('keeps Conversation guidance and its real source message together', async () => {
    await getConversationGuidance('conversation/1');
    await updateConversationGuidance('conversation/1', 2, '只在这里简短回答', 42);
    expect(client.get).toHaveBeenCalledWith('/personalization/conversations/conversation%2F1/guidance');
    expect(client.put).toHaveBeenCalledWith(
      '/personalization/conversations/conversation%2F1/guidance',
      { expected_version: 2, guidance: '只在这里简短回答', source_message_id: 42 },
    );
  });

  it('keeps Debrief guidance on the InterviewRecord owner', async () => {
    await getDebriefGuidance('interview/1');
    await updateDebriefGuidance('interview/1', 1, '重点复盘系统设计');
    expect(client.get).toHaveBeenCalledWith('/personalization/interviews/interview%2F1/guidance');
    expect(client.put).toHaveBeenCalledWith(
      '/personalization/interviews/interview%2F1/guidance',
      { expected_version: 1, guidance: '重点复盘系统设计', source_message_id: null },
    );
  });


  it('keeps account Memory recall and contribution as independent controls', async () => {
    await getAgentMemorySettings();
    await updateAgentMemorySettings(2, false, true);
    expect(client.get).toHaveBeenCalledWith('/personalization/memory-settings');
    expect(client.put).toHaveBeenCalledWith('/personalization/memory-settings', {
      expected_version: 2,
      recall_enabled: false,
      contribution_enabled: true,
    });
  });

  it('stores only nullable Memory usage overrides on the Conversation', async () => {
    await getConversationMemoryControls('conversation/1');
    await updateConversationMemoryControls('conversation/1', 3, null, false);
    expect(client.get).toHaveBeenCalledWith(
      '/personalization/conversations/conversation%2F1/memory-controls',
    );
    expect(client.put).toHaveBeenCalledWith(
      '/personalization/conversations/conversation%2F1/memory-controls',
      { expected_version: 3, recall_override: null, contribution_override: false },
    );
  });

  it('uses the canonical user-level Memory lifecycle endpoints', async () => {
    await getAgentMemories(true, 50);
    await updateAgentMemory('memory/1', 1, '先给例子有帮助', '学习新概念时', ['learning']);
    await invalidateAgentMemory('memory/1', 2, 'user_invalidated_from_settings');
    await deleteAgentMemory('memory/1', 3, 'user_deleted_from_settings');
    await promoteAgentMemoryToPreference('memory/1', 4, 5, '学习新概念时先给例子');

    expect(client.get).toHaveBeenCalledWith('/personalization/memories', {
      params: { include_inactive: true, limit: 50 },
    });
    expect(client.patch).toHaveBeenCalledWith('/personalization/memories/memory%2F1', {
      expected_version: 1,
      content: '先给例子有帮助',
      applicability: '学习新概念时',
      tags: ['learning'],
    });
    expect(client.post).toHaveBeenNthCalledWith(
      1,
      '/personalization/memories/memory%2F1/invalidate',
      { expected_version: 2, reason: 'user_invalidated_from_settings' },
    );
    expect(client.delete).toHaveBeenCalledWith('/personalization/memories/memory%2F1', {
      data: { expected_version: 3, reason: 'user_deleted_from_settings' },
    });
    expect(client.post).toHaveBeenNthCalledWith(
      2,
      '/personalization/memories/memory%2F1/promote-to-preference',
      {
        expected_memory_version: 4,
        expected_preference_version: 5,
        instruction: '学习新概念时先给例子',
      },
    );
  });
});
