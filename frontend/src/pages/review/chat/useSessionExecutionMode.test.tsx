import type { PropsWithChildren } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getMode, updateMode, toastInfo, toastError } = vi.hoisted(() => ({
  getMode: vi.fn(),
  updateMode: vi.fn(),
  toastInfo: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock('@/api/chat', () => ({
  getChatSessionExecutionMode: getMode,
  updateChatSessionExecutionMode: updateMode,
}));

vi.mock('@/store/uiStore', () => ({
  toast: { info: toastInfo, error: toastError },
}));

import { useSessionExecutionMode } from './useSessionExecutionMode';

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

describe('useSessionExecutionMode', () => {
  beforeEach(() => {
    getMode.mockReset();
    updateMode.mockReset();
    toastInfo.mockReset();
    toastError.mockReset();
    localStorage.clear();
  });

  it('ignores the legacy localStorage value and writes with the server version', async () => {
    localStorage.setItem('execution-mode:conversation-1', 'auto');
    getMode.mockResolvedValue({
      session_id: 'conversation-1', execution_mode: 'standard', version: 3,
    });
    updateMode.mockResolvedValue({
      session_id: 'conversation-1', execution_mode: 'auto', version: 4,
    });
    const { wrapper } = setup();
    const { result } = renderHook(
      () => useSessionExecutionMode('conversation-1'),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.executionMode).toBe('standard');
    await act(async () => { await result.current.setExecutionMode('auto'); });

    expect(updateMode).toHaveBeenCalledWith('conversation-1', 'auto', 3);
    await waitFor(() => expect(result.current.executionMode).toBe('auto'));
    expect(localStorage.getItem('execution-mode:conversation-1')).toBeNull();
  });

  it('rereads the authoritative state after a CAS conflict', async () => {
    getMode
      .mockResolvedValueOnce({
        session_id: 'conversation-1', execution_mode: 'standard', version: 1,
      })
      .mockResolvedValueOnce({
        session_id: 'conversation-1', execution_mode: 'auto', version: 2,
      });
    updateMode.mockRejectedValue({ response: { status: 409 } });
    const { wrapper } = setup();
    const { result } = renderHook(
      () => useSessionExecutionMode('conversation-1'),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isPending).toBe(false));
    await act(async () => { await result.current.setExecutionMode('auto'); });
    await waitFor(() => expect(result.current.executionMode).toBe('auto'));

    expect(getMode).toHaveBeenCalledTimes(2);
    expect(toastInfo).toHaveBeenCalledWith('执行模式已在另一设备更新，已同步最新设置');
    expect(toastError).not.toHaveBeenCalled();
  });
});
