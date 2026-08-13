import { beforeEach, describe, expect, it, vi } from 'vitest';

const client = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(),
}));
vi.mock('./client', () => ({ apiClient: client }));

import { getGmailIntegration, revokeGmailIntegration, testGmailIntegration } from './integrations';
import {
  changePersistentTaskState,
  createPersistentTask,
  getPersistentTask,
  listPersistentTaskEligibleTools,
  listPersistentTasks,
  triggerPersistentTask,
  updatePersistentTask,
} from './persistentTasks';
import type { PersistentTask, PersistentTaskDefinitionInput } from '@/types/persistentTask';

const definition: PersistentTaskDefinitionInput = {
  title: '跟踪岗位', instruction: '每天检查新岗位',
  trigger: { kind: 'scheduled', schedule: '0 9 * * 1-5', timezone: 'Asia/Shanghai' },
  readScope: ['public_jobs'], actionScope: [], allowedToolNames: ['search_jobs'],
  skillIds: [],
};

const task = {
  id: 'pt/1', version: 3,
} as PersistentTask;

describe('Stage 4 API clients', () => {
  beforeEach(() => Object.values(client).forEach((mock) => mock.mockReset()));

  it('covers the available PersistentTask definition and state commands with version identity', async () => {
    client.get.mockResolvedValue({ data: [] });
    client.post.mockResolvedValue({ data: task });
    client.patch.mockResolvedValue({ data: task });
    await listPersistentTasks();
    await listPersistentTaskEligibleTools();
    await getPersistentTask('pt/1');
    await createPersistentTask(definition, 'create-1');
    await updatePersistentTask(task, definition, 'update-1');
    await changePersistentTaskState(task, 'paused', 'pause-1');
    expect(client.get).toHaveBeenNthCalledWith(1, '/persistent-tasks');
    expect(client.get).toHaveBeenNthCalledWith(2, '/persistent-tasks/eligible-tools');
    expect(client.get).toHaveBeenNthCalledWith(3, '/persistent-tasks/pt%2F1');
    expect(client.post).toHaveBeenNthCalledWith(1, '/persistent-tasks', expect.objectContaining({
      trigger: definition.trigger, read_scope: ['public_jobs'], allowed_tool_names: ['search_jobs'],
      user_request_identity: 'product_ui:create-1', idempotency_key: 'create-1',
    }));
    expect(client.patch).toHaveBeenCalledWith('/persistent-tasks/pt%2F1', expect.objectContaining({
      expected_version: 3, user_request_identity: 'product_ui:update-1',
    }));
    expect(client.post).toHaveBeenNthCalledWith(2, '/persistent-tasks/pt%2F1/pause', expect.objectContaining({
      expected_version: 3, state: 'paused',
    }));
  });

  it('creates a manual trigger as a distinct intake record', async () => {
    client.post.mockResolvedValue({ data: { status: 'admitted' } });
    await triggerPersistentTask('pt/1', '现在检查', 'trigger-1');
    expect(client.post).toHaveBeenCalledWith('/persistent-tasks/pt%2F1/trigger', expect.objectContaining({
      kind: 'manual', summary: '现在检查', source_identity: 'product_ui:trigger-1', idempotency_key: 'trigger-1',
    }));
  });

  it('uses only the Gmail status, test, and revoke endpoints that actually exist', async () => {
    client.get.mockResolvedValue({ data: { provider: 'gmail', adapter_available: true, connection_required: true, account: null } });
    client.post.mockResolvedValue({ data: { provider: 'gmail', adapter_available: true, connection_required: true, account: null } });
    await getGmailIntegration();
    await testGmailIntegration();
    await revokeGmailIntegration();
    expect(client.get).toHaveBeenCalledWith('/integrations/gmail');
    expect(client.post).toHaveBeenNthCalledWith(1, '/integrations/gmail/test');
    expect(client.post).toHaveBeenNthCalledWith(2, '/integrations/gmail/revoke');
  });
});
