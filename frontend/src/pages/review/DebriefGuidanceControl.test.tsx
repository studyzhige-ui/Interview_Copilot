import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ getDebriefGuidance: vi.fn(), updateDebriefGuidance: vi.fn() }));
vi.mock('@/api/personalization', () => api);

import { DebriefGuidanceControl } from './DebriefGuidanceControl';

describe('DebriefGuidanceControl', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getDebriefGuidance.mockResolvedValue({
      owner_id: 'interview-1', guidance: null, source_message_id: null, version: 2, updated_at: null,
    });
    api.updateDebriefGuidance.mockResolvedValue({
      owner_id: 'interview-1', guidance: '重点复盘系统设计', source_message_id: null, version: 3, updated_at: null,
    });
  });

  it('writes directly to the InterviewRecord owner without inventing a source message', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><DebriefGuidanceControl interviewId="interview-1" /></QueryClientProvider>);
    fireEvent.click(screen.getByRole('button', { name: '本次复盘指导' }));
    fireEvent.change(await screen.findByLabelText('本次复盘指导'), { target: { value: '重点复盘系统设计' } });
    fireEvent.click(screen.getByRole('button', { name: '保存到本次复盘' }));
    await waitFor(() => expect(api.updateDebriefGuidance).toHaveBeenCalledWith(
      'interview-1', 2, '重点复盘系统设计', null,
    ));
  });
});
