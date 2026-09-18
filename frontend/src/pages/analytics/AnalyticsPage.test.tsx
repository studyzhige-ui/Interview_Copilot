import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { expect, it, vi } from 'vitest';
import { getAnalyticsReport } from '@/api/interview';
import { AnalyticsPage } from './AnalyticsPage';

vi.mock('@/api/interview', () => ({ getAnalyticsReport: vi.fn().mockResolvedValue({ status: 'empty', message: '暂无能力状态数据' }) }));

it('deduplicates strict-mode loading and reuses fresh data on return', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30000 } } });
  const page = <StrictMode><QueryClientProvider client={client}><AnalyticsPage /></QueryClientProvider></StrictMode>;
  const first = render(page);
  expect(await screen.findByText('暂无能力状态数据')).toBeInTheDocument();
  first.unmount();
  render(page);
  expect(screen.getByText('暂无能力状态数据')).toBeInTheDocument();
  expect(getAnalyticsReport).toHaveBeenCalledOnce();
});
