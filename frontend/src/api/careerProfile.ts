import { apiClient } from './client';
import type {
  AbilitySignal,
  CareerProfile,
  CareerProfileDraft,
  ConfirmationInput,
  DirectionInput,
  DirectionLifecycle,
  PersonalFact,
  CareerProfileCandidateItem,
} from '@/types/career';

export async function getCareerProfile(): Promise<CareerProfile> {
  return (await apiClient.get('/career-profile')).data;
}

export async function savePersonalFact(input: {
  profileVersion: number;
  fact: PersonalFact;
  factId?: string;
}): Promise<CareerProfile> {
  const body = {
    expected_profile_version: input.profileVersion,
    fact: input.fact,
    confirmation: { kind: 'user_edit' } satisfies ConfirmationInput,
  };
  const path = input.factId
    ? `/career-profile/facts/${encodeURIComponent(input.factId)}`
    : '/career-profile/facts';
  return (await (input.factId ? apiClient.put(path, body) : apiClient.post(path, body))).data;
}

export async function removePersonalFact(
  factId: string,
  profileVersion: number,
): Promise<CareerProfile> {
  return (
    await apiClient.delete(`/career-profile/facts/${encodeURIComponent(factId)}`, {
      data: {
        expected_profile_version: profileVersion,
        confirmation: { kind: 'user_edit' } satisfies ConfirmationInput,
      },
    })
  ).data;
}

export async function saveCareerDirection(input: {
  profileVersion: number;
  direction: DirectionInput;
  directionId?: string;
}): Promise<CareerProfile> {
  const body = {
    expected_profile_version: input.profileVersion,
    direction: input.direction,
    confirmation: { kind: 'user_edit' } satisfies ConfirmationInput,
  };
  const path = input.directionId
    ? `/career-profile/directions/${encodeURIComponent(input.directionId)}`
    : '/career-profile/directions';
  return (await (input.directionId ? apiClient.put(path, body) : apiClient.post(path, body))).data;
}

export async function setCareerDirectionLifecycle(
  directionId: string,
  profileVersion: number,
  lifecycle: DirectionLifecycle,
): Promise<CareerProfile> {
  return (
    await apiClient.patch(`/career-profile/directions/${encodeURIComponent(directionId)}/lifecycle`, {
      expected_profile_version: profileVersion,
      lifecycle,
      confirmation: { kind: 'user_edit' } satisfies ConfirmationInput,
    })
  ).data;
}

export async function listCareerProfileDrafts(): Promise<CareerProfileDraft[]> {
  return (await apiClient.get('/career-profile/drafts')).data;
}

export async function resolveCareerProfileDraft(input: {
  draft: CareerProfileDraft;
  profileVersion: number;
  decision: 'accept' | 'reject';
  note?: string;
}): Promise<CareerProfile | CareerProfileDraft> {
  return (
    await apiClient.post(
      `/career-profile/drafts/${encodeURIComponent(input.draft.id)}/${input.decision}`,
      {
        expected_draft_version: input.draft.version,
        expected_profile_version: input.decision === 'accept' ? input.profileVersion : undefined,
        resolution_note: input.note || undefined,
      },
    )
  ).data;
}

export async function resolveCareerProfileCandidates(input: {
  draft: CareerProfileDraft;
  profileVersion: number;
  decisions: Array<{
    item: CareerProfileCandidateItem;
    decision: 'accept' | 'reject';
    note?: string;
  }>;
}): Promise<{ profile: CareerProfile; draft: CareerProfileDraft }> {
  return (
    await apiClient.post(
      `/career-profile/drafts/${encodeURIComponent(input.draft.id)}/candidates/resolve`,
      {
        expected_draft_version: input.draft.version,
        expected_profile_version: input.profileVersion,
        decisions: input.decisions.map(({ item, decision, note }) => ({
          item_id: item.id,
          expected_version: item.version,
          decision,
          note,
        })),
      },
    )
  ).data;
}

export async function listAbilitySignals(includeInactive = false): Promise<AbilitySignal[]> {
  return (await apiClient.get('/ability-signals', { params: { include_inactive: includeInactive } })).data;
}

export async function changeAbilitySignalStatus(
  signal: AbilitySignal,
  action: 'dispute' | 'invalidate',
  reason: string,
): Promise<AbilitySignal> {
  return (
    await apiClient.post(`/ability-signals/${encodeURIComponent(signal.id)}/${action}`, {
      expected_version: signal.version,
      reason,
    })
  ).data;
}

export async function recomputeInterviewAbilitySignals(
  interviewRecordId: string,
): Promise<AbilitySignal[]> {
  return (
    await apiClient.post(
      `/interviews/${encodeURIComponent(interviewRecordId)}/ability-signals/recompute`,
      {},
    )
  ).data;
}
