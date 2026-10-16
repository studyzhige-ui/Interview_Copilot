import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { useChatStream } from '@/pages/review/chat/useChatStream';
import type { SessionRuntime } from '@/pages/review/chat/types';
import { streamChatTurn, getChatTranscript } from '@/api/chat';

vi.mock('@/api/chat', () => ({ streamChatTurn: vi.fn(), getChatTranscript: vi.fn(), cancelChatTurn: vi.fn(), createChatSubmissionIdentity: vi.fn() }));

it.each([false, true])('refreshes visible business data when the Agent stream ends (connection lost: %s)', async (lost) => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  const queryKey = ['career-workspace', 'jobs'];
  client.setQueryData(queryKey, ['before']);
  let serverJobs = ['before'];
  vi.mocked(streamChatTurn).mockImplementationOnce(async () => {
    serverJobs = ['after committed tool'];
    if (lost) throw new Error('connection lost after write');
    return null;
  });
  vi.mocked(getChatTranscript).mockResolvedValue({ status: 'success', session_id: 'session', type: 'general', turn_count: 1, compaction_cursor: 0, active_turn_id: null, messages: [], total_messages: 0 });
  const runtime: SessionRuntime = { abort: null, turnId: null, messages: [], partial: '', inflightBlocks: [], inflightSources: [], status: '', streaming: false, hidePartialBar: false, loadedHistory: true, interaction: null };
  const { result } = renderHook(() => ({
    jobs: useQuery({ queryKey, queryFn: async () => serverJobs }),
    stream: useChatStream({ activeSessionId: 'session', getRuntime: () => runtime, bump: () => {}, mode: 'AGENT', executionMode: 'standard' }),
  }), { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  expect(result.current.jobs.data).toEqual(['before']);
  act(() => result.current.stream.resumeTurn('turn'));
  await waitFor(() => expect(result.current.jobs.data).toEqual(['after committed tool']));
});
