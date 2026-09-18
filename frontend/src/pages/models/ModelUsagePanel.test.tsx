import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, act } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useAuthStore } from '@/store/authStore';
import { ModelUsagePanel } from './ModelUsagePanel';
const read = vi.hoisted(() => vi.fn());
vi.mock('@/api/workspace', () => ({ getPrimaryModelUsage: read }));
beforeEach(() => { read.mockReset(); useAuthStore.setState({ subjectId: 'owner-a', isAuthed: true }); });
function mount() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ModelUsagePanel /></QueryClientProvider>); }
it('reports server-held reservations with their limited accounting scope', async () => {
  read.mockResolvedValue({ scope: 'primary_chat_agent', unit: 'logical_tokens_not_currency', window_date: '2026-09-19', timezone: 'UTC', call_limit: 500, token_limit: 2000000, calls_admitted: 4, tokens_used: 125, tokens_reserved: 10000, excluded: [] });
  mount();
  expect(await screen.findByText(/已准入 4/)).toBeInTheDocument();
  expect(screen.getByText(/这不是供应商账单/)).toBeInTheDocument();
  expect(screen.getByText(/预留 10,000/)).toBeInTheDocument();
  act(() => { useAuthStore.setState({ subjectId: null, isAuthed: false }); });
  expect(screen.queryByText(/已准入 4/)).not.toBeInTheDocument();
});
it('does not manufacture zero usage when the server is unavailable', async () => {
  read.mockRejectedValue(new Error('offline'));
  mount();
  expect(await screen.findByRole('alert')).toHaveTextContent('不能据此认为额度已清零');
  expect(screen.queryByText(/已准入 0/)).not.toBeInTheDocument();
});
