import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useAuthStore } from '@/store/authStore';
import { ModelUsagePanel } from './ModelUsagePanel';
const { read, history } = vi.hoisted(() => ({ read: vi.fn(), history: vi.fn() }));
vi.mock('@/api/usage', () => ({ getAccountUsage: read, getUsageReceipts: history }));
beforeEach(() => { read.mockReset(); history.mockReset(); useAuthStore.setState({ subjectId: 'owner-a', isAuthed: true }); });
const snapshot = { scope: 'account_consumption', unit: 'logical_tokens_and_resource_units', window_date: '2026-09-19', timezone: 'UTC', call_limit: 500, token_limit: 2000000, calls_admitted: 4, tokens_used: 125, tokens_reserved: 10000, currency: 'USD', cost_limit_micros: null, rated_cost_used_micros: '1000001', rated_cost_reserved_micros: '2000000', unpriced_requests: 1, unresolved_all_dates: 2, invoice_reconciled_requests: 0, unit_limits: { audio_ms: 100000 }, units_used: {}, units_reserved: {}, excluded: [] };
function mount() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ModelUsagePanel /></QueryClientProvider>); }
it('reports every category with unknown price distinct from free and invoice', async () => {
  read.mockResolvedValue(snapshot);
  mount();
  expect(await screen.findByText(/已准入 4/)).toBeInTheDocument();
  expect(screen.getByText(/这不是供应商账单/)).toBeInTheDocument();
  expect(screen.getByText(/预留 10,000/)).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('不是免费');
  expect(screen.getByText(/已计价 1.000001/)).toBeInTheDocument();
  expect(history).not.toHaveBeenCalled();
  act(() => { useAuthStore.setState({ subjectId: null, isAuthed: false }); });
  expect(screen.queryByText(/已准入 4/)).not.toBeInTheDocument();
});
it('does not manufacture zero usage when the server is unavailable', async () => {
  read.mockRejectedValue(new Error('offline'));
  mount();
  expect(await screen.findByRole('alert')).toHaveTextContent('不能据此认为额度已清零');
  expect(screen.queryByText(/已准入 0/)).not.toBeInTheDocument();
});
it('keeps the receipt original currency and distinguishes unknown outcome', async () => {
  read.mockResolvedValue(snapshot);
  history.mockResolvedValue({ items: [{ id: 'receipt-old', date: '2026-09-18', currency: 'CNY', meter: 'embedding', model: 'model', status: 'unknown', cost_basis: 'rated_estimate', cost_reserved_micros: '1000001', cost_observed_micros: null }], next_cursor: null });
  mount();
  fireEvent.click(await screen.findByText('查看调用记录'));
  expect(await screen.findByText('1.000001 CNY')).toBeInTheDocument();
  expect(screen.getByText('结果未知')).toBeInTheDocument();
  expect(screen.getByText('更早记录')).toBeDisabled();
});
