import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
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
});
