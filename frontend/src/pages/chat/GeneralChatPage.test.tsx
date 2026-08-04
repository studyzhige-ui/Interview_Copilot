import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listChatSessions } from '@/api/chat';
import { GeneralChatPage } from './GeneralChatPage';

vi.mock('@/api/chat', () => ({
  createChatSession: vi.fn(),
  deleteChatSession: vi.fn(),
  listChatSessions: vi.fn(),
  renameChatSession: vi.fn(),
}));

vi.mock('@/pages/review/chat/ChatPanel', () => ({
  ChatPanel: ({ sessionId }: { sessionId: string }) => <div>会话：{sessionId}</div>,
}));

describe('GeneralChatPage', () => {
  beforeEach(() => {
    vi.mocked(listChatSessions).mockReset().mockResolvedValue([
      {
        session_id: 'session-1',
        title: '已有会话',
        type: 'general',
        state_summary: '',
        turn_count: 2,
        updated_at: '2026-08-03T10:00:00',
      },
    ]);
  });

  it('opens the first existing session without requiring a click', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <GeneralChatPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText('会话：session-1')).toBeInTheDocument();
  });
});
