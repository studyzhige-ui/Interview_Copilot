import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('./client', () => ({ apiClient: { get } }));

import { readInteractionHistoryRecord, searchInteractionHistory } from './history';

describe('history API', () => {
  beforeEach(() => get.mockReset());

  it('uses repeated FastAPI list parameters and normalizes the query', async () => {
    get.mockResolvedValue({ data: { query: '面试 反馈', count: 0, results: [] } });

    await searchInteractionHistory({
      query: '  面试   反馈  ',
      conversationId: ' conversation-1 ',
      kinds: ['message', 'tool_call'],
      roles: ['user', 'assistant'],
      limit: 30,
    });

    const [, config] = get.mock.calls[0];
    const params = config.params as URLSearchParams;
    expect(get.mock.calls[0][0]).toBe('/history/search');
    expect(params.get('query')).toBe('面试 反馈');
    expect(params.get('conversation_id')).toBe('conversation-1');
    expect(params.getAll('kind')).toEqual(['message', 'tool_call']);
    expect(params.getAll('role')).toEqual(['user', 'assistant']);
    expect(params.get('limit')).toBe('30');
  });

  it('fetches the exact record using an encoded stable identity', async () => {
    get.mockResolvedValue({ data: { identity: 'conversation_message:42' } });

    await readInteractionHistoryRecord('agent_tool_call:turn/1:call 2');

    expect(get).toHaveBeenCalledWith(
      '/history/records/agent_tool_call%3Aturn%2F1%3Acall%202',
    );
  });
});
