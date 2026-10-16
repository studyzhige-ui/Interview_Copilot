import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { CopilotPreferencesPage } from '@/pages/settings/CopilotPreferencesPage';
import { getMe } from '@/api/auth';
import { getAgentMemories, getAgentMemorySettings, getMemoryPipelineStatus, getMemoryReceipts, updateAgentMemorySettings } from '@/api/personalization';

vi.mock('@/api/auth', async (original) => ({ ...await original<typeof import('@/api/auth')>(), getMe: vi.fn() }));
vi.mock('@/api/personalization', async (original) => ({
  ...await original<typeof import('@/api/personalization')>(),
  getAgentMemories: vi.fn().mockResolvedValue([]), getAgentMemorySettings: vi.fn(),
  updateAgentMemorySettings: vi.fn(), getMemoryPipelineStatus: vi.fn().mockResolvedValue({ extractions: {}, consolidation: null, producer_available: true }),
  getMemoryReceipts: vi.fn().mockResolvedValue([]),
}));
const settings = { version: 7, recall_enabled: true, contribution_enabled: false, producer_available: true, updated_at: null };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAgentMemorySettings).mockResolvedValue(settings);
  vi.mocked(updateAgentMemorySettings).mockResolvedValue({ ...settings, contribution_enabled: true, version: 8 });
});
function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={['/settings/personalization?view=memory']}><CopilotPreferencesPage /></MemoryRouter>
  </QueryClientProvider>);
}

it('opens the memory view directly and keeps use/contribution controls independent', async () => {
  show();
  const contribution = await screen.findByRole('checkbox', { name: /允许已完成对话贡献/ });
  expect(getMe).not.toHaveBeenCalled();
  expect(getAgentMemories).toHaveBeenCalledWith(true);
  expect(screen.queryByRole('heading', { name: '全局协作偏好' })).not.toBeInTheDocument();
  fireEvent.click(contribution);
  fireEvent.click(screen.getByRole('button', { name: '保存 Memory 控制' }));
  await waitFor(() => expect(updateAgentMemorySettings).toHaveBeenCalledWith(7, true, true));
  await waitFor(() => expect(screen.getByRole('button', { name: '保存 Memory 控制' })).toBeDisabled());
});

it('loads processing and usage history only when the user opens that detail', async () => {
  show();
  await screen.findByRole('checkbox', { name: /允许已完成对话贡献/ });
  expect(getMemoryPipelineStatus).not.toHaveBeenCalled();
  expect(getMemoryReceipts).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('记忆整理与使用记录'));
  await waitFor(() => expect(getMemoryPipelineStatus).toHaveBeenCalledOnce());
  expect(getMemoryReceipts).toHaveBeenCalledOnce();
});
