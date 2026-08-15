import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  authorizeExternalPlugin: vi.fn(), authorizeGmailIntegration: vi.fn(),
  getExternalPluginStatus: vi.fn(), getGmailIntegration: vi.fn(),
  revokeExternalPlugin: vi.fn(), revokeGmailIntegration: vi.fn(),
  testExternalPlugin: vi.fn(), testGmailIntegration: vi.fn(),
}));
vi.mock('@/api/integrations', () => api);
vi.mock('@/hooks/useEditionPolicy', () => ({
  useEditionPolicy: () => ({ data: { mcp_transports: ['streamable_http'] } }),
}));

import { CapabilitiesPage } from './CapabilitiesPage';

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><CapabilitiesPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('plugin marketplace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getGmailIntegration.mockResolvedValue({
      provider: 'gmail', adapter_available: true, connection_required: false,
      account: {
        id: 'g1', provider: 'gmail', account_hint: 'a***@gmail.com', scopes: ['gmail.readonly'],
        status: 'active', last_checked_at: null, last_error_code: null, revoked_at: null,
      },
    });
    api.getExternalPluginStatus.mockImplementation(async (provider: 'canva' | 'notion') => ({
      provider, adapter_available: true, connection_required: provider === 'notion',
      account: provider === 'canva' ? {
        id: 'c1', provider: 'canva', account_hint: 'Canva 用户 · abc123',
        scopes: ['design:meta:read'], status: 'active', last_checked_at: null,
        last_error_code: null, revoked_at: null,
      } : null,
    }));
  });

  it('shows real states and manages an account inside the marketplace', async () => {
    renderPage();
    expect((await screen.findAllByText('已连接')).length).toBeGreaterThanOrEqual(2);
    fireEvent.click(screen.getByRole('button', { name: '管理 Gmail 插件' }));
    expect(await screen.findByRole('region', { name: 'Gmail 插件连接' })).toBeInTheDocument();
    expect(screen.getByText('a***@gmail.com')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Canva' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '管理 Canva 插件' })).toBeInTheDocument();
  });

  it('filters by category and keyword', async () => {
    renderPage();
    await screen.findByText('Gmail');
    fireEvent.click(screen.getByRole('button', { name: '设计' }));
    expect(screen.getByRole('heading', { name: 'Canva' })).toBeInTheDocument();
    expect(screen.queryByText('Gmail')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: '搜索插件' }), { target: { value: 'missing' } });
    expect(screen.getByText('没有匹配的插件')).toBeInTheDocument();
  });
});
