import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AgentTaskCard } from './AgentTaskCard';

describe('AgentTaskCard', () => {
  it('renders one flat ordered plan without inventing waiting or tool-log phases', () => {
    render(<AgentTaskCard task={{
      id: 'at-1', turn_id: 'turn-1', objective: '比较两个岗位并给出建议',
      completion_conditions: ['完成比较'], version: 2,
      created_at: '2026-08-13T10:00:00Z', updated_at: '2026-08-13T10:01:00Z', frozen_at: null,
      phases: [
        { id: 'collect', title: '读取岗位事实', status: 'completed', result_refs: [] },
        { id: 'compare', title: '逐项比较', status: 'in_progress', result_refs: [] },
        { id: 'deliver', title: '形成建议', status: 'pending', result_refs: [] },
      ],
    }} />);
    expect(screen.getByRole('region', { name: '当前执行计划' })).toBeInTheDocument();
    expect(screen.getByText('比较两个岗位并给出建议')).toBeInTheDocument();
    expect(screen.getByText('逐项比较')).toBeInTheDocument();
    expect(screen.getByText('形成建议')).toBeInTheDocument();
    expect(screen.queryByText('读取岗位事实')).not.toBeInTheDocument();
    expect(screen.getByText('1/3 阶段')).toBeInTheDocument();
    expect(screen.queryByText('等待审批')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看全部 3 个阶段' }));
    expect(screen.getByText('读取岗位事实')).toBeInTheDocument();
  });
});
