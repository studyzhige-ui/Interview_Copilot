import type { ConfirmInvitationResult, InvitationFacts, InvitationHandoff } from '@/api/interviewInvitations';
import type { FactConfirmationInteraction } from '@/types/api';
/** Synthetic fixtures: no actual user or employer data. */
export const facts: InvitationFacts = { company_name: '测试公司', job_title: '测试工程师',
  scheduled_start_at: '2026-10-01T14:00:00+08:00', original_time_text: '10月1日14点', source_timezone: 'Asia/Shanghai' };
export const confirmed: ConfirmInvitationResult = { operation_id: 'operation-1', replayed: false,
  opportunity: { kind: 'job_opportunity', id: 'job-1', version: 2 },
  interview: { kind: 'interview_record', id: 'interview-1', version: 1 },
  verification: { id: 'verification-1', operation_id: 'operation-1', conclusion: 'verified' }, projection_invalidations: [] };
export const handoff: InvitationHandoff = { ...facts, opportunity: confirmed.opportunity,
  interview: confirmed.interview, verification: confirmed.verification, source: { kind: 'manual', identity: 'synthetic' } };
export const factInteraction: FactConfirmationInteraction = { id: 'interaction-1', turn_id: 'turn-1',
  tool_call_id: 'tool-1', kind: 'fact_confirmation', schema_version: 1, status: 'pending', version: 3,
  request: { protocol: 'interview_invitation.fact_confirmation.v1', invitation_facts: facts,
    expected_candidate_version: 1, candidate_reference: { kind: 'interview_invitation_candidate', id: 'candidate-1', version: 1 },
    missing_or_uncertain_fields: [], conflicts: [], source_and_evidence_references: [{ kind: 'fixture', identity: 'synthetic' }],
    opportunity_match_options: [{ opportunity_id: 'job-1', expected_version: 2, company_name: '测试公司', job_title: '测试工程师', current_step: '准备' }] } };
