import { apiClient } from './client';
import type {
  PersistentTask,
  PersistentTaskDeleteResponse,
  PersistentTaskDefinitionInput,
  PersistentTaskEligibleTool,
  PersistentTaskState,
  PersistentTaskTrigger,
  PersistentTaskTriggerAdmission,
} from '@/types/persistentTask';

function definitionPayload(input: PersistentTaskDefinitionInput) {
  return {
    title: input.title,
    instruction: input.instruction,
    trigger: input.trigger,
    read_scope: input.readScope,
    action_scope: input.actionScope,
    allowed_tool_names: input.allowedToolNames,
  };
}

export async function listPersistentTasks(): Promise<PersistentTask[]> {
  return (await apiClient.get('/persistent-tasks')).data;
}

export async function listPersistentTaskEligibleTools(): Promise<PersistentTaskEligibleTool[]> {
  return (await apiClient.get('/persistent-tasks/eligible-tools')).data;
}

export async function getPersistentTask(taskId: string): Promise<PersistentTask> {
  return (await apiClient.get(`/persistent-tasks/${encodeURIComponent(taskId)}`)).data;
}

export async function listPersistentTaskTriggers(taskId: string): Promise<PersistentTaskTrigger[]> {
  return (await apiClient.get(`/persistent-tasks/${encodeURIComponent(taskId)}/triggers`)).data;
}

export async function createPersistentTask(
  input: PersistentTaskDefinitionInput,
  operationId: string,
): Promise<PersistentTask> {
  return (
    await apiClient.post('/persistent-tasks', {
      ...definitionPayload(input),
      user_request_identity: `product_ui:${operationId}`,
      user_request_version: '1',
      idempotency_key: operationId,
    })
  ).data;
}

export async function updatePersistentTask(
  task: PersistentTask,
  input: PersistentTaskDefinitionInput,
  operationId: string,
): Promise<PersistentTask> {
  return (
    await apiClient.patch(`/persistent-tasks/${encodeURIComponent(task.id)}`, {
      expected_version: task.version,
      ...definitionPayload(input),
      user_request_identity: `product_ui:${operationId}`,
      user_request_version: String(task.version),
    })
  ).data;
}

export async function changePersistentTaskState(
  task: PersistentTask,
  state: PersistentTaskState,
  operationId: string,
): Promise<PersistentTask> {
  const action = state === 'paused' ? 'pause' : 'resume';
  return (
    await apiClient.post(`/persistent-tasks/${encodeURIComponent(task.id)}/${action}`, {
      expected_version: task.version,
      state,
      user_request_identity: `product_ui:${operationId}`,
      user_request_version: String(task.version),
    })
  ).data;
}

export async function triggerPersistentTask(
  taskId: string,
  summary: string,
  operationId: string,
): Promise<PersistentTaskTriggerAdmission> {
  const now = new Date().toISOString();
  return (
    await apiClient.post(`/persistent-tasks/${encodeURIComponent(taskId)}/trigger`, {
      kind: 'manual',
      occurred_at: now,
      observed_at: now,
      source_identity: `product_ui:${operationId}`,
      source_version: '1',
      summary,
      idempotency_key: operationId,
    })
  ).data;
}

export async function deletePersistentTask(
  task: PersistentTask,
  operationId: string,
): Promise<PersistentTaskDeleteResponse> {
  return (
    await apiClient.delete(`/persistent-tasks/${encodeURIComponent(task.id)}`, {
      data: {
        expected_version: task.version,
        user_request_identity: `product_ui:${operationId}`,
        user_request_version: String(task.version),
      },
    })
  ).data;
}
