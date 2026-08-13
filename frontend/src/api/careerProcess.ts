import { apiClient } from './client';
import type {
  JobOpportunity,
  NextAction,
  NextActionStatus,
  NextActionTimeKind,
  ProcessEvent,
  ProcessEventKind,
} from '@/types/career';

export interface OpportunityCreateInput {
  company_name: string;
  job_title: string;
  entry_reason: 'explicit_tracking' | 'targeted_preparation' | 'user_confirmed_application';
  occurred_at: string;
  source_kind: 'user_assertion';
  source_identity: string;
  source_description: string;
  location?: string;
  team?: string;
  source_url?: string;
  idempotency_key?: string;
  directions?: Array<{ direction_id: string; match_reason: string }>;
}

export async function listJobOpportunities(includeArchived = false): Promise<JobOpportunity[]> {
  return (
    await apiClient.get('/career-process/opportunities', {
      params: { include_archived: includeArchived },
    })
  ).data;
}

export async function createJobOpportunity(input: OpportunityCreateInput): Promise<JobOpportunity> {
  return (await apiClient.post('/career-process/opportunities', input)).data;
}

export async function replaceJobOpportunityDirections(input: {
  opportunityId: string;
  expectedVersion: number;
  sourceIdentity: string;
  directions: Array<{ direction_id: string; match_reason: string }>;
}): Promise<JobOpportunity> {
  return (
    await apiClient.patch(
      `/career-process/opportunities/${encodeURIComponent(input.opportunityId)}/directions`,
      {
        expected_version: input.expectedVersion,
        source_kind: 'user_assertion',
        source_identity: input.sourceIdentity,
        directions: input.directions,
      },
    )
  ).data;
}

export async function listProcessEvents(opportunityId: string): Promise<ProcessEvent[]> {
  return (
    await apiClient.get(`/career-process/opportunities/${encodeURIComponent(opportunityId)}/events`)
  ).data;
}

export async function appendProcessEvent(input: {
  opportunityId: string;
  kind: ProcessEventKind;
  occurredAt: string;
  description: string;
  stepSummary?: string;
  sourceIdentity: string;
  idempotencyKey: string;
}): Promise<ProcessEvent> {
  return (
    await apiClient.post(
      `/career-process/opportunities/${encodeURIComponent(input.opportunityId)}/events`,
      {
        kind: input.kind,
        occurred_at: input.occurredAt,
        source_kind: 'user_assertion',
        source_identity: input.sourceIdentity,
        description: input.description,
        step_summary: input.stepSummary || undefined,
        idempotency_key: input.idempotencyKey,
      },
    )
  ).data;
}

export async function correctProcessEvent(input: {
  opportunityId: string;
  eventId: string;
  kind: ProcessEventKind;
  occurredAt: string;
  description: string;
  stepSummary?: string;
  sourceIdentity: string;
  idempotencyKey: string;
}): Promise<ProcessEvent> {
  return (
    await apiClient.post(
      `/career-process/opportunities/${encodeURIComponent(input.opportunityId)}/events/${encodeURIComponent(input.eventId)}/corrections`,
      {
        replacement_kind: input.kind,
        occurred_at: input.occurredAt,
        source_kind: 'user_assertion',
        source_identity: input.sourceIdentity,
        description: input.description,
        step_summary: input.stepSummary || undefined,
        idempotency_key: input.idempotencyKey,
      },
    )
  ).data;
}

export async function listNextActions(statuses?: NextActionStatus[]): Promise<NextAction[]> {
  return (await apiClient.get('/career-process/next-actions', { params: { statuses } })).data;
}

export interface NextActionCreateInput {
  content: string;
  status: 'suggested' | 'planned';
  time_kind: NextActionTimeKind;
  source_kind: 'user_request';
  source_identity: string;
  job_opportunity_id?: string;
  starts_at?: string;
  ends_at?: string;
  due_at?: string;
  original_time_text?: string;
  source_timezone?: string;
  idempotency_key: string;
}

export async function createNextAction(input: NextActionCreateInput): Promise<NextAction> {
  return (await apiClient.post('/career-process/next-actions', input)).data;
}

export async function transitionNextAction(
  action: NextAction,
  transition: 'plan' | 'complete' | 'close',
  reason?: string,
): Promise<NextAction> {
  return (
    await apiClient.post(`/career-process/next-actions/${encodeURIComponent(action.id)}/${transition}`, {
      source_kind: 'user_assertion',
      source_identity: `ui:${crypto.randomUUID()}`,
      ...(transition === 'close' ? { reason: reason || '用户关闭' } : {}),
    })
  ).data;
}
