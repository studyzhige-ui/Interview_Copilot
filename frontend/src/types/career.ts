export type DirectionLifecycle = 'exploring' | 'active' | 'paused' | 'archived';

export interface ConfirmationInput {
  kind: 'user_edit' | 'conversation_message';
  source_message_id?: number | null;
}

interface DatedFact {
  start_date?: string | null;
  end_date?: string | null;
}

export type PersonalFact =
  | (DatedFact & {
      kind: 'education';
      institution: string;
      degree?: string | null;
      field_of_study?: string | null;
      description?: string | null;
    })
  | (DatedFact & {
      kind: 'experience';
      organization: string;
      role: string;
      description?: string | null;
    })
  | (DatedFact & {
      kind: 'project';
      name: string;
      role?: string | null;
      description?: string | null;
      technologies: string[];
    })
  | { kind: 'skill'; name: string; category?: string | null }
  | {
      kind: 'achievement';
      title: string;
      description?: string | null;
      occurred_on?: string | null;
    }
  | { kind: 'contact'; channel: 'email' | 'phone' | 'website' | 'other'; value: string }
  | { kind: 'location'; value: string };

export interface ConfirmedPersonalFact {
  id: string;
  value: PersonalFact;
  confirmed_source_kind: 'user_edit' | 'conversation_message' | 'draft_acceptance';
  confirmed_source_id: string | null;
  confirmed_at: string;
}

export interface DirectionCriteria {
  role_keywords: string[];
  seniority: string[];
  locations: string[];
  work_modes: Array<'onsite' | 'hybrid' | 'remote'>;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  industries: string[];
  technologies: string[];
  exclusions: string[];
}

export interface DirectionInput {
  label: string;
  criteria: DirectionCriteria;
  lifecycle: DirectionLifecycle;
  priority: number;
}

export interface CareerProfileDirection extends DirectionInput {
  id: string;
  confirmed_source_kind: string;
  confirmed_source_id: string | null;
  confirmed_at: string;
}

export interface CareerProfile {
  id: string;
  user_id: number;
  personal_facts: ConfirmedPersonalFact[];
  directions: CareerProfileDirection[];
  version: number;
  created_at: string;
  updated_at: string;
}

export interface FactDraftChange {
  operation: 'upsert' | 'remove';
  target_fact_id?: string | null;
  fact?: PersonalFact | null;
}

export interface DirectionDraftChange {
  operation: 'upsert' | 'archive';
  target_direction_id?: string | null;
  direction?: DirectionInput | null;
}

export interface CareerProfileDraft {
  id: string;
  career_profile_id: string;
  source_kind: 'artifact_version' | 'resume' | 'conversation_message' | 'model_inference';
  source_id: string;
  base_profile_version: number;
  proposed_facts: FactDraftChange[];
  proposed_directions: DirectionDraftChange[];
  status: 'pending' | 'accepted' | 'rejected';
  resolution_note: string | null;
  version: number;
  created_at: string;
  resolved_at: string | null;
  /** Present on the canonical 0029 projection; optional keeps cached/legacy
   * clients readable during a rolling deployment. */
  candidates?: CareerProfileCandidateItem[];
}

export interface CareerProfileCandidateItem {
  id: string;
  item_kind: 'fact' | 'direction';
  position: number;
  payload: FactDraftChange | DirectionDraftChange;
  conflict_kind: 'none' | 'duplicate' | 'conflict' | 'missing_target';
  current_value: Record<string, unknown> | null;
  status: 'pending' | 'accepted' | 'rejected';
  resolution_note: string | null;
  version: number;
  created_at: string;
  resolved_at: string | null;
}

export type AbilitySignalStatus = 'active' | 'disputed' | 'invalidated' | 'superseded';

export interface AbilitySignal {
  id: string;
  user_id: number;
  topic: string;
  signal_type: string;
  level: string | null;
  score: number | null;
  summary: string;
  confidence: number | null;
  limitations: string | null;
  scope_kind: 'general' | 'career_direction' | 'job_opportunity' | 'interview_record';
  scope_ref_id: string | null;
  formed_at: string;
  rubric_version: string | null;
  status: AbilitySignalStatus;
  status_reason: string | null;
  supersedes_signal_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  status_changed_at: string;
  sources: Array<{
    source_kind: string;
    source_id: string;
    source_version: string | null;
  }>;
}

export type JobPhase = 'pending_application' | 'applied' | 'in_process' | 'offer';
export type JobOutcome =
  | 'rejected'
  | 'withdrawn'
  | 'posting_closed'
  | 'declined_offer'
  | 'accepted';

