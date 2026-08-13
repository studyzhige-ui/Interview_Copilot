import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
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
  ChatPanel: ({ sessionId, fixedMode, productObjectReferences, onProductObjectReferencesConsumed }: {
    sessionId: string;
    fixedMode?: string;
    productObjectReferences?: Array<{ kind: string; object_id: string; label?: string }>;
    onProductObjectReferencesConsumed?: () => void;
  }) => (
    <div>
      会话：{sessionId} · 模式：{fixedMode}
      {productObjectReferences?.map((reference) => (
        <span key={`${reference.kind}:${reference.object_id}`}>
          引用：{reference.kind} · {reference.object_id} · {reference.label}
        </span>
      ))}
      <button onClick={onProductObjectReferencesConsumed}>模拟接纳</button>
    </div>
  ),
}));

function renderPage(initialEntry = '/general-chat') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={queryClient}>
        <GeneralChatPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('GeneralChatPage', () => {
  beforeEach(() => {
    vi.mocked(listChatSessions).mockReset().mockResolvedValue([
      {
        session_id: 'session-1',
        title: '已有会话',
        type: 'general',
        state_summary: '',
        execution_mode: 'standard',
        execution_mode_version: 0,
        turn_count: 2,
        updated_at: '2026-08-03T10:00:00',
      },
    ]);
  });

  it('opens the first existing session without requiring a click', async () => {
    renderPage();

    expect(await screen.findByText('会话：session-1 · 模式：AGENT')).toBeInTheDocument();
  });

  it('restores an explicit object handoff from the URL until admission consumes it', async () => {
    renderPage('/general-chat?object_kind=job_opportunity&object_id=jo_123&object_label=Example%20Backend');

    expect(await screen.findByText(
      '引用：job_opportunity · jo_123 · Example Backend',
    )).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '模拟接纳' }));
    expect(screen.queryByText(
      '引用：job_opportunity · jo_123 · Example Backend',
    )).not.toBeInTheDocument();
  });
});
