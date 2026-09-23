import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { listCareerActivity } from '@/api/careerActivity';
import { RecentActivity } from './RecentActivity';

vi.mock('@/api/careerActivity', () => ({ listCareerActivity: vi.fn() }));
function show() {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><RecentActivity /></MemoryRouter></QueryClientProvider>);
}
it('separates confirmed facts from pending execution and links the owning conversation', async () => {
  vi.mocked(listCareerActivity).mockResolvedValue([
    { event_id: 'fact', event_category: 'domain', occurred_at: '2026-09-23T00:00:00Z', conversation_id: null, payload: { title: '面试已记录', status: 'confirmed' } },
    { event_id: 'waiting', event_category: 'harness', occurred_at: '2026-09-23T00:00:00Z', conversation_id: 'conv-1', payload: { title: 'Copilot 执行', detail: '等待用户决定', status: 'waiting' } },
  ]);
  show();
  expect(await screen.findByText('等待用户决定')).toBeInTheDocument();
  expect(screen.getByText('面试已记录')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '查看相关对话' })).toHaveAttribute('href', '/chat?session=conv-1');
});
it('does not turn a failed read into an empty state', async () => {
  vi.mocked(listCareerActivity).mockRejectedValue(new Error('offline'));
  show();
  expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法读取');
  expect(screen.queryByText('暂无进展记录。')).not.toBeInTheDocument();
});
