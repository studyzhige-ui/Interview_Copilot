import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listChatSessions, createChatSession } from '@/api/chat';
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
    localStorage.clear();
    vi.mocked(createChatSession).mockReset();
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

  it('opens an explicit session instead of silently choosing the newest one', async () => {
    renderPage('/general-chat?session=older-session');
    expect(await screen.findByText('会话：older-session · 模式：AGENT')).toBeInTheDocument();
  });

  it('starts with an editable draft and reuses the creation identity after failure', async () => {
    vi.mocked(createChatSession).mockRejectedValueOnce(new Error('connection lost')).mockResolvedValueOnce({
      session_id: 'created', title: '一起改好我的简历', type: 'general', execution_mode: 'standard', execution_mode_version: 0,
    });
    renderPage('/general-chat?start=resume');
    fireEvent.click(await screen.findByRole('button', { name: '开始这项准备' }));
    const retry = await screen.findByRole('button', { name: '开始这项准备' });
    fireEvent.click(retry);
    expect(await screen.findByText('会话：created · 模式：AGENT')).toBeInTheDocument();
    expect(createChatSession).toHaveBeenCalledTimes(2);
    expect(vi.mocked(createChatSession).mock.calls[0][0].client_request_id).toBe(vi.mocked(createChatSession).mock.calls[1][0].client_request_id);
    expect(localStorage.getItem('chat-draft:created')).toContain('我想改进简历');
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
