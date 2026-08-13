import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  getAgentMemorySettings: vi.fn(),
  updateAgentMemorySettings: vi.fn(),
  getAgentMemories: vi.fn(),
  getCopilotPreference: vi.fn(),
  updateAgentMemory: vi.fn(),
  invalidateAgentMemory: vi.fn(),
  deleteAgentMemory: vi.fn(),
  promoteAgentMemoryToPreference: vi.fn(),
}));
vi.mock('@/api/personalization', () => api);

import { AgentMemorySettingsSection } from './AgentMemorySettingsSection';
import type { AgentMemory } from '@/types/personalization';

const memory: AgentMemory = {
  id: 'memory/1',
  semantic_key: 'examples-before-theory',
  content: '先给具体例子再解释抽象概念，对用户更有效',
  applicability: '学习陌生技术概念时',
  tags: ['learning', 'examples'],
  valence: 'effective',
  confidence: 0.86,
  status: 'active',
  version: 3,
  formed_at: '2026-08-01T01:00:00Z',
  last_confirmed_at: '2026-08-02T01:00:00Z',
  last_recalled_at: null,
  recall_count: 0,
  status_reason: null,
  invalidated_at: null,
  deleted_at: null,
  created_at: '2026-08-01T01:00:00Z',
  updated_at: '2026-08-02T01:00:00Z',
  sources: [{
    source_turn_identity: 'turn-7',
    source_conversation_identity: 'conversation-2',
    observed_at: '2026-08-01T01:00:00Z',
    source_deleted_at: null,
  }],
};

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AgentMemorySettingsSection />
    </QueryClientProvider>,
  );
}

describe('AgentMemorySettingsSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getAgentMemorySettings.mockResolvedValue({
      recall_enabled: true,
      contribution_enabled: false,
      producer_available: true,
      version: 2,
      updated_at: null,
    });
    api.updateAgentMemorySettings.mockResolvedValue({
      recall_enabled: false,
      contribution_enabled: true,
      producer_available: true,
      version: 3,
      updated_at: '2026-08-13T00:00:00Z',
    });
    api.getAgentMemories.mockResolvedValue([memory]);
    api.getCopilotPreference.mockResolvedValue({
      id: 'preference-1', instructions: ['先给结论'], version: 5, updated_at: null,
    });
    api.updateAgentMemory.mockResolvedValue({ ...memory, version: 4 });
    api.invalidateAgentMemory.mockResolvedValue({
      ...memory,
      version: 4,
      status: 'invalidated',
      status_reason: 'user_invalidated_from_settings',
    });
    api.deleteAgentMemory.mockResolvedValue({
      ...memory,
      version: 4,
      status: 'deleted',
      status_reason: 'user_deleted_from_settings',
    });
    api.promoteAgentMemoryToPreference.mockResolvedValue({
      memory: {
        ...memory,
        version: 4,
        status: 'invalidated',
        status_reason: 'promoted_to_copilot_preference',
      },
      preference: {
        id: 'preference-1',
        instructions: ['先给结论', '在学习陌生技术概念时，先给具体例子再解释抽象概念，对用户更有效'],
        version: 6,
        updated_at: '2026-08-13T00:00:00Z',
      },
    });
  });

  it('edits recall and contribution as independent account controls', async () => {
    renderSection();
    const recall = await screen.findByRole('checkbox', { name: /在未来对话中使用 Memory/ });
    const contribution = screen.getByRole('checkbox', { name: /允许已完成对话贡献 Memory/ });
    expect(recall).toBeChecked();
    expect(contribution).not.toBeChecked();

    fireEvent.click(recall);
    fireEvent.click(contribution);
    fireEvent.click(screen.getByRole('button', { name: '保存 Memory 控制' }));

    await waitFor(() => expect(api.updateAgentMemorySettings).toHaveBeenCalledWith(
      2,
      false,
      true,
    ));
  });

  it('does not present contribution as available when the automatic producer is disabled', async () => {
    api.getAgentMemorySettings.mockResolvedValue({
      recall_enabled: true,
      contribution_enabled: false,
      producer_available: false,
      version: 0,
      updated_at: null,
    });
    renderSection();
    expect(await screen.findByRole('checkbox', { name: /在未来对话中使用 Memory/ })).toBeEnabled();
    expect(screen.getByRole('checkbox', { name: /允许已完成对话贡献 Memory/ })).toBeDisabled();
    expect(screen.getByText(/自动 Memory 生产器当前不可用/)).toBeInTheDocument();
  });

  it('shows canonical Memory content, applicability, exact source identities and lifecycle actions', async () => {
    renderSection();
    expect(await screen.findByText(memory.content)).toBeInTheDocument();
    expect(screen.getByText(/学习陌生技术概念时/)).toBeInTheDocument();
    expect(screen.getByText('Conversation conversation-2')).toBeInTheDocument();
    expect(screen.getByText('Turn turn-7')).toBeInTheDocument();
    expect(screen.getByText('有效')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '失效' }));
    fireEvent.click(screen.getByRole('button', { name: '确认失效' }));
    await waitFor(() => expect(api.invalidateAgentMemory).toHaveBeenCalledWith(
      'memory/1',
      3,
      'user_invalidated_from_settings',
    ));
  });

  it('promotes confirmed wording to CopilotPreference using both owner versions', async () => {
    renderSection();
    await screen.findByText(memory.content);
    const promoteButton = screen.getByRole('button', { name: '晋升为偏好' });
    await waitFor(() => expect(promoteButton).toBeEnabled());
    fireEvent.click(promoteButton);
    expect(await screen.findByText(/避免同一规则从两个所有者重复进入上下文/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认晋升' }));

    await waitFor(() => expect(api.promoteAgentMemoryToPreference).toHaveBeenCalledWith(
      'memory/1',
      3,
      5,
      '在学习陌生技术概念时，先给具体例子再解释抽象概念，对用户更有效',
    ));
  });
});
