import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ContentBlock } from '@/types/api';

const getToolCallAudit = vi.hoisted(() => vi.fn());
vi.mock('@/api/chat', () => ({ getToolCallAudit }));

import { BlockChain } from './MessageBlocks';


describe('BlockChain durable Tool identity', () => {
  beforeEach(() => vi.clearAllMocks());

  it('pairs non-adjacent parallel results by call id without orphan cards', () => {
    const blocks: ContentBlock[] = [
      { type: 'tool_use', id: 'call-a', name: 'read_a', input: { target: 'a' } },
      { type: 'tool_use', id: 'call-b', name: 'read_b', input: { target: 'b' } },
      {
        type: 'tool_result', tool_use_id: 'call-b', is_error: false,
        latency_ms: 4, summary: 'B ready', content: 'result B',
      },
      { type: 'text', text: 'parallel calls completed' },
      {
        type: 'tool_result', tool_use_id: 'call-a', is_error: false,
        latency_ms: 7, summary: 'A ready', content: 'result A',
      },
    ];

    render(<BlockChain blocks={blocks} />);

    expect(screen.getByText('read_a')).toBeInTheDocument();
    expect(screen.getByText('read_b')).toBeInTheDocument();
    expect(screen.getByText('· A ready')).toBeInTheDocument();
    expect(screen.getByText('· B ready')).toBeInTheDocument();
    expect(screen.queryByText('(unknown tool)')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('read_a').closest('button')!);
    expect(screen.getByText('result A')).toBeInTheDocument();
  });

  it('loads the deep redacted audit for the same session, turn, and call id', async () => {
    getToolCallAudit.mockResolvedValue({
      call_id: 'call-a', turn_id: 'turn-1', tool_name: 'read_a', effect: 'read',
      status: 'completed', dispatch_generation: 2, policy_decision: 'allow',
      policy_reason: 'read_only', arguments: { token: '[REDACTED]' },
      result: { count: 2 }, error: null, timeout_seconds: 30, duration_ms: 11,
      started_at: '2026-08-13T10:00:00Z', completed_at: '2026-08-13T10:00:00.011Z',
    });
    const blocks: ContentBlock[] = [
      { type: 'tool_use', id: 'call-a', name: 'read_a', input: {} },
      {
        type: 'tool_result', tool_use_id: 'call-a', is_error: false,
        latency_ms: 11, summary: 'done', content: 'two records',
      },
    ];
    render(
      <BlockChain
        blocks={blocks}
        auditRef={{ sessionId: 'session-1', turnId: 'turn-1' }}
      />,
    );

    fireEvent.click(screen.getByText('read_a').closest('button')!);
    fireEvent.click(screen.getByRole('button', { name: '查看执行审计' }));

    await waitFor(() => expect(getToolCallAudit).toHaveBeenCalledWith(
      'session-1', 'turn-1', 'call-a',
    ));
    expect(await screen.findByRole('region', { name: '执行审计 call-a' })).toBeInTheDocument();
    expect(screen.getByText('Policy：allow')).toBeInTheDocument();
  });
});
