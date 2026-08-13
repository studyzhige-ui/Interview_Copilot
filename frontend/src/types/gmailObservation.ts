import type { ProcessEventKind } from './career';

export type GmailObservationStatus =
  | 'unreviewed'
  | 'pending_confirmation'
  | 'applied'
  | 'dismissed'
  | 'retracted';

export interface GmailObservationSnapshot {
  id: string;
  observation_id: string;
  snapshot_version: string;
  provider_history_id: string;
  provider_message_id: string;
  provider_thread_id: string;
  content_available: boolean;
  received_at: string | null;
  from_hint: string;
  subject: string;
  snippet: string;
  content_sha256: string;
  observed_at: string;
  created_at: string;
}

export interface GmailObservation {
  id: string;
  gmail_account_id: string;
  provider_message_id: string;
  provider_thread_id: string;
  received_at: string | null;
  observed_at: string;
  status: GmailObservationStatus;
  version: number;
  candidate_event_kind: ProcessEventKind | null;
  classification_confidence: number | null;
  unique_match: boolean | null;
  analysis_summary: string | null;
  matched_job_opportunity_id: string | null;
  applied_process_event_id: string | null;
  retraction_process_event_id: string | null;
  notification_summary: string | null;
  created_at: string;
  updated_at: string;
  latest_snapshot: GmailObservationSnapshot;
}

export interface GmailObservationNewOpportunity {
  company_name: string;
  job_title: string;
  application_provider: string;
  external_application_id: string;
  external_job_id?: string | null;
  source_url?: string | null;
  location?: string | null;
}

export interface GmailObservationReviewCard {
  id: string;
  persistent_task_id: string;
  observation_id: string;
  source_snapshot_id: string;
  status: 'pending' | 'approved' | 'rejected' | 'skipped';
  version: number;
  candidate_event_kind: ProcessEventKind;
  candidate_opportunity_id: string | null;
  occurred_at: string;
  description: string;
  step_summary: string | null;
  confidence: number;
  unique_match: boolean;
  rationale: string;
  new_opportunity_json: GmailObservationNewOpportunity | null;
  process_event_id: string | null;
  resolution_note: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
  source_snapshot: GmailObservationSnapshot;
}

export interface GmailObservationSyncResult {
  initialized_cursor: boolean;
  cursor_after: string;
  observations_created: number;
  snapshots_created: number;
  triggers_created: number;
  turns_admitted: number;
  turn_ids: string[];
}

export interface GmailObservationResolution {
  outcome: string;
  observation: GmailObservation;
  review_card: GmailObservationReviewCard | null;
  process_event_id: string | null;
}
