import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ getMemoryPipelineStatus: vi.fn(), getMemoryReceipts: vi.fn(), setMemoryFeedback: vi.fn() }));
vi.mock('@/api/personalization', () => api);
import { MemoryActivity } from './MemoryActivity';

beforeEach(() => {
  vi.clearAllMocks();
  api.getMemoryPipelineStatus.mockResolvedValue({ producer_available: true, extractions: { failed: 1 }, consolidation: null });
  api.getMemoryReceipts.mockResolvedValue([{ id: 'receipt-1', memory_id: 'memory-1', memory_version: 1, cited_at: null, feedback: null, created_at: '2026-09-16T01:00:00Z' }]);
  api.setMemoryFeedback.mockResolvedValue(undefined);
});

function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryActivity memories={[]} /></QueryClientProvider>);
  fireEvent.click(screen.getByText('记忆整理与使用记录'));
}

it('shows processing failure separately from a lack of memories and records explicit feedback', async () => {
  show();
  expect(await screen.findByText(/部分记忆整理失败/)).toBeInTheDocument();
  expect(await screen.findByText(/曾被读取，未确认引用/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '没帮助' }));
  await waitFor(() => expect(api.setMemoryFeedback).toHaveBeenCalledWith('receipt-1', 'unhelpful'));
});

it('does not present a failed status request as an empty successful pipeline', async () => {
  api.getMemoryPipelineStatus.mockRejectedValue(new Error('offline'));
  show();
  expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法读取整理状态');
  expect(screen.queryByText('等待可整理的对话。')).not.toBeInTheDocument();
});
