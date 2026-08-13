import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ searchInteractionHistory: vi.fn() }));
vi.mock('@/api/history', () => api);

import { HistorySearchPage } from './HistorySearchPage';

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><HistorySearchPage /></QueryClientProvider>);
}

describe('HistorySearchPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.searchInteractionHistory.mockResolvedValue({
      query: '面试反馈',
      count: 2,
      results: [
        {
          kind: 'message', identity: 'message:42', conversation_id: 'conversation-1',
          conversation_title: 'A 公司一面复盘', conversation_type: 'debrief', turn_id: 'turn-1',
          message_id: 42, seq: 7, role: 'user', tool_call_id: null, tool_name: null,
          tool_status: null, occurred_at: '2026-08-13T08:00:00Z', excerpt: '面试官反馈系统设计需要更具体。',
        },
        {
          kind: 'tool_call', identity: 'tool_call:call-9', conversation_id: 'conversation-2',
          conversation_title: '岗位准备', conversation_type: 'general', turn_id: 'turn-2',
          message_id: null, seq: null, role: null, tool_call_id: 'call-9', tool_name: 'read_career_context',
          tool_status: 'completed', occurred_at: '2026-08-13T09:00:00Z', excerpt: '读取已确认的求职档案。',
        },
      ],
    });
  });

  it('shows exact message and ToolCall identities with provenance context', async () => {
    renderPage();
    expect(screen.getByText(/历史记录只说明当时发生过什么/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('搜索内容'), { target: { value: '面试反馈' } });
    fireEvent.click(screen.getByRole('button', { name: '搜索历史' }));

    await waitFor(() => expect(api.searchInteractionHistory).toHaveBeenCalledWith(expect.objectContaining({
      query: '面试反馈', kinds: ['message', 'tool_call'], roles: [], limit: 20,
    })));
    expect(await screen.findByText('面试官反馈系统设计需要更具体。')).toBeInTheDocument();
    expect(screen.getByText('读取已确认的求职档案。')).toBeInTheDocument();
    expect(screen.getByText(/Conversation：A 公司一面复盘/)).toBeInTheDocument();
    expect(screen.getByText(/Conversation：岗位准备/)).toBeInTheDocument();
    expect(screen.getByText('消息 · 用户')).toBeInTheDocument();
    expect(screen.getByText('Tool · read_career_context')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
    expect(screen.getAllByTestId('history-exact-identity').map((node) => node.textContent)).toEqual([
      'message:42', 'tool_call:call-9',
    ]);
    expect(screen.getByText('conversation-1')).toBeInTheDocument();
    expect(screen.getByText('call-9')).toBeInTheDocument();
  });

  it('requires a meaningful query and at least one record kind', async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText('搜索内容'), { target: { value: 'a' } });
    fireEvent.click(screen.getByRole('button', { name: '搜索历史' }));
    expect(screen.getByRole('alert')).toHaveTextContent('至少 2 个字符');
    expect(api.searchInteractionHistory).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('搜索内容'), { target: { value: '反馈' } });
    fireEvent.click(screen.getByText('范围与类型筛选'));
    fireEvent.click(screen.getByLabelText('消息'));
    fireEvent.click(screen.getByLabelText('Tool 调用'));
    fireEvent.click(screen.getByRole('button', { name: '搜索历史' }));
    expect(screen.getByRole('alert')).toHaveTextContent('至少选择一种记录类型');
    expect(api.searchInteractionHistory).not.toHaveBeenCalled();
  });
});
