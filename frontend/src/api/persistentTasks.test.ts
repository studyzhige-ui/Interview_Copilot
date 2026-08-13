import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PersistentTask, PersistentTaskDeletionImpact } from '@/types/persistentTask';

const { get, del } = vi.hoisted(() => ({ get: vi.fn(), del: vi.fn() }));

vi.mock('./client', () => ({
  apiClient: { get, delete: del },
}));

import {
  deletePersistentTask,
  listPersistentTaskEligibleTools,
  listPersistentTaskTriggers,
} from './persistentTasks';

const task: PersistentTask = {
  id: 'task/with space', user_id: 1, conversation_id: 'conversation-1', title: '岗位跟踪',
  instruction: '检查岗位', state: 'paused', version: 7, trigger_kind: 'scheduled',
  trigger_spec_json: { kind: 'scheduled', schedule: '0 9 * * 1-5', timezone: 'Asia/Shanghai' },
  read_scope_json: [], action_scope_json: [], allowed_tool_names_json: ['search_jobs'],
  skill_refs_json: [],
  user_request_identity: 'product_ui:create', user_request_version: '1', compensation_blocked_at: null,
  next_due_at: null, created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-13T00:00:00Z',
};

const deletionImpact: PersistentTaskDeletionImpact = {
  task_id: task.id,
  title: task.title,
  version: task.version,
  pending_trigger_count: 1,
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
};

describe('persistentTasks API', () => {
  beforeEach(() => {
    get.mockReset();
    del.mockReset();
  });

  it('reads retained triggers from the task-owned endpoint', async () => {
    get.mockResolvedValue({ data: [{ id: 'trigger-1' }] });
    await expect(listPersistentTaskTriggers(task.id)).resolves.toEqual([{ id: 'trigger-1' }]);
    expect(get).toHaveBeenCalledWith('/persistent-tasks/task%2Fwith%20space/triggers');
  });

  it('reads the current server-owned unattended Tool catalog', async () => {
    get.mockResolvedValue({ data: [{ name: 'search_jobs', description: 'Search jobs.' }] });
    await expect(listPersistentTaskEligibleTools()).resolves.toEqual([
      { name: 'search_jobs', description: 'Search jobs.' },
    ]);
    expect(get).toHaveBeenCalledWith('/persistent-tasks/eligible-tools');
  });

  it('sends the selected task version as the delete CAS', async () => {
    del.mockResolvedValue({ data: { status: 'success', id: task.id } });
    await expect(deletePersistentTask(task, deletionImpact, 'operation-1')).resolves.toEqual({
      status: 'success', id: task.id,
    });
    expect(del).toHaveBeenCalledWith('/persistent-tasks/task%2Fwith%20space', {
      data: {
        expected_version: 7,
        user_request_identity: 'product_ui:operation-1',
        user_request_version: '7',
        confirmation_token: 'b'.repeat(64),
        confirm_task_id: task.id,
      },
    });
  });
});
