import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Bubble } from './Bubble';

describe('Bubble product-object history', () => {
  it('replays the admitted server-resolved label and identity chip', () => {
    render(
      <Bubble
        role="user"
        content="请分析这个岗位"
        blocks={[
          {
            type: 'product_object_reference',
            kind: 'job_opportunity',
            object_id: 'jo_1',
            label: 'Example · Backend Engineer',
          },
          { type: 'text', text: '请分析这个岗位' },
        ]}
      />,
    );
    expect(screen.getByText('Example · Backend Engineer').closest('span[title]')).toHaveAttribute(
      'title',
      'job_opportunity · jo_1',
    );
    expect(screen.getByText('请分析这个岗位')).toBeInTheDocument();
  });

  it('copies only the assistant answer while leaving tool details out', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    render(
      <Bubble
        role="assistant"
        content="最终回答"
        blocks={[
          { type: 'text', text: '我先搜索一下。' },
          { type: 'tool_use', id: 'call-a', name: 'search_jobs', input: { query: 'secret detail' } },
          {
            type: 'tool_result', tool_use_id: 'call-a', is_error: false,
            latency_ms: 5, summary: 'done', content: 'raw tool result',
          },
          { type: 'text', text: '搜索完成，下面给出结论。' },
          { type: 'tool_use', id: 'call-b', name: 'read_profile', input: {} },
          {
            type: 'tool_result', tool_use_id: 'call-b', is_error: false,
            latency_ms: 3, summary: 'done', content: 'profile result',
          },
          { type: 'text', text: '这是最终回答。' },
        ]}
      />,
    );

    expect(screen.getAllByRole('button', { name: /执行过程/ })).toHaveLength(1);
    expect(screen.getByRole('button', { name: /执行过程/ })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('搜索完成，下面给出结论。')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '复制回答' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('这是最终回答。'));
    expect(screen.getByText('已复制')).toBeInTheDocument();
  });
});