export interface JobOpportunityDirectionLink {
  career_profile_direction_id: string;
  position: number;
  source_kind: 'user_assertion' | 'observation' | 'tool_result' | 'provider_receipt';
  source_identity: string;
  match_reason: string;
  confirmed_at: string;
}

export interface JobOpportunity {
  id: string;
  user_id: number;
  company_name: string;
  job_title: string;
  location: string | null;
  team: string | null;
  source_url: string | null;
  source_provider: string | null;
  external_job_id: string | null;
  external_application_id: string | null;
  phase: JobPhase;
  current_step: string;
  outcome: JobOutcome | null;
  archived_at: string | null;
  last_event_at: string | null;
  direction_version: number;
  direction_links: JobOpportunityDirectionLink[];
  created_at: string;
  updated_at: string;
}

export interface JobOpportunityMergeCandidate {
  duplicate_opportunity_id: string;
  canonical_opportunity_id: string;
  reasons: string[];
}

export interface JobOpportunityMerge {
  id: string;
  duplicate_opportunity_id: string;
  canonical_opportunity_id: string;
  status: 'active' | 'retracted';
  version: number;
  reason: string;
  confirmation_source_identity: string;
  created_at: string;
  updated_at: string;
  retraction_reason: string | null;
  retracted_at: string | null;
}

export type ProcessEventKind =
  | 'tracking_started'
  | 'preparation_started'
  | 'application_submitted'
  | 'application_acknowledged'
  | 'recruiter_contact'
  | 'assessment_invited'
  | 'assessment_completed'
  | 'hiring_step'
  | 'interview_scheduled'
  | 'interview_completed'
  | 'background_check_started'
  | 'offer_received'
  | 'rejected'
  | 'withdrawn'
  | 'posting_closed'
  | 'offer_declined'
  | 'offer_accepted';

export interface ProcessEvent {
  id: string;
  job_opportunity_id: string;
  sequence: number;
  operation: 'assert' | 'retract';
  kind: ProcessEventKind | 'retraction';
  occurred_at: string;
  observed_at: string;
  source_kind: 'user_assertion' | 'observation' | 'tool_result' | 'provider_receipt';
  source_identity: string;
  source_version: string | null;
  description: string;
  step_summary: string | null;
  analysis_context_json: Record<string, unknown>;
  corrects_event_id: string | null;
  created_at: string;
}

export type NextActionStatus = 'suggested' | 'planned' | 'done' | 'closed';
export type NextActionTimeKind = 'fixed' | 'deadline' | 'flexible';

