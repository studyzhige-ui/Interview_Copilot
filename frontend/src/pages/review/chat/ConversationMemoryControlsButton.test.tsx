import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  getConversationMemoryControls: vi.fn(),
  updateConversationMemoryControls: vi.fn(),
}));
vi.mock('@/api/personalization', () => api);

import { ConversationMemoryControlsButton } from './ConversationMemoryControlsButton';

function renderButton(sessionId: string | null = 'conversation/1') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ConversationMemoryControlsButton sessionId={sessionId} />
    </QueryClientProvider>,
  );
}

describe('ConversationMemoryControlsButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getConversationMemoryControls.mockResolvedValue({
      conversation_id: 'conversation/1',
      recall_override: null,
      contribution_override: null,
      effective_recall_enabled: true,
      effective_contribution_enabled: false,
      producer_available: true,
      version: 7,
      updated_at: null,
    });
    api.updateConversationMemoryControls.mockResolvedValue({
      conversation_id: 'conversation/1',
      recall_override: false,
      contribution_override: true,
      effective_recall_enabled: false,
      effective_contribution_enabled: true,
      producer_available: true,
      version: 8,
      updated_at: '2026-08-13T00:00:00Z',
    });
  });

  it('writes only nullable usage and contribution overrides to the current Conversation', async () => {
    renderButton();
    const trigger = await screen.findByRole('button', { name: /Memory/ });
    await waitFor(() => expect(trigger).toHaveTextContent('用开/贡关'));
    fireEvent.click(trigger);

    expect(screen.getByText(/不会创建 Conversation、Debrief 或 Project scoped Memory/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('当前对话使用 Memory'), {
      target: { value: 'disabled' },
    });
    fireEvent.change(screen.getByLabelText('当前对话贡献 Memory'), {
      target: { value: 'enabled' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存当前对话控制' }));

    await waitFor(() => expect(api.updateConversationMemoryControls).toHaveBeenCalledWith(
      'conversation/1',
      7,
      false,
      true,
    ));
  });

  it('disables the control when no Conversation is selected', () => {
    renderButton(null);
    expect(screen.getByRole('button', { name: /Memory/ })).toBeDisabled();
    expect(api.getConversationMemoryControls).not.toHaveBeenCalled();
  });

  it('keeps recall independent while blocking an unavailable contribution producer', async () => {
    api.getConversationMemoryControls.mockResolvedValue({
      conversation_id: 'conversation/1',
      recall_override: null,
      contribution_override: null,
      effective_recall_enabled: true,
      effective_contribution_enabled: false,
      producer_available: false,
      version: 0,
      updated_at: null,
    });
    renderButton();
    fireEvent.click(await screen.findByRole('button', { name: /Memory/ }));
    expect(await screen.findByText(/当前部署未启用自动 Memory 生产器/)).toBeInTheDocument();
    const recall = screen.getByLabelText('当前对话使用 Memory');
    const contribution = screen.getByLabelText('当前对话贡献 Memory');
    expect(within(recall).getByRole('option', { name: '仅在当前对话开启' })).toBeEnabled();
    expect(within(contribution).getByRole('option', { name: '仅在当前对话开启' })).toBeDisabled();
  });
});
