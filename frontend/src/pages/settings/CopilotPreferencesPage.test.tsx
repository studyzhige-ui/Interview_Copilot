import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ getCopilotPreference: vi.fn(), updateCopilotPreference: vi.fn() }));
const authApi = vi.hoisted(() => ({ getMe: vi.fn(), updateMe: vi.fn() }));
vi.mock('@/api/personalization', () => api);
vi.mock('@/api/auth', () => authApi);

import { CopilotPreferencesPage } from './CopilotPreferencesPage';

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><CopilotPreferencesPage /></QueryClientProvider>);
}

describe('CopilotPreferencesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getCopilotPreference.mockResolvedValue({
      id: 'preference-1', instructions: ['先给结论'], version: 4, updated_at: null,
    });
    api.updateCopilotPreference.mockResolvedValue({
      id: 'preference-1', instructions: ['先给结论', '保留多行\n规则'], version: 5, updated_at: null,
    });
    authApi.getMe.mockResolvedValue({
      username: 'alice', email: 'alice@example.com', nickname: null, avatar_url: null,
      bio: null, default_execution_mode: 'standard', email_verified: true,
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    });
    authApi.updateMe.mockResolvedValue({
      username: 'alice', email: 'alice@example.com', nickname: null, avatar_url: null,
      bio: null, default_execution_mode: 'auto', email_verified: true,
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-13T00:00:00Z',
    });
  });

  it('edits global rules as independent values so one instruction may contain newlines', async () => {
    renderPage();
    expect(await screen.findByDisplayValue('先给结论')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '添加规则' }));
    fireEvent.change(screen.getByLabelText('全局协作规则 2'), { target: { value: '保留多行\n规则' } });
    fireEvent.click(screen.getByRole('button', { name: '保存全局规则' }));
    await waitFor(() => expect(api.updateCopilotPreference).toHaveBeenCalledWith(
      4,
      ['先给结论', '保留多行\n规则'],
    ));
  });

  it('saves the server-owned default for newly created conversations', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('radio', { name: /Auto/ }));
    fireEvent.click(screen.getByRole('button', { name: '保存默认模式' }));
    await waitFor(() => expect(authApi.updateMe).toHaveBeenCalledWith({
      default_execution_mode: 'auto',
    }));
    expect(screen.getByText(/当前对话仍可在聊天工具栏单独切换/)).toBeInTheDocument();
  });
});
