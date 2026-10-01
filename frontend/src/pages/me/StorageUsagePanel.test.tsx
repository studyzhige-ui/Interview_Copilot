import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useAuthStore } from '@/store/authStore';
import { StorageUsagePanel } from './StorageUsagePanel';
const { read } = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock('@/api/storage', () => ({ getStorageUsage: read }));
const usage = { backend: 'filesystem', used_bytes: 2048, asset_count: 2, free_bytes: 1073741824, total_bytes: 2147483648 };
beforeEach(() => { read.mockReset(); useAuthStore.setState({ subjectId: 'storage-owner-a', isAuthed: true }); });
function mount() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><StorageUsagePanel /></QueryClientProvider>); }
it('separates account usage from device-wide capacity', async () => {
  read.mockResolvedValue(usage);
  mount();
  expect(await screen.findByText('2 KiB')).toBeInTheDocument();
  expect(screen.getByText(/存储目录可用空间： 1 GiB/)).toBeInTheDocument();
  expect(screen.getByText(/容器中可能/)).toHaveTextContent('不是整台电脑的物理磁盘空间，也不是账号配额');
  expect(screen.getByText(/新文件保存位置/)).toHaveTextContent('本地文件存储');
});
it('does not call unknown S3 capacity zero or expose local paths', async () => {
  read.mockResolvedValue({ ...usage, backend: 's3', free_bytes: null, total_bytes: null });
  mount();
  expect(await screen.findByText(/对象存储容量由服务商管理/)).toBeInTheDocument();
  expect(screen.queryByText(/存储目录可用空间/)).not.toBeInTheDocument();
});
it('shows failure rather than invented zero usage and supports retry', async () => {
  read.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(usage);
  mount();
  expect(await screen.findByRole('alert')).toHaveTextContent('不能据此判断空间已清零');
  expect(screen.queryByText('0 B')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '刷新存储用量' }));
  expect(await screen.findByText('2 KiB')).toBeInTheDocument();
});
it('does not display another account snapshot during a switch or after logout', async () => {
  read.mockResolvedValueOnce(usage).mockReturnValue(new Promise(() => {}));
  mount();
  expect(await screen.findByText('2 KiB')).toBeInTheDocument();
  act(() => useAuthStore.setState({ subjectId: 'storage-owner-b' }));
  expect(screen.queryByText('2 KiB')).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toBeInTheDocument();
  act(() => useAuthStore.setState({ subjectId: null, isAuthed: false }));
  expect(screen.queryByRole('region', { name: '文件存储' })).not.toBeInTheDocument();
});
