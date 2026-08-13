import { apiClient } from './client';
import type {
  FunnelAnalysis,
  NextAction,
  NextActionAgenda,
  NotificationPreference,
  OfferAnalysis,
} from '@/types/career';

export async function getNextActionAgenda(): Promise<NextActionAgenda> {
  return (await apiClient.get('/career-insights/next-actions/agenda')).data;
}

export async function getNotificationPreference(): Promise<NotificationPreference> {
  return (await apiClient.get('/career-insights/notification-preference')).data;
}

export async function updateNotificationPreference(input: NotificationPreference): Promise<NotificationPreference> {
  return (
    await apiClient.put('/career-insights/notification-preference', {
      expected_version: input.version,
      enabled: input.enabled,
      default_channel: input.default_channel,
      timezone: input.timezone,
      quiet_start: input.quiet_start,
      quiet_end: input.quiet_end,
    })
  ).data;
}

export async function listReminderInbox(): Promise<NextAction[]> {
  return (await apiClient.get('/career-insights/reminders/inbox')).data;
}

export async function dismissReminder(action: Pick<NextAction, 'id' | 'version'>): Promise<NextAction> {
  return (
    await apiClient.post(`/career-insights/reminders/${encodeURIComponent(action.id)}/dismiss`, {
      expected_version: action.version,
    })
  ).data;
}

export async function getFunnelAnalysis(params?: {
  direction_id?: string;
  submitted_artifact_version_id?: string;
  channel?: string;
  occurred_from?: string;
  occurred_to?: string;
}): Promise<FunnelAnalysis> {
  return (await apiClient.get('/career-insights/funnel', { params })).data;
}

export interface OfferComparisonInput {
  offer_ids: string[];
  base_currency: string;
  exchange_rates: Array<{
    currency: string;
    rate_to_base: string;
    source: { identity: string; observed_at: string; url?: string };
  }>;
  tax_assumptions: Array<{
    offer_id: string;
    effective_rate: string;
    jurisdiction: string;
    source: { identity: string; observed_at: string; url?: string };
  }>;
  equity_assumptions: Array<{
    offer_id: string;
    annual_value: string;
    currency: string;
    method: string;
    source: { identity: string; observed_at: string; url?: string };
  }>;
  bonus_assumptions: Array<{
    offer_id: string;
    annual_value: string;
    currency: string;
    basis: string;
    source: { identity: string; observed_at: string; url?: string };
  }>;
  user_constraints: string[];
  save_artifact: boolean;
  operation_key?: string;
}

export async function compareOffers(input: OfferComparisonInput): Promise<OfferAnalysis> {
  return (await apiClient.post('/career-insights/offers/compare', input)).data;
}

export async function createNegotiationDraft(input: {
  offerId: string;
  objective: string;
  tone: 'professional' | 'warm' | 'concise';
  constraints: string[];
  saveArtifact: boolean;
}): Promise<{ offer_id: string; draft_markdown: string; send_status: 'not_sent'; execution_note: string; artifact_id: string | null }> {
  return (
    await apiClient.post(`/career-insights/offers/${encodeURIComponent(input.offerId)}/negotiation-draft`, {
      objective: input.objective,
      tone: input.tone,
      constraints: input.constraints,
      save_artifact: input.saveArtifact,
      operation_key: input.saveArtifact ? crypto.randomUUID() : undefined,
    })
  ).data;
}
