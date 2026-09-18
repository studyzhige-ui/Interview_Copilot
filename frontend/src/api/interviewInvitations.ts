/** VS-01 transport only. All writes go through the existing shared Operation. */
import { apiClient } from './client';
import type { AgentInteraction } from '@/types/api';

export interface InvitationFacts {
  company_name: string; job_title: string; scheduled_start_at: string;
  original_time_text: string; source_timezone: string;
  scheduled_end_at?: string | null; stage_label?: string | null;
  location?: string | null; meeting_url?: string | null;
  contact_name?: string | null; contact_email?: string | null;
}
export interface ObjectReference { kind: string; id: string; version: number | null }
export interface OperationVerification {
  id: string; operation_id: string;
  conclusion: 'pending' | 'verified' | 'failed' | 'unknown' | 'reconciled';
}
export type OpportunityResolution = { kind: 'create_new' }
  | { kind: 'link_existing'; opportunity_id: string; expected_version: number };
export interface ConfirmInvitationCommand {
  schema_version: 1; idempotency_key: string; actor_kind: 'user'; asserted_at: string;
  confirmation_basis: { kind: 'explicit_user_assertion'; source: { kind: 'manual'; identity: string } };
  facts: InvitationFacts; opportunity: OpportunityResolution;
}
export interface ConfirmInvitationResult {
  operation_id: string; replayed: boolean;
  opportunity: ObjectReference; interview: ObjectReference;
  verification: OperationVerification; projection_invalidations: string[];
}
export interface InvitationHandoff extends InvitationFacts {
  opportunity: ObjectReference; interview: ObjectReference;
  verification: OperationVerification;
  source: { kind: string; identity: string; version?: string | null };
}
export interface PendingConfirmation {
  conversation_id: string; turn_status: string; interaction: AgentInteraction;
}
export async function confirmInvitation(command: ConfirmInvitationCommand): Promise<ConfirmInvitationResult> {
  return (await apiClient.post('/career/interview-invitations/confirm', command)).data;
}
export async function listInvitationHandoffs(): Promise<InvitationHandoff[]> {
  return (await apiClient.get('/career/interview-invitations/interviews')).data;
}
export async function getInvitationHandoff(id: string): Promise<InvitationHandoff> {
  return (await apiClient.get(`/career/interview-invitations/interviews/${encodeURIComponent(id)}/handoff`)).data;
}
export async function listPendingConfirmations(): Promise<PendingConfirmation[]> {
  return (await apiClient.get('/interactions/pending-confirmations')).data;
}

export interface InvitationSubmissionReceipt {
  status: 'not_received' | 'pending' | 'committed' | 'rejected' | 'cancelled';
  idempotency_key: string;
  result: ConfirmInvitationResult | null;
  command: ConfirmInvitationCommand | null;
}
export async function getInvitationSubmission(key: string): Promise<InvitationSubmissionReceipt> {
  return (await apiClient.get('/career/interview-invitations/submissions/receipt', {
    params: { idempotency_key: key },
  })).data;
}
export async function resumeInvitationSubmission(key: string): Promise<ConfirmInvitationResult> {
  return (await apiClient.post('/career/interview-invitations/submissions/resume', { idempotency_key: key })).data;
}
export async function cancelInvitationSubmission(key: string): Promise<InvitationSubmissionReceipt> {
  return (await apiClient.post('/career/interview-invitations/submissions/cancel', { idempotency_key: key })).data;
}
