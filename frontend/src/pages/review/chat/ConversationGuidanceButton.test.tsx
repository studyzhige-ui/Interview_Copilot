import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  getChatTranscript: vi.fn(), getConversationGuidance: vi.fn(), updateConversationGuidance: vi.fn(),
}));
vi.mock('@/api/chat', () => ({ getChatTranscript: api.getChatTranscript }));
vi.mock('@/api/personalization', () => ({
  getConversationGuidance: api.getConversationGuidance,
  updateConversationGuidance: api.updateConversationGuidance,
}));

import { ConversationGuidanceButton } from './ConversationGuidanceButton';

function renderControl() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ConversationGuidanceButton sessionId="conversation-1" /></QueryClientProvider>);
}

describe('ConversationGuidanceButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getConversationGuidance.mockResolvedValue({
      owner_id: 'conversation-1', guidance: null, source_message_id: null, version: 0, updated_at: null,
    });
    api.getChatTranscript.mockResolvedValue({
      status: 'success', session_id: 'conversation-1', type: 'general', turn_count: 2,
      compaction_cursor: 0, active_turn_id: null, total_messages: 3,
      messages: [
        { id: 11, seq: 1, role: 'user', content: '这个对话都先给结论', blocks: [], created_at: null },
        { id: 12, seq: 2, role: 'assistant', content: '好的', blocks: [], created_at: null },
        { id: 19, seq: 3, role: 'user', content: '并且控制篇幅', blocks: [], created_at: null },
      ],
    });
    api.updateConversationGuidance.mockResolvedValue({
      owner_id: 'conversation-1', guidance: '先给结论', source_message_id: 19, version: 1, updated_at: null,
    });
  });

  it('defaults to the latest persisted user message id, never its sequence', async () => {
    renderControl();
    fireEvent.click(screen.getByRole('button', { name: '对话规则' }));
    fireEvent.change(await screen.findByLabelText('当前对话规则'), { target: { value: '先给结论' } });
    expect(screen.getByLabelText('对话规则来源消息')).toHaveValue('19');
    fireEvent.click(screen.getByRole('button', { name: '保存到当前对话' }));
    await waitFor(() => expect(api.updateConversationGuidance).toHaveBeenCalledWith(
      'conversation-1', 0, '先给结论', 19,
    ));
  });

  it('does not allow non-empty guidance when no persisted user source exists', async () => {
    api.getChatTranscript.mockResolvedValue({
      status: 'success', session_id: 'conversation-1', type: 'general', turn_count: 0,
      compaction_cursor: 0, active_turn_id: null, total_messages: 0, messages: [],
    });
    renderControl();
    fireEvent.click(screen.getByRole('button', { name: '对话规则' }));
    fireEvent.change(await screen.findByLabelText('当前对话规则'), { target: { value: '先给结论' } });
    expect(screen.getByRole('button', { name: '保存到当前对话' })).toBeDisabled();
    expect(screen.getByText(/没有已持久化的用户消息/)).toBeInTheDocument();
  });
});