export interface NextAction {
  id: string;
  user_id: number;
  job_opportunity_id: string | null;
  interview_record_id: string | null;
  offer_id: string | null;
  artifact_id: string | null;
  content: string;
  status: NextActionStatus;
  time_kind: NextActionTimeKind;
  starts_at: string | null;
  ends_at: string | null;
  due_at: string | null;
  original_time_text: string | null;
  source_timezone: string | null;
  source_kind: 'user_request' | 'process_event' | 'agent_suggestion' | 'copilot_preference' | 'offer';
  source_identity: string;
  source_version: string | null;
  planned_at: string | null;
  resolved_at: string | null;
  close_reason: string | null;
  reminder_at: string | null;
  reminder_next_attempt_at: string | null;
  reminder_channel: 'in_app' | null;
  reminder_delivered_at: string | null;
  reminder_dismissed_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ArtifactWriteInput {
  title: string;
  content_text?: string | null;
  content_format: string;
  file_asset_id?: string | null;
  file_asset_version?: string | null;
  provenance?: {
    source_message_id?: number | null;
    source_turn_id?: string | null;
    source_owner_type?: string | null;
    source_owner_id?: string | null;
  };
}

export interface ArtifactVersion {
  id: string;
  artifact_id: string;
  version_no: number;
  title: string;
  content_text: string | null;
  content_format: string;
  file_asset_id: string | null;
  file_asset_version: string | null;
  origin_kind: 'explicit_save' | 'message_promotion' | 'flow_delivery' | 'edit';
  source_message_id: number | null;
  source_turn_id: string | null;
  source_owner_type: string | null;
  source_owner_id: string | null;
  created_at: string;
}

export interface Artifact {
  id: string;
  kind: string;
  archived_at: string | null;
  current_version: ArtifactVersion;
}

export interface ArtifactRelation {
  id: string;
  artifact_id: string;
  job_opportunity_id: string;
  created_at: string;
}

export interface ArtifactSubmission {
  id: string;
  job_opportunity_id: string;
  artifact_id: string;
  artifact_version_id: string;
  basis: 'user_confirmation' | 'product_ui_confirmation' | 'external_receipt';
  confirmation_message_id: number | null;
  receipt_owner_type: string | null;
  receipt_owner_id: string | null;
  submitted_at: string;
  /** Immutable version frozen when this use assertion was recorded. */
  submitted_version: ArtifactVersion;
}

export interface OfferSourceInput {
  kind: 'user_assertion' | 'observation' | 'tool_result' | 'provider_receipt' | 'artifact' | 'file_asset';
  identity: string;
  version?: string | null;
  observed_at: string;
}

export interface OfferTermsInput {
  position_title?: string | null;
  location?: string | null;
  employment_type?: string | null;
  base_salary_amount?: string | number | null;
  currency?: string | null;
  pay_period?: 'hourly' | 'monthly' | 'annual' | 'total' | null;
  tax_basis?: 'gross' | 'net' | 'unspecified' | null;
  bonus_text?: string | null;
  equity_text?: string | null;
  benefits?: string[] | null;
  probation_text?: string | null;
  start_date?: string | null;
  response_deadline?: string | null;
  response_deadline_text?: string | null;
  response_deadline_timezone?: string | null;
  additional_terms?: Record<string, string> | null;
  formality: 'written' | 'verbal_confirmed' | 'verbal_pending_written';
  original_text: string;
}

export interface Offer {
  id: string;
  user_id: number;
  job_opportunity_id: string;
  terms_json: Record<string, unknown>;
  term_sources_json: Record<string, Record<string, unknown>>;
  source_excerpts_json: Record<string, Record<string, unknown>>;
  last_source_kind: OfferSourceInput['kind'];
  last_source_identity: string;
  last_source_version: string | null;
  last_source_observed_at: string;
  created_at: string;
  updated_at: string;
}

export interface OfferCurrent {
  offer: Offer;
  current_token: string;
}

export interface OfferTermsDiff {
  added: Record<string, unknown>;
  changed: Record<string, { current?: unknown; proposed?: unknown }>;
  removed: Record<string, unknown>;
}

export interface OfferConfirmationRequired {
  status: 'confirmation_required';
  offer_id: string;
  current_token: string;
  diff: OfferTermsDiff;
}

export interface OfferListItem {
  offer: Offer;
  current_token: string;
  company_name: string;
  job_title: string;
}

export interface NotificationPreference {
  enabled: boolean;
  default_channel: 'in_app';
  timezone: string;
  quiet_start: string | null;
  quiet_end: string | null;
  version: number;
}

export interface NextActionAgendaItem {
  action: NextAction;
  bucket: 'conflict' | 'today' | 'upcoming' | 'unscheduled_planned' | 'suggested';
  overdue: boolean;
  due_soon: boolean;
  conflict_action_ids: string[];
  duplicate_action_ids: string[];
}

export interface NextActionAgenda {
  generated_at: string;
  items: NextActionAgendaItem[];
}

export interface FunnelAnalysis {
  generated_at: string;
  sample_job_ids: string[];
  coverage: {
    sample_count: number;
    direction_snapshot_count: number;
    submitted_material_count: number;
    channel_count: number;
    jd_snapshot_count: number;
    outcome_count: number;
  };
  groups: Array<{
    direction_id: string | null;
    direction_label: string | null;
    submitted_artifact_version_id: string | null;
    channel: string | null;
    calendar_month: string;
    sample_job_ids: string[];
    stages: Array<{
      stage: 'applied' | 'in_process' | 'offer' | 'terminal';
      reached: number;
      conversion_from_sample: number;
      median_wait_hours: number | null;
    }>;
    outcomes: Record<string, number>;
  }>;
  missing_source_notes: string[];
  confounders: string[];
  interpretation_limit: string;
}

export interface OfferAnalysisItem {
  offer_id: string;
  job_opportunity_id: string;
  company_name: string;
  job_title: string;
  original_currency: string | null;
  annual_base_original: string | null;
  annual_base_in_base_currency: string | null;
  annual_bonus_in_base_currency: string | null;
  annual_equity_in_base_currency: string | null;
  estimated_after_tax_cash: string | null;
  estimated_total_value: string | null;
  missing_information: string[];
  risks: string[];
  assumptions: string[];
}

export interface OfferAnalysis {
  generated_at: string;
  base_currency: string;
  items: OfferAnalysisItem[];
  career_profile_constraints: string[];
  user_constraints: string[];
  source_observations: Array<{ identity: string; observed_at: string; url: string | null }>;
  report_markdown: string;
  artifact_id: string | null;
}
export interface JobDescriptionSnapshot {
  id: string
  job_opportunity_id: string
  version: number
  original_url: string
  normalized_url: string
  observed_at: string
  provider: string
  canonical_content: string
  content_checksum: string
  source_kind: 'tool_result' | 'typed_product_ui'
  source_identity: string
  source_version: string
  created_at: string
}
