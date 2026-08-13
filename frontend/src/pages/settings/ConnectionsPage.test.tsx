import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  authorizeGmailIntegration: vi.fn(), getGmailIntegration: vi.fn(),
  revokeGmailIntegration: vi.fn(), testGmailIntegration: vi.fn(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }));
vi.mock('@/api/integrations', () => api);
vi.mock('@/store/uiStore', () => ({ toast }));

import { ConnectionsPage } from './ConnectionsPage';

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ConnectionsPage /></QueryClientProvider>);
}

describe('ConnectionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, '', '/settings/connections');
  });

  it('consumes a successful OAuth return, clears only its safe fields, and rereads status', async () => {
    window.history.replaceState(
      {},
      '',
      '/settings/connections?source=settings&gmail_oauth_outcome=connected#gmail',
    );
    api.getGmailIntegration.mockResolvedValue({
      provider: 'gmail', adapter_available: true, connection_required: false,
      account: {
        id: 'gmail-1', provider: 'gmail', account_hint: 'a***@gmail.com',
        scopes: ['gmail.readonly'], status: 'active', last_checked_at: null,
        last_error_code: null, revoked_at: null,
      },
    });

    renderPage();

    await waitFor(() => expect(api.getGmailIntegration).toHaveBeenCalled());
    expect(toast.success).toHaveBeenCalledWith('Gmail 已连接，可以使用只读检查与搜索。');
    expect(window.location.search).toBe('?source=settings');
    expect(window.location.hash).toBe('#gmail');
    expect(window.location.href).not.toContain('gmail_oauth_outcome');
  });

  it('maps a failed OAuth return to safe copy without reflecting unknown provider text', async () => {
    window.history.replaceState(
      {},
      '',
      '/settings/connections?gmail_oauth_outcome=failed&gmail_oauth_error=oauth_state_expired',
    );
    api.getGmailIntegration.mockResolvedValue({
      provider: 'gmail', adapter_available: true, connection_required: true, account: null,
    });

    renderPage();

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
      'Gmail 授权链接已失效，请重新发起连接。',
    ));
    expect(window.location.search).toBe('');
    expect(window.location.href).not.toContain('oauth_state_expired');
    expect(api.getGmailIntegration).toHaveBeenCalled();
  });

  it('starts the real OAuth handoff and navigates only to the returned URL', async () => {
    api.getGmailIntegration.mockResolvedValue({ provider: 'gmail', adapter_available: true, connection_required: true, account: null });
    api.authorizeGmailIntegration.mockResolvedValue({
      provider: 'gmail', authorization_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=safe',
      expires_in_seconds: 600,
    });
    const replace = vi.fn();
    const popup = {
      opener: window,
      location: { replace },
      close: vi.fn(),
    } as unknown as Window;
    const open = vi.spyOn(window, 'open').mockImplementation(() => popup);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '前往 Google 连接' }));
    await waitFor(() => expect(api.authorizeGmailIntegration).toHaveBeenCalledTimes(1));
    expect(open).toHaveBeenCalledWith(
      'about:blank', 'gmail-oauth', 'popup,width=620,height=760',
    );
    expect(replace).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/v2/auth?state=safe');
    expect(popup.opener).toBeNull();
    open.mockRestore();
  });

  it('honestly disables authorization before click when no Gmail adapter exists', async () => {
    api.getGmailIntegration.mockResolvedValue({ provider: 'gmail', adapter_available: false, connection_required: true, account: null });
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent('当前部署未配置 Gmail Adapter');
    expect(screen.getByRole('button', { name: 'Gmail 尚未配置' })).toBeDisabled();
    expect(api.authorizeGmailIntegration).not.toHaveBeenCalled();
  });

  it('tests an already-bound account through the real status endpoint', async () => {
    const status = {
      provider: 'gmail', adapter_available: true, connection_required: false,
      account: {
        id: 'gmail-1', provider: 'gmail', account_hint: 'a***@gmail.com',
        scopes: ['gmail.readonly'], status: 'active', last_checked_at: null,
        last_error_code: null, revoked_at: null,
      },
    };
    api.getGmailIntegration.mockResolvedValue(status);
    api.testGmailIntegration.mockResolvedValue(status);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '测试真实连接' }));
    await waitFor(() => expect(api.testGmailIntegration).toHaveBeenCalledTimes(1));
    expect(screen.getByText('a***@gmail.com')).toBeInTheDocument();
  });

  it('requires confirmation before revoking the bound grant', async () => {
    const status = {
      provider: 'gmail', adapter_available: true, connection_required: false,
      account: {
        id: 'gmail-1', provider: 'gmail', account_hint: 'a***@gmail.com',
        scopes: ['gmail.readonly'], status: 'active', last_checked_at: null,
        last_error_code: null, revoked_at: null,
      },
    } as const;
    api.getGmailIntegration.mockResolvedValue(status);
    api.revokeGmailIntegration.mockResolvedValue({
      ...status, connection_required: true,
      account: { ...status.account, status: 'revoked', revoked_at: '2026-08-13T00:00:00Z' },
    });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '撤销授权' }));
    expect(api.revokeGmailIntegration).not.toHaveBeenCalled();
    const buttons = screen.getAllByRole('button', { name: '撤销授权' });
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(api.revokeGmailIntegration).toHaveBeenCalledTimes(1));
  });
});
