import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  authorizeExternalPlugin: vi.fn(), authorizeGmailIntegration: vi.fn(),
  getExternalPluginStatus: vi.fn(), getGmailIntegration: vi.fn(),
  revokeExternalPlugin: vi.fn(), revokeGmailIntegration: vi.fn(),
  testExternalPlugin: vi.fn(), testGmailIntegration: vi.fn(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('@/api/integrations', () => api);
vi.mock('@/store/uiStore', () => ({ toast }));

import { PluginConnectionPanel } from './PluginConnectionPanel';

function renderPanel(provider: 'gmail' | 'canva' | 'notion') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><PluginConnectionPanel provider={provider} onClose={vi.fn()} /></QueryClientProvider>);
}

describe('PluginConnectionPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, '', '/plugins');
  });

  it('starts Canva OAuth directly inside the plugin marketplace', async () => {
    api.getExternalPluginStatus.mockResolvedValue({ provider: 'canva', adapter_available: true, connection_required: true, account: null });
    api.authorizeExternalPlugin.mockResolvedValue({ provider: 'canva', authorization_url: 'https://www.canva.com/api/oauth/authorize?state=safe', expires_in_seconds: 600 });
    const replace = vi.fn();
    const popup = { opener: window, location: { replace }, close: vi.fn() } as unknown as Window;
    const open = vi.spyOn(window, 'open').mockReturnValue(popup);
    renderPanel('canva');
    fireEvent.click(await screen.findByRole('button', { name: '前往 Canva 连接' }));
    await waitFor(() => expect(api.authorizeExternalPlugin).toHaveBeenCalledWith('canva'));
    expect(replace).toHaveBeenCalledWith('https://www.canva.com/api/oauth/authorize?state=safe');
    expect(popup.opener).toBeNull();
    open.mockRestore();
  });

  it('shows an actionable Notion deployment checklist when OAuth is absent', async () => {
    api.getExternalPluginStatus.mockResolvedValue({ provider: 'notion', adapter_available: false, connection_required: true, account: null });
    renderPanel('notion');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('先完成一次部署配置，再连接个人账号');
    expect(alert).toHaveTextContent('NOTION_OAUTH_CLIENT_ID');
    expect(alert).toHaveTextContent('/integrations/plugins/notion/callback');
    expect(screen.getByRole('link', { name: '打开 Notion Creator Dashboard' })).toHaveAttribute('href', 'https://www.notion.so/profile/integrations');
    expect(screen.queryByRole('button', { name: 'Notion 尚未配置' })).not.toBeInTheDocument();
  });

  it('consumes only bounded provider OAuth return fields', async () => {
    window.history.replaceState({}, '', '/plugins?keep=1&plugin_oauth_provider=notion&plugin_oauth_outcome=failed&plugin_oauth_error=oauth_state_expired#market');
    api.getExternalPluginStatus.mockResolvedValue({ provider: 'notion', adapter_available: true, connection_required: true, account: null });
    renderPanel('notion');
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('授权链接已失效，请重新发起连接。'));
    expect(window.location.search).toBe('?keep=1');
    expect(window.location.hash).toBe('#market');
  });
});
