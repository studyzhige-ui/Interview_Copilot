import { beforeEach, describe, expect, it, vi } from 'vitest';

const client = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock('./client', () => ({ apiClient: client }));

import {
  getConversationGuidance,
  getCopilotPreference,
  getDebriefGuidance,
  updateConversationGuidance,
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
});
