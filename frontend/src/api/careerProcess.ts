import { apiClient } from './client';
import type {
  JobDescriptionSnapshot,
  JobOpportunity,
  JobOpportunityMerge,
  JobOpportunityMergeCandidate,
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

export async function listJobOpportunityMergeCandidates(): Promise<JobOpportunityMergeCandidate[]> {
  return (await apiClient.get('/career-process/opportunity-merge-candidates')).data;
}

export async function listJobOpportunityMerges(includeRetracted = false): Promise<JobOpportunityMerge[]> {
  return (
    await apiClient.get('/career-process/opportunity-merges', {
      params: { include_retracted: includeRetracted },
    })
  ).data;
}

export async function mergeJobOpportunities(input: {
  duplicateOpportunityId: string;
  canonicalOpportunityId: string;
  reason: string;
  operationKey: string;
}): Promise<JobOpportunityMerge> {
  return (
    await apiClient.post('/career-process/opportunity-merges', {
      duplicate_opportunity_id: input.duplicateOpportunityId,
      canonical_opportunity_id: input.canonicalOpportunityId,
      operation_key: input.operationKey,
      reason: input.reason,
    })
  ).data;
}

export async function retractJobOpportunityMerge(input: {
  merge: JobOpportunityMerge;
  reason: string;
  operationKey: string;
}): Promise<JobOpportunityMerge> {
  return (
    await apiClient.post(
      `/career-process/opportunity-merges/${encodeURIComponent(input.merge.id)}/retract`,
      {
        expected_version: input.merge.version,
        operation_key: input.operationKey,
        reason: input.reason,
      },
    )
  ).data;
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
  applicationChannel?: string;
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
        application_channel: input.applicationChannel || undefined,
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
  applicationChannel?: string;
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
        application_channel: input.applicationChannel || undefined,
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
  interview_record_id?: string;
  offer_id?: string;
  artifact_id?: string;
  reminder_at?: string;
  reminder_channel?: 'in_app';
  idempotency_key: string;
}

export async function createNextAction(input: NextActionCreateInput): Promise<NextAction> {
  return (await apiClient.post('/career-process/next-actions', input)).data;
}

export async function editNextAction(input: {
  action: NextAction;
  content: string;
  time_kind: NextActionTimeKind;
  job_opportunity_id?: string;
  interview_record_id?: string;
  offer_id?: string;
  artifact_id?: string;
  starts_at?: string;
  ends_at?: string;
  due_at?: string;
  original_time_text?: string;
  source_timezone?: string;
  reminder_at?: string;
  reminder_channel?: 'in_app';
}): Promise<NextAction> {
  return (
    await apiClient.put(`/career-process/next-actions/${encodeURIComponent(input.action.id)}`, {
      expected_version: input.action.version,
      content: input.content,
      time_kind: input.time_kind,
      job_opportunity_id: input.job_opportunity_id,
      interview_record_id: input.interview_record_id,
      offer_id: input.offer_id,
      artifact_id: input.artifact_id,
      starts_at: input.starts_at,
      ends_at: input.ends_at,
      due_at: input.due_at,
      original_time_text: input.original_time_text,
      source_timezone: input.source_timezone,
      reminder_at: input.reminder_at,
      reminder_channel: input.reminder_channel,
    })
  ).data;
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

export async function listJobDescriptionSnapshots(
  opportunityId: string,
): Promise<JobDescriptionSnapshot[]> {
  return (
    await apiClient.get(
      `/career-process/opportunities/${encodeURIComponent(opportunityId)}/jd-snapshots`,
    )
  ).data;
}

export async function createJobDescriptionSnapshot(
  opportunityId: string,
  input: {
    source_kind: 'typed_product_ui';
    source_identity: string;
    source_version: string;
    original_url: string;
    observed_at: string;
    provider: string;
    canonical_content: string;
    idempotency_key: string;
  },
): Promise<JobDescriptionSnapshot> {
  return (
    await apiClient.post(
      `/career-process/opportunities/${encodeURIComponent(opportunityId)}/jd-snapshots`,
      input,
    )
  ).data;
}
