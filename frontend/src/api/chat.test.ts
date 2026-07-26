import { beforeEach, describe, expect, it, vi } from 'vitest';

const { post, authedFetch } = vi.hoisted(() => ({
  post: vi.fn(),
  authedFetch: vi.fn(),
}));

vi.mock('./client', () => ({
  apiClient: { defaults: { baseURL: '/api/v1' }, post },
  authedFetch,
}));

import { streamChatTurn } from './chat';

function event(type: string, data: Record<string, unknown> = {}) {
  return JSON.stringify({ type, data, step: 1, elapsed_ms: 2 });
}

describe('streamChatTurn', () => {
  beforeEach(() => {
    post.mockReset();
    authedFetch.mockReset();
  });

  it('creates a turn and reconnects from the last Redis stream cursor', async () => {
    post.mockResolvedValue({ data: { turn_id: 'turn-1' } });
    authedFetch
      .mockResolvedValueOnce(new Response(`id: 1-0\ndata: ${event('text_delta', { delta: 'A' })}\n\n`))
      .mockResolvedValueOnce(new Response(`id: 2-0\ndata: ${event('done')}\n\n`));
    const deltas: string[] = [];

    await streamChatTurn('session-1', 'hello', {
      onTextDelta: (delta) => deltas.push(delta),
    });

    expect(post).toHaveBeenCalledWith(
      '/chat/session-1/turns',
      { message: 'hello', mode: 'chat' },
      { signal: undefined },
    );
    expect(authedFetch.mock.calls[1][0]).toContain('after=1-0');
    expect(deltas).toEqual(['A']);
  });

  it('can resume an existing turn without submitting a new message', async () => {
    authedFetch.mockResolvedValue(new Response(`data: ${event('done')}\n\n`));
    await streamChatTurn('session-1', '', {}, { turnId: 'existing' });
    expect(post).not.toHaveBeenCalled();
  });
});
