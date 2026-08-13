import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PersistentTask } from '@/types/persistentTask';

const api = vi.hoisted(() => ({
  changePersistentTaskState: vi.fn(), createPersistentTask: vi.fn(),
  deletePersistentTask: vi.fn(), getPersistentTask: vi.fn(), listPersistentTasks: vi.fn(),
  listPersistentTaskEligibleTools: vi.fn(), listPersistentTaskTriggers: vi.fn(),
  triggerPersistentTask: vi.fn(), updatePersistentTask: vi.fn(),
}));
vi.mock('@/api/persistentTasks', () => api);
vi.mock('@/pages/review/chat/ChatPanel', () => ({ ChatPanel: () => <div>专属对话面板</div> }));

import { PersistentTasksPage } from './PersistentTasksPage';

const task: PersistentTask = {
  id: 'pt-1', user_id: 1, conversation_id: 'conversation-1', title: '跟踪 Agent 岗位',
  instruction: '每天检查符合方向的新岗位并汇报', state: 'active', version: 2,
  trigger_kind: 'scheduled', trigger_spec_json: { kind: 'scheduled', schedule: '0 9 * * 1-5', timezone: 'Asia/Shanghai' },
  read_scope_json: ['public_jobs'], action_scope_json: [], allowed_tool_names_json: ['search_jobs'],
  user_request_identity: 'ui:create', user_request_version: '1', compensation_blocked_at: null,
  next_due_at: '2026-08-14T01:00:00Z',
  created_at: '2026-08-12T10:00:00Z', updated_at: '2026-08-13T10:00:00Z',
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MemoryRouter initialEntries={['/persistent-tasks/pt-1']}>
      <QueryClientProvider client={client}>
        <Routes><Route path="/persistent-tasks/:taskId?" element={<PersistentTasksPage />} /></Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('PersistentTasksPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listPersistentTasks.mockResolvedValue([task]);
    api.listPersistentTaskEligibleTools.mockResolvedValue([
      { name: 'search_jobs', description: 'Search real configured job sources.' },
    ]);
    api.getPersistentTask.mockResolvedValue(task);
    api.listPersistentTaskTriggers.mockResolvedValue([{
      id: 'trigger-1', persistent_task_id: 'pt-1', kind: 'scheduled',
      occurred_at: '2026-08-13T01:00:00Z', observed_at: '2026-08-13T01:00:01Z',
      source_identity: 'scheduler:pt-1', source_version: '2', summary: '工作日岗位检查',
      cursor_after: null, admitted_turn_id: 'turn-1', admitted_at: '2026-08-13T01:00:02Z',
      created_at: '2026-08-13T01:00:01Z',
    }]);
    api.deletePersistentTask.mockResolvedValue({ status: 'success', id: 'pt-1' });
    api.triggerPersistentTask.mockResolvedValue({
      trigger_id: 'trigger-1', status: 'admitted', reason: null, turn_id: 'turn-1',
      merged_trigger_ids: [], pending_trigger_count: 0,
    });
  });

  it('shows the real task, dedicated conversation, and retained trigger history', async () => {
    renderPage();
    expect(await screen.findAllByText('跟踪 Agent 岗位')).not.toHaveLength(0);
    expect(screen.getByRole('link', { name: '打开专属对话' })).toHaveAttribute('href', '/persistent-tasks/pt-1/conversation');
    expect(await screen.findByText('工作日岗位检查')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '已接纳为 Turn' })).toHaveAttribute('href', '/persistent-tasks/pt-1/conversation');
    expect(screen.getByRole('button', { name: '删除任务' })).toBeEnabled();
  });

  it('manually triggers through the durable intake endpoint', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '手动运行一次' }));
    fireEvent.change(screen.getByLabelText(/本次触发说明/), { target: { value: '现在检查一次' } });
    fireEvent.click(screen.getByRole('button', { name: '确认运行' }));
    await waitFor(() => expect(api.triggerPersistentTask).toHaveBeenCalledWith('pt-1', '现在检查一次', expect.any(String)));
    expect(await screen.findByText('本次执行已进入专属对话。')).toBeInTheDocument();
  });

  it('deletes the selected version only after explicit confirmation', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '删除任务' }));
    expect(screen.getByText('删除这个持续任务？')).toBeInTheDocument();
    const deleteButtons = screen.getAllByRole('button', { name: '删除任务' });
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);
    await waitFor(() => expect(api.deletePersistentTask).toHaveBeenCalledWith(task, expect.any(String)));
  });

  it('does not offer an event trigger before a real connector event ingress exists', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '新建持续任务' }));
    expect(screen.getByRole('option', { name: '外部事件触发（尚未接入）' })).toBeDisabled();
    expect(await screen.findByText('search_jobs')).toBeInTheDocument();
    expect(api.listPersistentTaskEligibleTools).toHaveBeenCalledTimes(1);
  });
});
