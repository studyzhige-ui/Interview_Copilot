import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PersistentTask } from '@/types/persistentTask';

const api = vi.hoisted(() => ({
  changePersistentTaskState: vi.fn(), createPersistentTask: vi.fn(),
  deletePersistentTask: vi.fn(), getPersistentTask: vi.fn(),
  getPersistentTaskDeletionImpact: vi.fn(), listPersistentTasks: vi.fn(),
  listPersistentTaskEligibleTools: vi.fn(), listPersistentTaskTriggers: vi.fn(),
  triggerPersistentTask: vi.fn(), updatePersistentTask: vi.fn(),
}));
const integrationsApi = vi.hoisted(() => ({ getGmailIntegration: vi.fn() }));
vi.mock('@/api/persistentTasks', () => api);
vi.mock('@/api/integrations', () => integrationsApi);
vi.mock('@/api/capabilities', () => ({ listSkills: vi.fn().mockResolvedValue([]) }));
vi.mock('@/api/gmailObservations', () => ({
  listGmailObservations: vi.fn().mockResolvedValue([]),
  listGmailReviewCards: vi.fn().mockResolvedValue([]),
  syncGmailObservations: vi.fn(),
  rebaselineGmailObservations: vi.fn(),
  resolveGmailReviewCard: vi.fn(),
  retractGmailObservation: vi.fn(),
}));
vi.mock('@/api/careerProcess', () => ({ listJobOpportunities: vi.fn().mockResolvedValue([]) }));
vi.mock('@/pages/review/chat/ChatPanel', () => ({ ChatPanel: () => <div>专属对话面板</div> }));

import { PersistentTasksPage } from './PersistentTasksPage';

const task: PersistentTask = {
  id: 'pt-1', user_id: 1, conversation_id: 'conversation-1', title: '跟踪 Agent 岗位',
  instruction: '每天检查符合方向的新岗位并汇报', state: 'active', version: 2,
  trigger_kind: 'scheduled', trigger_spec_json: { kind: 'scheduled', schedule: '0 9 * * 1-5', timezone: 'Asia/Shanghai' },
  read_scope_json: ['public_jobs'], action_scope_json: [], allowed_tool_names_json: ['search_jobs'],
  skill_refs_json: [],
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
      { name: 'read_career_context', description: 'Read career context.' },
      { name: 'read_gmail_observations', description: 'Read admitted Gmail observations.' },
      { name: 'review_gmail_observation', description: 'Review a Gmail observation.' },
    ]);
    integrationsApi.getGmailIntegration.mockResolvedValue({
      provider: 'gmail', adapter_available: true, connection_required: false,
      account: {
        id: 'gmail-1', provider: 'gmail', account_hint: 'a***@gmail.com', scopes: ['gmail.readonly'],
        status: 'active', last_checked_at: null, last_error_code: null,
        history_cursor_updated_at: null,
        last_observation_sync_at: null, last_observation_sync_error_code: null,
        revoked_at: null,
      },
    });
    api.getPersistentTask.mockResolvedValue(task);
    api.listPersistentTaskTriggers.mockResolvedValue([{
      id: 'trigger-1', persistent_task_id: 'pt-1', kind: 'scheduled',
      occurred_at: '2026-08-13T01:00:00Z', observed_at: '2026-08-13T01:00:01Z',
      source_identity: 'scheduler:pt-1', source_version: '2', summary: '工作日岗位检查',
      cursor_after: null, admitted_turn_id: 'turn-1', admitted_at: '2026-08-13T01:00:02Z',
      created_at: '2026-08-13T01:00:01Z',
    }]);
    api.deletePersistentTask.mockResolvedValue({ status: 'success', id: 'pt-1' });
    api.getPersistentTaskDeletionImpact.mockResolvedValue({
      task_id: task.id,
      title: task.title,
      version: task.version,
      pending_trigger_count: 0,
      confirmation_token: 'b'.repeat(64),
      disclosures: ['停止未来调度'],
      conversation: {
        conversation_id: task.conversation_id,
        conversation_type: 'persistent_task',
        title: task.title,
        active_turn_id: null,
        active_turn_status: null,
        pending_submission_count: 0,
        message_count: 1,
        local_attachment_count: 0,
        unpromoted_file_count: 0,
        preserved_debrief_source_count: 0,
        unresolved_external_call_count: 0,
        completed_external_action_count: 0,
        confirmation_token: 'a'.repeat(64),
        disclosures: ['删除专属对话'],
      },
    });
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
    await waitFor(() => expect(api.getPersistentTaskDeletionImpact).toHaveBeenCalledWith('pt-1'));
    const deleteButtons = screen.getAllByRole('button', { name: '删除任务' });
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);
    await waitFor(() => expect(api.deletePersistentTask).toHaveBeenCalledWith(
      task,
      expect.objectContaining({ confirmation_token: 'b'.repeat(64) }),
      expect.any(String),
    ));
  });

  it('offers only the real Gmail event trigger when its connector is available', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '新建持续任务' }));
    expect(screen.getByRole('option', { name: 'Gmail 新邮件事件' })).toBeEnabled();
    expect(await screen.findByText('search_jobs')).toBeInTheDocument();
    expect(api.listPersistentTaskEligibleTools).toHaveBeenCalledTimes(1);
  });
});
