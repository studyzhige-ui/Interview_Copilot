import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { listCareerActivity } from '@/api/careerActivity';
import { ActivityCenterPage } from './ActivityCenterPage';
vi.mock('@/api/careerActivity', () => ({ listCareerActivity: vi.fn() }));
function mount() { render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><ActivityCenterPage /></MemoryRouter></QueryClientProvider>); }
describe('canonical activity projection', () => {
  it('does not turn an unknown provider outcome into a completed task', async () => {
    vi.mocked(listCareerActivity).mockResolvedValue([{ event_id: 'one', event_kind: 'tool_outcome', event_category: 'harness',
      schema_version: 1, occurred_at: '2026-09-18T00:00:00Z', operation_id: null, conversation_id: 'session-1', interaction_id: null,
      replayable: true, payload: { title: '等待核实外部结果', status: 'unknown' } }]);
    mount(); expect(await screen.findByText('等待核实外部结果')).toBeInTheDocument();
    expect(screen.getByText('执行过程 · unknown')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看原协作' })).toHaveAttribute('href', '/general-chat?session=session-1');
  });
  it('distinguishes query failure from an empty activity history', async () => {
    vi.mocked(listCareerActivity).mockRejectedValue(new Error('offline')); mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('无法读取');
    expect(screen.queryByText('暂时没有活动记录。')).not.toBeInTheDocument();
  });
});
