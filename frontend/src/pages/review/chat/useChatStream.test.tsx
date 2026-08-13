import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SessionRuntime } from './types';

const { createIdentity, streamChatTurn, toastInfo } = vi.hoisted(() => ({
  createIdentity: vi.fn(),
  streamChatTurn: vi.fn(),
  toastInfo: vi.fn(),
}));

vi.mock('@/api/chat', () => ({
  cancelChatTurn: vi.fn(),
  createChatSubmissionIdentity: createIdentity,
  streamChatTurn,
}));
vi.mock('@/api/client', () => ({
  extractErr: (_error: unknown, fallback: string) => fallback,
}));
vi.mock('@/store/uiStore', () => ({
  toast: { error: vi.fn(), info: toastInfo },
}));

import { useChatStream } from './useChatStream';

function runtime(): SessionRuntime {
  return {
    abort: null,
    turnId: null,
    messages: [],
    partial: '',
    inflightBlocks: [],
    inflightSources: [],
    status: '',
    streaming: false,
    hidePartialBar: false,
    loadedHistory: true,
    interaction: null,
  };
}

describe('useChatStream durable admission', () => {
  beforeEach(() => {
    createIdentity.mockReset().mockReturnValue({
      submissionId: 'submission-1',
      version: 1,
      sourceClientId: 'client-1',
    });
    streamChatTurn.mockReset().mockResolvedValue({
      submission_id: 'submission-1',
      version: 1,
      status: 'queued',
      turn_id: null,
      queue_position: 2,
    });
    toastInfo.mockReset();
  });

  it('creates one identity per Send and refreshes the queue after queued admission', async () => {
    const state = runtime();
    const onQueueChanged = vi.fn();
    const { result } = renderHook(() => useChatStream({
      activeSessionId: 'session-1',
      getRuntime: () => state,
      bump: vi.fn(),
      mode: 'AGENT',
      executionMode: 'auto',
      onQueueChanged,
    }));

    act(() => result.current.sendMessage('hello'));

    expect(createIdentity).toHaveBeenCalledTimes(1);
    expect(streamChatTurn).toHaveBeenCalledWith(
      'session-1',
      'hello',
      expect.any(Object),
      expect.objectContaining({
        mode: 'agent',
        executionMode: 'auto',
        submission: {
          submissionId: 'submission-1',
          version: 1,
          sourceClientId: 'client-1',
        },
      }),
    );
    await waitFor(() => expect(onQueueChanged).toHaveBeenCalledTimes(1));
    expect(state.streaming).toBe(false);
    expect(state.turnId).toBeNull();
    // A queued submission is visible through the durable queue projection,
    // not the chronological transcript.  Claiming it is what creates the
    // authoritative UserMessage/Turn.
    expect(state.messages).toHaveLength(0);
    expect(toastInfo).toHaveBeenCalledWith('消息已排队 · 第 2 位');
  });

  it('refreshes the matching AgentTask after task projection tools finish', () => {
    streamChatTurn.mockReturnValue(new Promise(() => {}));
    const state = runtime();
    const onAgentTaskChanged = vi.fn();
    const { result } = renderHook(() => useChatStream({
      activeSessionId: 'session-1',
      getRuntime: () => state,
      bump: vi.fn(),
      mode: 'AGENT',
      executionMode: 'standard',
      onAgentTaskChanged,
    }));

    act(() => result.current.sendMessage('plan this'));
    const handlers = streamChatTurn.mock.calls[0]?.[2] as {
      onToolDone: (event: {
        tool: string;
        tool_call_id: string;
        result_summary: string;
        result_content: string;
        is_error: boolean;
        tool_latency_ms: number;
      }) => void;
    };
    const options = streamChatTurn.mock.calls[0]?.[3] as {
      onTurnCreated: (turnId: string) => void;
    };

    act(() => {
      options.onTurnCreated('turn-7');
      handlers.onToolDone({
        tool: 'task_update',
        tool_call_id: 'call-1',
        result_summary: 'updated',
        result_content: '{}',
        is_error: false,
        tool_latency_ms: 3,
      });
    });

    expect(onAgentTaskChanged).toHaveBeenCalledWith('session-1', 'turn-7');
  });
});
