import { apiClient } from './client';
import type { ProcessEventKind } from '@/types/career';
import type {
  GmailObservation,
  GmailObservationResolution,
  GmailObservationReviewCard,
  GmailObservationSyncResult,
} from '@/types/gmailObservation';

export async function listGmailObservations(): Promise<GmailObservation[]> {
  return (await apiClient.get('/gmail/observations')).data;
}

export async function syncGmailObservations(): Promise<GmailObservationSyncResult> {
  return (await apiClient.post('/gmail/observations/sync')).data;
}

export async function rebaselineGmailObservations(operationId: string): Promise<GmailObservationSyncResult> {
  return (
    await apiClient.post('/gmail/observations/rebaseline', {
      confirm_gap: true,
      user_request_identity: `product_ui:${operationId}`,
    })
  ).data;
}

export async function listGmailReviewCards(taskId: string): Promise<GmailObservationReviewCard[]> {
  return (
    await apiClient.get(
      `/persistent-tasks/${encodeURIComponent(taskId)}/gmail-review-cards`,
      { params: { statuses: ['pending'] } },
    )
  ).data;
}

export async function resolveGmailReviewCard(input: {
  taskId: string;
  card: GmailObservationReviewCard;
  decision: 'approve' | 'reject' | 'skip';
  operationId: string;
  opportunityId?: string;
  eventKind?: ProcessEventKind;
  description?: string;
  resolutionNote?: string;
}): Promise<GmailObservationResolution> {
  return (
    await apiClient.post(
      `/persistent-tasks/${encodeURIComponent(input.taskId)}/gmail-review-cards/${encodeURIComponent(input.card.id)}/resolve`,
      {
        expected_version: input.card.version,
        decision: input.decision,
        user_request_identity: `product_ui:${input.operationId}`,
        user_request_version: String(input.card.version),
        resolution_note: input.resolutionNote || undefined,
        ...(input.decision === 'approve'
          ? {
              opportunity_id: input.opportunityId || undefined,
              new_opportunity: input.opportunityId ? undefined : input.card.new_opportunity_json || undefined,
              event_kind: input.eventKind,
              description: input.description,
            }
          : {}),
      },
    )
  ).data;
}

export async function retractGmailObservation(
  observation: GmailObservation,
  reason: string,
  operationId: string,
): Promise<GmailObservation> {
  return (
    await apiClient.post(`/gmail/observations/${encodeURIComponent(observation.id)}/retract`, {
      expected_version: observation.version,
      occurred_at: new Date().toISOString(),
      reason,
      user_request_identity: `product_ui:${operationId}`,
      user_request_version: String(observation.version),
    })
  ).data;
}
