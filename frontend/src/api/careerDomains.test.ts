import { beforeEach, describe, expect, it, vi } from 'vitest';

const client = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
}));

vi.mock('./client', () => ({ apiClient: client }));

import {
  createArtifactVersion,
  listArtifactRelations,
  listArtifactSubmissions,
  listArtifactVersions,
  listArtifacts,
} from './artifacts';
import {
  appendProcessEvent,
  correctProcessEvent,
  replaceJobOpportunityDirections,
} from './careerProcess';
import { savePersonalFact } from './careerProfile';
import { confirmOfferTerms, OfferConfirmationError, recordOffer } from './offers';
import {
  compareOffers,
  dismissReminder,
  updateNotificationPreference,
} from './careerInsights';

describe('career domain API clients', () => {
  beforeEach(() => Object.values(client).forEach((mock) => mock.mockReset()));

  it('writes a confirmed profile fact against the expected aggregate version', async () => {
    client.post.mockResolvedValue({ data: { version: 4 } });
    await savePersonalFact({
      profileVersion: 3,
      fact: { kind: 'skill', name: 'Python', category: '编程语言' },
    });
    expect(client.post).toHaveBeenCalledWith('/career-profile/facts', {
      expected_profile_version: 3,
      fact: { kind: 'skill', name: 'Python', category: '编程语言' },
      confirmation: { kind: 'user_edit' },
    });
  });

  it('appends a user-confirmed process event with its idempotency identity', async () => {
    client.post.mockResolvedValue({ data: { id: 'event-1' } });
    await appendProcessEvent({
      opportunityId: 'job/1', kind: 'interview_scheduled',
      occurredAt: '2026-08-13T10:00:00Z', description: '收到一面邀请',
      sourceIdentity: 'ui:event-1', idempotencyKey: 'event-1',
    });
    expect(client.post).toHaveBeenCalledWith(
      '/career-process/opportunities/job%2F1/events',
      expect.objectContaining({
        source_kind: 'user_assertion', source_identity: 'ui:event-1', idempotency_key: 'event-1',
      }),
    );
  });

  it('corrects a process fact by appending a correction command', async () => {
    client.post.mockResolvedValue({ data: { id: 'event-2' } });
    await correctProcessEvent({
      opportunityId: 'job-1', eventId: 'event-1', kind: 'interview_scheduled',
      occurredAt: '2026-08-14T10:00:00Z', description: '面试改到周五',
      sourceIdentity: 'ui:correction-1', idempotencyKey: 'correction-1',
    });
    expect(client.post).toHaveBeenCalledWith(
      '/career-process/opportunities/job-1/events/event-1/corrections',
      expect.objectContaining({ replacement_kind: 'interview_scheduled', source_kind: 'user_assertion' }),
    );
  });

  it('CAS-replaces the current CareerProfile direction relations', async () => {
    client.patch.mockResolvedValue({ data: { id: 'job-1', direction_version: 3 } });
    await replaceJobOpportunityDirections({
      opportunityId: 'job/1',
      expectedVersion: 2,
      sourceIdentity: 'ui:direction-update',
      directions: [{ direction_id: 'direction-1', match_reason: '岗位职责匹配' }],
    });
    expect(client.patch).toHaveBeenCalledWith(
      '/career-process/opportunities/job%2F1/directions',
      {
        expected_version: 2,
        source_kind: 'user_assertion',
        source_identity: 'ui:direction-update',
        directions: [{ direction_id: 'direction-1', match_reason: '岗位职责匹配' }],
      },
    );
  });

  it('creates an explicit new Artifact version', async () => {
    client.post.mockResolvedValue({ data: { id: 'artifact-1' } });
    await createArtifactVersion({
      artifactId: 'artifact-1', operationKey: 'op-2',
      version: { title: '简历', content_text: 'v2', content_format: 'markdown' },
    });
    expect(client.post).toHaveBeenCalledWith('/artifacts/artifact-1/versions', {
      operation_key: 'op-2',
      version: { title: '简历', content_text: 'v2', content_format: 'markdown' },
    });
  });

  it('loads the user Artifact list from the cloud authority', async () => {
    client.get.mockResolvedValue({ data: [] });
    await listArtifacts(true, 50, 10);
    expect(client.get).toHaveBeenCalledWith('/artifacts', {
      params: { include_archived: true, limit: 50, offset: 10 },
    });
  });

  it('reads Artifact versions, related jobs, and exact-version submissions', async () => {
    client.get.mockResolvedValue({ data: [] });
    await listArtifactVersions('artifact/1');
    await listArtifactRelations('artifact/1');
    await listArtifactSubmissions('artifact/1');
    expect(client.get.mock.calls).toEqual([
      ['/artifacts/artifact%2F1/versions'],
      ['/artifacts/artifact%2F1/related'],
      ['/artifacts/artifact%2F1/submissions'],
    ]);
  });

  it('surfaces the typed 409 Offer diff instead of flattening it to a string', async () => {
    const detail = {
      status: 'confirmation_required' as const,
      offer_id: 'offer-1', current_token: 'a'.repeat(64),
      diff: { added: {}, changed: { location: { current: '北京', proposed: '上海' } }, removed: {} },
    };
    client.post.mockRejectedValue({ response: { status: 409, data: { detail } } });
    const promise = recordOffer({
      opportunityId: 'job-1', operationKey: 'op-3',
      terms: { formality: 'written', original_text: 'offer' },
      source: { kind: 'artifact', identity: 'version-1', observed_at: '2026-08-13T10:00:00Z' },
    });
    await expect(promise).rejects.toBeInstanceOf(OfferConfirmationError);
    await expect(promise).rejects.toMatchObject({ confirmation: detail });
  });

  it('sends the selected Offer resolution as a typed first-party UI confirmation', async () => {
    client.post.mockResolvedValue({ data: { current_token: 'b'.repeat(64) } });
    await confirmOfferTerms({
      opportunityId: 'job-1', offerId: 'offer-1', operationKey: 'op-4',
      expectedCurrentToken: 'a'.repeat(64), resolution: 'supplement',
      terms: { formality: 'written', original_text: 'offer' },
      candidateSource: { kind: 'artifact', identity: 'version-2', observed_at: '2026-08-13T10:00:00Z' },
    });
    expect(client.post).toHaveBeenCalledWith(
      '/career-process/opportunities/job-1/offer/confirm-terms',
      expect.objectContaining({
        resolution: 'supplement',
        ui_confirmation: { kind: 'product_ui' },
      }),
    );
  });

  it('CAS-updates notification settings without creating a second reminder object', async () => {
    client.put.mockResolvedValue({ data: { version: 4 } });
    await updateNotificationPreference({
      enabled: true, default_channel: 'in_app', timezone: 'Asia/Shanghai',
      quiet_start: '22:00', quiet_end: '08:00', version: 3,
    });
    expect(client.put).toHaveBeenCalledWith('/career-insights/notification-preference', {
      expected_version: 3, enabled: true, default_channel: 'in_app', timezone: 'Asia/Shanghai',
      quiet_start: '22:00', quiet_end: '08:00',
    });
  });

  it('dismisses a delivered reminder through its NextAction CAS version', async () => {
    client.post.mockResolvedValue({ data: { version: 6 } });
    await dismissReminder({ id: 'action/1', version: 5 });
    expect(client.post).toHaveBeenCalledWith('/career-insights/reminders/action%2F1/dismiss', {
      expected_version: 5,
    });
  });

  it('keeps Offer comparison assumptions and source observation in the request', async () => {
    client.post.mockResolvedValue({ data: { items: [] } });
    await compareOffers({
      offer_ids: ['offer-1'], base_currency: 'CNY',
      exchange_rates: [{ currency: 'USD', rate_to_base: '7.2', source: { identity: 'central-bank', observed_at: '2026-08-13T10:00:00Z' } }],
      tax_assumptions: [], equity_assumptions: [], bonus_assumptions: [], user_constraints: [],
      save_artifact: true, operation_key: 'save-report',
    });
    expect(client.post).toHaveBeenCalledWith('/career-insights/offers/compare', expect.objectContaining({
      save_artifact: true, operation_key: 'save-report',
      exchange_rates: [expect.objectContaining({ source: expect.objectContaining({ identity: 'central-bank' }) })],
    }));
  });
});
